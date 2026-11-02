"""
Tasks Celery para geração assíncrona de dietas.

Em produção (com Redis):
    O worker executa esta task em processo separado, liberando o gunicorn
    para servir outras requisições enquanto a IA processa.

Em dev (sem Redis / CELERY_TASK_ALWAYS_EAGER=True):
    A task roda de forma síncrona no mesmo processo Django — comportamento
    idêntico ao antigo fluxo síncrono, sem necessidade de worker separado.

Garantias de consistência:
    - Transição pending → processing é condicional (UPDATE ... WHERE status='pending'),
      então uma mensagem reentregue (acks_late) ou duplicada não processa o job duas vezes.
    - A criação do DietPlan + Meals e a marcação do job como 'done' ocorrem na mesma
      transação; se o job foi expirado/marcado 'failed' enquanto a IA respondia,
      o plano é descartado (rollback) em vez de sobrescrever o estado do job.
    - error_message guarda apenas mensagens amigáveis em português; o detalhe
      técnico da exceção vai somente para o log.
"""

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import transaction
from django.utils import timezone

from .services import DietGenerationError, PermanentAIError, TransientAIError

logger = logging.getLogger(__name__)

# Limites de tempo da task. O pior caso real do AIService é ~3 chamadas HTTP com
# timeout de 120s e até 3 tentativas cada; na prática a geração leva 30–90s.
# O soft limit levanta SoftTimeLimitExceeded (tratado abaixo); o hard limit mata o processo.
TASK_SOFT_TIME_LIMIT = 8 * 60    # 8 min
TASK_TIME_LIMIT = 9 * 60         # 9 min
RETRY_COUNTDOWN = 15             # segundos entre retries de falhas transitórias

# Mensagens específicas por subclasse de TransientAIError (após esgotar retries)
_USER_MESSAGES = {
    'AllergenViolation': (
        'Não foi possível gerar um plano respeitando suas alergias após '
        'várias tentativas. Verifique se o campo de alergias está claro '
        '(ex: "amendoim, leite, frutos do mar") ou contate o suporte.'
    ),
    'RestrictionViolation': (
        'Não foi possível gerar um plano respeitando suas restrições alimentares '
        '(ex: vegetariano, sem lactose) após várias tentativas. Revise as '
        'restrições informadas no questionário ou contate o suporte.'
    ),
    'NutritionDataGap': (
        'Não conseguimos gerar um plano com cálculos calóricos confiáveis '
        'após várias tentativas. Tente reformular suas preferências '
        'alimentares com termos mais comuns ou contate o suporte.'
    ),
    'MacroImbalanceError': (
        'Não conseguimos gerar um plano com macronutrientes equilibrados '
        'após várias tentativas. Tente ajustar suas preferências alimentares '
        'incluindo mais fontes de proteína (frango, ovos, peixe) ou contate o suporte.'
    ),
}

MSG_TRANSIENT = (
    'O serviço de IA está instável no momento e não conseguimos gerar sua dieta. '
    'Aguarde alguns minutos e tente novamente.'
)
MSG_PERMANENT = (
    'Não foi possível gerar sua dieta por um problema de configuração do serviço. '
    'Nossa equipe foi notificada; tente novamente mais tarde.'
)
MSG_GENERATION = (
    'Não foi possível gerar um plano alimentar válido com os dados informados. '
    'Revise o questionário e tente novamente.'
)
MSG_TIMEOUT = (
    'A geração da dieta demorou mais que o esperado e foi interrompida. '
    'Tente gerar sua dieta novamente.'
)
MSG_UNEXPECTED = 'Ocorreu um erro inesperado ao gerar sua dieta. Tente novamente em instantes.'


def user_message_for(exc: BaseException) -> str:
    """Traduz uma exceção da geração em mensagem amigável (nunca expõe str(exc))."""
    if isinstance(exc, SoftTimeLimitExceeded):
        return MSG_TIMEOUT
    if isinstance(exc, TransientAIError):
        return _USER_MESSAGES.get(type(exc).__name__, MSG_TRANSIENT)
    if isinstance(exc, PermanentAIError):
        return MSG_PERMANENT
    if isinstance(exc, DietGenerationError):
        return MSG_GENERATION
    return MSG_UNEXPECTED


class _JobNoLongerProcessing(Exception):
    """Sinaliza que o job saiu de 'processing' durante a geração — força rollback do plano."""


def _mark_failed(job_id: int, exc: BaseException) -> None:
    """Marca o job como failed apenas se ainda estiver em andamento (não sobrescreve done)."""
    from .models import DietJob

    DietJob.objects.filter(
        pk=job_id,
        status__in=[DietJob.STATUS_PENDING, DietJob.STATUS_PROCESSING],
    ).update(
        status=DietJob.STATUS_FAILED,
        error_message=user_message_for(exc),
        updated_at=timezone.now(),
    )


@shared_task(
    bind=True,
    max_retries=2,
    name='nutrition.tasks.generate_diet',
    acks_late=True,                      # reentrega se o worker morrer no meio
    soft_time_limit=TASK_SOFT_TIME_LIMIT,
    time_limit=TASK_TIME_LIMIT,
)
def generate_diet_task(self, job_id: int) -> None:
    """
    Executa a geração de dieta via IA para um DietJob existente.

    Retry automático (até 2 tentativas com intervalo de 15s) para
    TransientAIError (rede/API instável, formato inválido, cobertura nutricional,
    alergias, desequilíbrio de macros). PermanentAIError, DietGenerationError
    genérico e exceções inesperadas não são retentadas.
    """
    from .models import DietJob
    from .services import AIService

    # Transição condicional pending → processing: só um executor "ganha" o job.
    claimed = DietJob.objects.filter(pk=job_id, status=DietJob.STATUS_PENDING).update(
        status=DietJob.STATUS_PROCESSING,
        updated_at=timezone.now(),
    )
    if not claimed:
        current = DietJob.objects.filter(pk=job_id).values_list('status', flat=True).first()
        if current is None:
            logger.error('generate_diet_task: DietJob#%s não encontrado.', job_id)
        else:
            logger.warning(
                'generate_diet_task: DietJob#%s ignorado — status atual: %s.', job_id, current,
            )
        return

    job = DietJob.objects.select_related('anamnese', 'user').get(pk=job_id)

    logger.info(
        'generate_diet_task: iniciando geração para DietJob#%s (usuário %s, tentativa %d/%d).',
        job_id, job.user_id, self.request.retries + 1, self.max_retries + 1,
    )

    try:
        if job.anamnese is None:
            raise PermanentAIError('DietJob sem anamnese associada.')

        # Plano + refeições + status do job na mesma transação. As chamadas à IA
        # acontecem antes de qualquer escrita, então a transação só fica aberta
        # (de fato) durante a persistência.
        with transaction.atomic():
            diet_plan = AIService().generate_diet(job.anamnese)
            updated = DietJob.objects.filter(
                pk=job_id, status=DietJob.STATUS_PROCESSING,
            ).update(
                status=DietJob.STATUS_DONE,
                diet_plan=diet_plan,
                error_message='',
                updated_at=timezone.now(),
            )
            if not updated:
                raise _JobNoLongerProcessing()

        logger.info(
            'generate_diet_task: DietJob#%s concluído → DietPlan#%s.', job_id, diet_plan.pk,
        )

    except _JobNoLongerProcessing:
        logger.warning(
            'generate_diet_task: DietJob#%s expirou/foi cancelado durante a geração — '
            'plano descartado.', job_id,
        )

    except TransientAIError as exc:
        if self.request.retries < self.max_retries:
            logger.warning(
                'generate_diet_task: DietJob#%s — falha transitória (%s), reagendando retry %d. Erro: %s',
                job_id, type(exc).__name__, self.request.retries + 1, exc,
            )
            # Devolve para pending para o retry conseguir reivindicar o job de novo
            DietJob.objects.filter(pk=job_id, status=DietJob.STATUS_PROCESSING).update(
                status=DietJob.STATUS_PENDING,
                updated_at=timezone.now(),
            )
            raise self.retry(exc=exc, countdown=RETRY_COUNTDOWN)

        _mark_failed(job_id, exc)
        logger.error(
            'generate_diet_task: DietJob#%s falhou definitivamente — %s: %s',
            job_id, type(exc).__name__, exc,
        )

    except SoftTimeLimitExceeded as exc:
        _mark_failed(job_id, exc)
        logger.error('generate_diet_task: DietJob#%s excedeu o tempo limite.', job_id)

    except PermanentAIError as exc:
        _mark_failed(job_id, exc)
        logger.error('generate_diet_task: DietJob#%s erro permanente — %s', job_id, exc)

    except DietGenerationError as exc:
        _mark_failed(job_id, exc)
        logger.error(
            'generate_diet_task: DietJob#%s erro de geração — %s: %s',
            job_id, type(exc).__name__, exc,
        )

    except Exception as exc:
        _mark_failed(job_id, exc)
        logger.error(
            'generate_diet_task: DietJob#%s falhou — %s', job_id, exc, exc_info=True,
        )
