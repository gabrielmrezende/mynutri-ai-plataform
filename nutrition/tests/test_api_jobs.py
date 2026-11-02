"""
Testes de API e task — ciclo de vida do DietJob (geração assíncrona).

Cobre:
  - expiração de jobs presos (pending > 10 min, processing > 15 min)
  - enfileiramento via transaction.on_commit e falha do broker
  - cota diária: jobs falhos não consomem
  - idempotência da task (transição condicional pending → processing)
  - update final condicional (job expirado durante a geração não vira 'done')
  - atomicidade plano + job
  - mensagens de erro amigáveis por classe de exceção (C6)
  - IDOR no status de job
  - throttle scopes próprios (job_status, anamnese)
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from nutrition.models import Anamnese, DietJob, DietPlan, Meal
from nutrition.services import (
    AllergenViolation,
    DietGenerationError,
    MacroImbalanceError,
    NutritionDataGap,
    PermanentAIError,
    TransientAIError,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def user(db):
    return User.objects.create_user(
        username='jobs@api.com', email='jobs@api.com', password='senhaSegura123',
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        username='outro@api.com', email='outro@api.com', password='senhaSegura123',
    )


def _client_for(u):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(u).access_token}')
    return client


@pytest.fixture
def client(user):
    return _client_for(user)


@pytest.fixture
def anamnese(user):
    return Anamnese.objects.create(
        user=user, age=30, gender='M', weight_kg=80, height_cm=180,
        activity_level='moderate', goal='maintain', meals_per_day=3,
    )


def _make_plan(u, anamnese=None):
    return DietPlan.objects.create(
        user=u, anamnese=anamnese,
        raw_response={'macros': {'protein_g': 100, 'carbs_g': 200, 'fat_g': 50}, 'meals': []},
        total_calories=1800, goal_description='Teste',
    )


def _age_job(job, minutes):
    """Retrocede updated_at (auto_now) via update() para simular job antigo."""
    DietJob.objects.filter(pk=job.pk).update(
        updated_at=timezone.now() - timedelta(minutes=minutes),
    )


# ---------------------------------------------------------------------------
# Expiração de jobs presos
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestJobExpiration:

    def test_pending_antigo_expira_no_status(self, client, user, anamnese):
        job = DietJob.objects.create(user=user, anamnese=anamnese)
        _age_job(job, 11)

        r = client.get(f'/api/v1/diet/status/{job.pk}')

        assert r.status_code == 200
        assert r.data['status'] == DietJob.STATUS_FAILED
        assert 'tente' in r.data['error'].lower()

    def test_pending_recente_nao_expira(self, client, user, anamnese):
        job = DietJob.objects.create(user=user, anamnese=anamnese)
        _age_job(job, 5)

        r = client.get(f'/api/v1/diet/status/{job.pk}')
        assert r.data['status'] == DietJob.STATUS_PENDING

    def test_processing_ate_15min_nao_expira(self, client, user, anamnese):
        """Geração real pode durar vários minutos — 5 min não pode ser 'travado'."""
        job = DietJob.objects.create(user=user, anamnese=anamnese, status=DietJob.STATUS_PROCESSING)
        _age_job(job, 10)

        r = client.get(f'/api/v1/diet/status/{job.pk}')
        assert r.data['status'] == DietJob.STATUS_PROCESSING

    def test_processing_antigo_expira(self, client, user, anamnese):
        job = DietJob.objects.create(user=user, anamnese=anamnese, status=DietJob.STATUS_PROCESSING)
        _age_job(job, 16)

        r = client.get(f'/api/v1/diet/status/{job.pk}')
        assert r.data['status'] == DietJob.STATUS_FAILED

    @patch('nutrition.views.generate_diet_task.delay')
    def test_generate_com_pending_antigo_cria_novo_job(self, mock_delay, client, user, anamnese,
                                                       django_capture_on_commit_callbacks):
        old = DietJob.objects.create(user=user, anamnese=anamnese)
        _age_job(old, 30)

        with django_capture_on_commit_callbacks(execute=True):
            r = client.post('/api/v1/diet/generate', format='json')

        assert r.status_code == 202
        assert r.data['job_id'] != old.pk
        old.refresh_from_db()
        assert old.status == DietJob.STATUS_FAILED
        mock_delay.assert_called_once_with(r.data['job_id'])

    @patch('nutrition.views.generate_diet_task.delay')
    def test_generate_com_job_em_andamento_reutiliza(self, mock_delay, client, user, anamnese):
        job = DietJob.objects.create(user=user, anamnese=anamnese)

        r = client.post('/api/v1/diet/generate', format='json')

        assert r.status_code == 202
        assert r.data['job_id'] == job.pk
        assert DietJob.objects.filter(user=user).count() == 1
        mock_delay.assert_not_called()

    def test_expiracao_nao_afeta_outro_usuario(self, client, other_user):
        a = Anamnese.objects.create(
            user=other_user, age=30, gender='F', weight_kg=60, height_cm=165,
            activity_level='light', goal='maintain',
        )
        job = DietJob.objects.create(user=other_user, anamnese=a)
        _age_job(job, 60)

        # Polling de outro usuário não pode mexer nos jobs deste
        client.get('/api/v1/diet/status/999999')
        job.refresh_from_db()
        assert job.status == DietJob.STATUS_PENDING


# ---------------------------------------------------------------------------
# Enfileiramento
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestEnqueue:

    @patch('nutrition.views.generate_diet_task.delay')
    def test_delay_so_apos_commit(self, mock_delay, client, anamnese,
                                  django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            r = client.post('/api/v1/diet/generate', format='json')
        assert r.status_code == 202
        mock_delay.assert_not_called()
        assert len(callbacks) == 1
        callbacks[0]()
        mock_delay.assert_called_once_with(r.data['job_id'])

    @patch('nutrition.views.generate_diet_task.delay', side_effect=ConnectionError('redis down'))
    def test_broker_fora_marca_failed(self, mock_delay, client, anamnese,
                                      django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            r = client.post('/api/v1/diet/generate', format='json')

        assert r.status_code == 202
        job = DietJob.objects.get(pk=r.data['job_id'])
        assert job.status == DietJob.STATUS_FAILED
        assert 'redis' not in job.error_message.lower()

        status_r = client.get(f'/api/v1/diet/status/{job.pk}')
        assert status_r.data['status'] == DietJob.STATUS_FAILED


# ---------------------------------------------------------------------------
# Cota diária — jobs falhos não consomem
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDailyQuota:

    @override_settings(DIET_GENERATE_DAILY_LIMIT=2)
    @patch('nutrition.views.generate_diet_task.delay')
    def test_jobs_concluidos_consomem_cota(self, mock_delay, client, user, anamnese):
        for _ in range(2):
            DietJob.objects.create(user=user, anamnese=anamnese, status=DietJob.STATUS_DONE)

        r = client.post('/api/v1/diet/generate', format='json')

        assert r.status_code == 429
        assert 'limite' in r.data['error'].lower()

    @override_settings(DIET_GENERATE_DAILY_LIMIT=2)
    @patch('nutrition.views.generate_diet_task.delay')
    def test_jobs_falhos_nao_consomem_cota(self, mock_delay, client, user, anamnese):
        for _ in range(5):
            DietJob.objects.create(user=user, anamnese=anamnese, status=DietJob.STATUS_FAILED)
        DietJob.objects.create(user=user, anamnese=anamnese, status=DietJob.STATUS_DONE)

        r = client.post('/api/v1/diet/generate', format='json')
        assert r.status_code == 202

    @override_settings(DIET_GENERATE_DAILY_LIMIT=1)
    @patch('nutrition.views.generate_diet_task.delay')
    def test_jobs_antigos_nao_consomem_cota(self, mock_delay, client, user, anamnese):
        old = DietJob.objects.create(user=user, anamnese=anamnese, status=DietJob.STATUS_DONE)
        DietJob.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))

        r = client.post('/api/v1/diet/generate', format='json')
        assert r.status_code == 202

    @override_settings(DIET_GENERATE_DAILY_LIMIT=1)
    @patch('nutrition.views.generate_diet_task.delay')
    def test_job_expirado_nao_consome_cota(self, mock_delay, client, user, anamnese):
        stuck = DietJob.objects.create(user=user, anamnese=anamnese, status=DietJob.STATUS_PROCESSING)
        _age_job(stuck, 20)

        r = client.post('/api/v1/diet/generate', format='json')
        assert r.status_code == 202
        assert r.data['job_id'] != stuck.pk


# ---------------------------------------------------------------------------
# Task — concorrência, atomicidade e mensagens
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTaskConsistency:

    @pytest.fixture
    def job(self, user, anamnese):
        return DietJob.objects.create(user=user, anamnese=anamnese)

    @patch('nutrition.services.AIService.generate_diet')
    def test_job_processing_nao_reprocessado(self, mock_gen, job):
        """Mensagem reentregue (acks_late) enquanto outro worker processa: ignora."""
        DietJob.objects.filter(pk=job.pk).update(status=DietJob.STATUS_PROCESSING)
        from nutrition.tasks import generate_diet_task
        generate_diet_task.delay(job.pk)
        assert not mock_gen.called

    @patch('nutrition.services.AIService.generate_diet')
    def test_job_failed_nao_reprocessado(self, mock_gen, job):
        DietJob.objects.filter(pk=job.pk).update(status=DietJob.STATUS_FAILED)
        from nutrition.tasks import generate_diet_task
        generate_diet_task.delay(job.pk)
        assert not mock_gen.called

    @patch('nutrition.services.AIService.generate_diet')
    def test_job_expirado_durante_geracao_descarta_plano(self, mock_gen, job, user, anamnese):
        def _gen(anam):
            plan = _make_plan(user, anam)
            Meal.objects.create(diet_plan=plan, meal_name='X', description='x', calories=1, order=0)
            # Enquanto a IA respondia, o polling expirou o job
            DietJob.objects.filter(pk=job.pk).update(
                status=DietJob.STATUS_FAILED, error_message='expirado',
            )
            return plan
        mock_gen.side_effect = _gen

        from nutrition.tasks import generate_diet_task
        generate_diet_task.delay(job.pk)

        job.refresh_from_db()
        # Em produção o expirador commita em outra transação e o job fica 'failed';
        # aqui (mesma conexão) o rollback também desfaz a simulação. O essencial:
        # o job NÃO vira 'done' e nenhum plano órfão é persistido.
        assert job.status != DietJob.STATUS_DONE
        assert job.diet_plan_id is None
        # Plano + refeições revertidos junto (mesma transação)
        assert DietPlan.objects.filter(user=user).count() == 0
        assert Meal.objects.count() == 0

    @patch('nutrition.services.AIService.generate_diet')
    def test_sucesso_limpa_e_vincula_plano(self, mock_gen, job, user, anamnese):
        mock_gen.side_effect = lambda anam: _make_plan(user, anam)
        from nutrition.tasks import generate_diet_task
        generate_diet_task.delay(job.pk)
        job.refresh_from_db()
        assert job.status == DietJob.STATUS_DONE
        assert job.diet_plan is not None
        assert job.error_message == ''

    @override_settings(CELERY_TASK_EAGER_PROPAGATES=False)
    @patch('nutrition.services.AIService.generate_diet')
    def test_retry_transitorio_volta_para_pending_e_conclui(self, mock_gen, job, user, anamnese):
        states = []

        def _gen(anam):
            states.append(DietJob.objects.get(pk=job.pk).status)
            if len(states) == 1:
                raise TransientAIError('API da IA indisponível após 3 tentativas: <urlopen error>')
            return _make_plan(user, anam)
        mock_gen.side_effect = _gen

        from nutrition.tasks import generate_diet_task
        generate_diet_task.delay(job.pk)

        job.refresh_from_db()
        assert states == [DietJob.STATUS_PROCESSING, DietJob.STATUS_PROCESSING]
        assert job.status == DietJob.STATUS_DONE

    def test_task_tem_acks_late_e_time_limits(self):
        from nutrition.tasks import generate_diet_task
        assert generate_diet_task.acks_late is True
        assert generate_diet_task.soft_time_limit
        assert generate_diet_task.time_limit > generate_diet_task.soft_time_limit
        # O expirador de 'processing' precisa ser mais longo que o hard limit da task
        from nutrition.views import PROCESSING_JOB_TIMEOUT
        assert PROCESSING_JOB_TIMEOUT.total_seconds() > generate_diet_task.time_limit

    def test_job_sem_anamnese_falha_com_mensagem_amigavel(self, user):
        job = DietJob.objects.create(user=user, anamnese=None)
        from nutrition.tasks import generate_diet_task
        generate_diet_task.delay(job.pk)
        job.refresh_from_db()
        assert job.status == DietJob.STATUS_FAILED
        assert 'DietJob' not in job.error_message


@pytest.mark.django_db
class TestFriendlyErrorMessages:
    """C6: error_message nunca contém str(exc) bruto."""

    @pytest.fixture
    def job(self, user, anamnese):
        return DietJob.objects.create(user=user, anamnese=anamnese)

    @pytest.mark.parametrize('exc, expected_fragment', [
        (PermanentAIError('AI_API_KEY inválida: sk-xxx HTTP 401'), 'configuração'),
        (DietGenerationError('detalhe interno xyz'), 'questionário'),
        (ValueError('Traceback interno com dados'), 'erro inesperado'),
        (KeyError('meals'), 'erro inesperado'),
    ])
    @patch('nutrition.services.AIService.generate_diet')
    def test_excecoes_nao_transitorias(self, mock_gen, exc, expected_fragment, job):
        mock_gen.side_effect = exc
        from nutrition.tasks import generate_diet_task
        generate_diet_task.delay(job.pk)
        job.refresh_from_db()
        assert job.status == DietJob.STATUS_FAILED
        assert str(exc) not in job.error_message
        assert expected_fragment in job.error_message.lower()

    @pytest.mark.parametrize('exc_cls, expected_fragment', [
        (TransientAIError, 'instável'),
        (AllergenViolation, 'alergias'),
        (NutritionDataGap, 'calóricos'),
        (MacroImbalanceError, 'macronutrientes'),
    ])
    @override_settings(CELERY_TASK_EAGER_PROPAGATES=False)
    @patch('nutrition.services.AIService.generate_diet')
    def test_excecoes_transitorias_apos_retries(self, mock_gen, exc_cls, expected_fragment, job):
        mock_gen.side_effect = exc_cls('detalhe técnico: HTTP 502 from upstream')
        from nutrition.tasks import generate_diet_task
        generate_diet_task.delay(job.pk)
        job.refresh_from_db()
        assert job.status == DietJob.STATUS_FAILED
        assert 'HTTP 502' not in job.error_message
        assert expected_fragment in job.error_message.lower()
        assert mock_gen.call_count == 3

    @patch('nutrition.services.AIService.generate_diet')
    def test_soft_time_limit(self, mock_gen, job):
        from celery.exceptions import SoftTimeLimitExceeded
        mock_gen.side_effect = SoftTimeLimitExceeded()
        from nutrition.tasks import generate_diet_task
        generate_diet_task.delay(job.pk)
        job.refresh_from_db()
        assert job.status == DietJob.STATUS_FAILED
        assert 'demorou' in job.error_message.lower()

    @patch('nutrition.services.AIService.generate_diet')
    def test_status_endpoint_devolve_mensagem_amigavel(self, mock_gen, job, client):
        mock_gen.side_effect = RuntimeError('psycopg2.OperationalError: connection to 10.0.0.3 refused')
        from nutrition.tasks import generate_diet_task
        generate_diet_task.delay(job.pk)

        r = client.get(f'/api/v1/diet/status/{job.pk}')
        assert r.data['status'] == DietJob.STATUS_FAILED
        assert '10.0.0.3' not in r.data['error']
        assert 'psycopg2' not in r.data['error']


# ---------------------------------------------------------------------------
# IDOR + throttle scopes
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestJobIDOR:

    def test_status_de_job_alheio_404_e_nao_expira(self, client, other_user):
        a = Anamnese.objects.create(
            user=other_user, age=30, gender='F', weight_kg=60, height_cm=165,
            activity_level='light', goal='maintain',
        )
        job = DietJob.objects.create(user=other_user, anamnese=a)
        _age_job(job, 60)

        r = client.get(f'/api/v1/diet/status/{job.pk}')

        assert r.status_code == 404
        job.refresh_from_db()
        assert job.status == DietJob.STATUS_PENDING


class TestThrottleScopes:

    def test_status_tem_scope_proprio(self):
        from nutrition.views import DietJobStatusAPIView
        assert DietJobStatusAPIView.throttle_scope == 'job_status'

    def test_anamnese_tem_scope_proprio(self):
        from nutrition.views import AnamneseAPIView
        assert AnamneseAPIView.throttle_scope == 'anamnese'

    def test_settings_de_producao_tem_rates(self):
        """Os scopes usados nas views precisam existir em settings.py (senão 500 em prod)."""
        import importlib
        prod = importlib.import_module('mynutri.settings')
        rates = prod.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
        for scope in ('job_status', 'anamnese', 'diet_generate', 'user', 'anon'):
            assert scope in rates
        assert prod.REST_FRAMEWORK.get('NUM_PROXIES') is not None

    @pytest.mark.django_db
    @override_settings(REST_FRAMEWORK={
        'DEFAULT_AUTHENTICATION_CLASSES': (
            'rest_framework_simplejwt.authentication.JWTAuthentication',
        ),
        'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
        'DEFAULT_THROTTLE_CLASSES': [],
        'DEFAULT_THROTTLE_RATES': {
            'anon': '1000/hour', 'user': '1000/hour', 'diet_generate': '1000/day',
            'job_status': '1000/hour', 'anamnese': '2/hour',
        },
    })
    def test_anamnese_throttle_aplica(self, client):
        payload = {
            'idade': 30, 'sexo': 'M', 'peso': 80, 'altura': 180,
            'nivel_atividade': 'moderate', 'objetivo': 'maintain', 'meals_per_day': 3,
        }
        codes = [client.post('/api/v1/anamnese', payload, format='json').status_code for _ in range(3)]
        assert codes[-1] == 429
