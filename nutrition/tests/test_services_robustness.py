"""
Robustez do AIService frente a falhas da API e a valores absurdos do LLM.

Cobre:
  - Classificação de erros HTTP (4xx permanente; 429/5xx transitório com
    Retry-After e jitter) sem embrulhar em Exception genérica
  - Erros de parse (quantity_g inválido) viram TransientAIError
  - Clamp de quantity_g e quantidades inválidas contando como lacuna
  - Matching do nutrition_db: palavra principal, preparos bloqueados,
    fuzzy fraco conta como lacuna
  - Logs sem conteúdo do LLM; AI_MODEL lido de settings

Os testes de HTTP fazem patch apenas em urllib.request.urlopen e time.sleep.
"""

import io
import json
import logging
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from nutrition.models import Anamnese, DietPlan
from nutrition.nutrition_db import lookup_food_nutrition
from nutrition.services import (
    AIService,
    NutritionDataGap,
    PermanentAIError,
    TransientAIError,
)

User = get_user_model()

_SECRET_KEY = 'sk-super-secret-key-123'
_SECRET_URL = 'https://internal-llm.example.com/v1/chat/completions'


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def service():
    s = AIService()
    s.api_key = _SECRET_KEY
    s.api_url = _SECRET_URL
    return s


def _http_error(code, headers=None):
    return urllib.error.HTTPError(_SECRET_URL, code, 'erro', headers or {}, io.BytesIO(b'{"error": "detalhe interno"}'))


def _ok_response(content: dict, usage=None):
    body = {'choices': [{'message': {'content': json.dumps(content)}}]}
    if usage:
        body['usage'] = usage
    resp = MagicMock()
    resp.read.return_value = json.dumps(body).encode('utf-8')
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: False
    return resp


@pytest.fixture
def anamnese(db):
    user = User.objects.create_user(username='robust@test.com', email='robust@test.com', password='Senha-123')
    return Anamnese.objects.create(
        user=user, age=30, gender='M', weight_kg=80, height_cm=180,
        activity_level='moderate', goal='maintain', meals_per_day=3,
        food_restrictions='', food_preferences='', allergies='',
    )


# ─────────────────────────────────────────────────────────────────────────────
#  _call_api — classificação de erros HTTP
# ─────────────────────────────────────────────────────────────────────────────

class TestCallApiErrors:

    @pytest.mark.parametrize('code', [400, 401, 403, 404, 422])
    def test_4xx_e_permanente_sem_retry(self, service, code):
        with patch('urllib.request.urlopen', side_effect=_http_error(code)) as m_open, \
             patch('time.sleep') as m_sleep:
            with pytest.raises(PermanentAIError) as exc_info:
                service._call_api('p', 's')
        assert m_open.call_count == 1
        m_sleep.assert_not_called()
        msg = str(exc_info.value)
        assert _SECRET_KEY not in msg and _SECRET_URL not in msg

    @pytest.mark.parametrize('code', [429, 500, 502, 503])
    def test_429_e_5xx_sao_transitorios_com_retry(self, service, code):
        with patch('urllib.request.urlopen', side_effect=_http_error(code)) as m_open, \
             patch('time.sleep') as m_sleep:
            with pytest.raises(TransientAIError) as exc_info:
                service._call_api('p', 's', max_retries=3)
        assert m_open.call_count == 3
        # Não dorme depois da última tentativa
        assert m_sleep.call_count == 2
        msg = str(exc_info.value)
        assert _SECRET_KEY not in msg and _SECRET_URL not in msg
        assert 'detalhe interno' not in msg

    def test_retry_after_e_respeitado(self, service):
        err = _http_error(429, {'Retry-After': '7'})
        with patch('urllib.request.urlopen', side_effect=[err, _ok_response({'ok': 1})]), \
             patch('time.sleep') as m_sleep:
            service._call_api('p', 's', max_retries=3)
        waited = m_sleep.call_args[0][0]
        assert 7 <= waited <= 8

    def test_retry_after_tem_teto(self, service):
        err = _http_error(503, {'Retry-After': '3600'})
        with patch('urllib.request.urlopen', side_effect=[err, _ok_response({'ok': 1})]), \
             patch('time.sleep') as m_sleep:
            service._call_api('p', 's', max_retries=3)
        assert m_sleep.call_args[0][0] <= 31

    def test_backoff_tem_jitter(self, service):
        waits = []
        for _ in range(5):
            with patch('urllib.request.urlopen', side_effect=[_http_error(500), _ok_response({'ok': 1})]), \
                 patch('time.sleep') as m_sleep:
                service._call_api('p', 's', max_retries=3)
            waits.append(m_sleep.call_args[0][0])
        assert all(1 <= w <= 2 for w in waits)
        assert len(set(waits)) > 1

    def test_erro_de_rede_e_transitorio(self, service):
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('dns')), \
             patch('time.sleep'):
            with pytest.raises(TransientAIError):
                service._call_api('p', 's', max_retries=2)

    def test_corpo_nao_json_e_transitorio(self, service):
        resp = MagicMock()
        resp.read.return_value = b'<html>gateway</html>'
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda self, *a: False
        with patch('urllib.request.urlopen', return_value=resp), patch('time.sleep'):
            with pytest.raises(TransientAIError):
                service._call_api('p', 's', max_retries=1)

    def test_sem_configuracao_e_permanente_sem_detalhes(self):
        s = AIService()
        s.api_key = ''
        with pytest.raises(PermanentAIError) as exc_info:
            s._call_api('p', 's')
        assert '.env' not in str(exc_info.value)

    def test_registra_usage_de_tokens(self, service, caplog):
        usage = {'prompt_tokens': 11, 'completion_tokens': 22, 'total_tokens': 33}
        with patch('urllib.request.urlopen', return_value=_ok_response({'ok': 1}, usage)), \
             caplog.at_level(logging.INFO, logger='nutrition'):
            service._call_api('p', 's')
        assert any('33' in r.getMessage() and 'token' in r.getMessage().lower() for r in caplog.records)


# ─────────────────────────────────────────────────────────────────────────────
#  generate_diet / regenerate_meal — exceções tipadas propagam
# ─────────────────────────────────────────────────────────────────────────────

_PLAN = {
    'goal_description': 'Manutenção',
    'meals': [
        {'name': 'Café da manhã', 'time_suggestion': '07:00', 'foods': [
            {'name': 'Ovo cozido', 'quantity_text': '2 ovos', 'quantity_g': 100},
            {'name': 'Pão integral', 'quantity_text': '2 fatias', 'quantity_g': 50},
            {'name': 'Banana', 'quantity_text': '1 unidade', 'quantity_g': 100},
        ]},
        {'name': 'Almoço', 'time_suggestion': '12:00', 'foods': [
            {'name': 'Arroz branco cozido', 'quantity_text': '4 col', 'quantity_g': 200},
            {'name': 'Feijão carioca cozido', 'quantity_text': '1 concha', 'quantity_g': 150},
            {'name': 'Frango grelhado', 'quantity_text': '1 filé', 'quantity_g': 180},
            {'name': 'Azeite de oliva', 'quantity_text': '1 col', 'quantity_g': 10},
        ]},
        {'name': 'Jantar', 'time_suggestion': '19:00', 'foods': [
            {'name': 'Batata doce cozida', 'quantity_text': '1 unid', 'quantity_g': 250},
            {'name': 'Tilápia grelhada', 'quantity_text': '1 filé', 'quantity_g': 180},
            {'name': 'Brócolis cozido', 'quantity_text': '1 xícara', 'quantity_g': 100},
            {'name': 'Azeite de oliva', 'quantity_text': '1 col', 'quantity_g': 10},
        ]},
    ],
}


@pytest.mark.django_db
class TestGenerateDietPropagaErros:

    def test_5xx_vira_transient(self, service, anamnese):
        with patch('urllib.request.urlopen', side_effect=_http_error(503)), patch('time.sleep'):
            with pytest.raises(TransientAIError):
                service.generate_diet(anamnese)

    def test_4xx_vira_permanent(self, service, anamnese):
        with patch('urllib.request.urlopen', side_effect=_http_error(401)), patch('time.sleep'):
            with pytest.raises(PermanentAIError):
                service.generate_diet(anamnese)

    def test_quantity_g_lixo_vira_transient(self, service, anamnese):
        plan = json.loads(json.dumps(_PLAN))
        plan['meals'][0]['foods'][0]['quantity_g'] = 'um pouco'
        with patch('urllib.request.urlopen', return_value=_ok_response(plan)), patch('time.sleep'):
            with pytest.raises(TransientAIError):
                service.generate_diet(anamnese)

    def test_estrutura_invalida_vira_transient(self, service, anamnese):
        plan = {'meals': [{'name': 'Almoço', 'foods': 'arroz e feijão'}]}
        with patch('urllib.request.urlopen', return_value=_ok_response(plan)), patch('time.sleep'):
            with pytest.raises(TransientAIError):
                service.generate_diet(anamnese)

    def test_quantity_g_com_unidade_e_aceito(self, service, anamnese):
        plan = json.loads(json.dumps(_PLAN))
        plan['meals'][1]['foods'][2]['quantity_g'] = '180g'
        with patch('urllib.request.urlopen', return_value=_ok_response(plan)), patch('time.sleep'):
            diet_plan = service.generate_diet(anamnese)
        assert isinstance(diet_plan, DietPlan)
        frango = diet_plan.raw_response['meals'][1]['foods'][2]
        assert isinstance(frango['quantity_g'], int) and frango['quantity_g'] > 0

    def test_regenerate_meal_5xx_vira_transient(self, service, anamnese):
        with patch('urllib.request.urlopen', return_value=_ok_response(_PLAN)), patch('time.sleep'):
            diet_plan = service.generate_diet(anamnese)
        with patch('urllib.request.urlopen', side_effect=_http_error(500)), patch('time.sleep'):
            with pytest.raises(TransientAIError):
                service.regenerate_meal(diet_plan, 0)


# ─────────────────────────────────────────────────────────────────────────────
#  Valores absurdos do LLM — clamp e lacunas
# ─────────────────────────────────────────────────────────────────────────────

class TestQuantityClamp:

    def _enrich(self, service, qty):
        data = {'meals': [{'name': 'Almoço', 'foods': [{'name': 'Arroz branco cozido', 'quantity_g': qty}]}]}
        data, stats = service._enrich_foods_with_macros(data)
        return data['meals'][0]['foods'][0], stats

    def test_quantidade_enorme_limitada_a_1000g(self, service):
        food, _ = self._enrich(service, 5000)
        assert food['quantity_g'] == 1000

    def test_quantidade_minuscula_sobe_para_5g(self, service):
        food, _ = self._enrich(service, 1)
        assert food['quantity_g'] == 5

    @pytest.mark.parametrize('qty', [-100, 0, None, float('nan')])
    def test_quantidade_invalida_conta_como_lacuna(self, service, qty):
        food, stats = self._enrich(service, qty)
        assert stats['invalid'] == 1
        assert food['calories'] >= 0
        assert food['protein_g'] >= 0

    def test_invalid_conta_na_cobertura(self, service):
        anamnese = MagicMock(user_id=1)
        stats = {'total': 5, 'exact': 3, 'generic': 1, 'invalid': 1, 'generic_names': ['X']}
        with pytest.raises(NutritionDataGap):
            service._check_db_coverage(stats, anamnese)

    def test_lookup_negativo_nunca_gera_kcal_negativa(self):
        r = lookup_food_nutrition('Arroz branco', -50)
        assert r['calories'] == 0 and r['_source'] == 'invalid'
        r = lookup_food_nutrition('', 100)
        assert r['calories'] >= 0


# ─────────────────────────────────────────────────────────────────────────────
#  nutrition_db — matching seguro
# ─────────────────────────────────────────────────────────────────────────────

_GAP_SOURCES = {'generic', 'fuzzy_weak', 'invalid'}


class TestNutritionDbMatching:

    @pytest.mark.parametrize('name', ['Batata frita', 'Doce de leite', 'Leite de coco',
                                      'Suco de laranja de caixinha com açúcar'])
    def test_preparos_nao_casam_com_alimento_base(self, name):
        r = lookup_food_nutrition(name, 100)
        assert r['_source'] in _GAP_SOURCES, (name, r)

    def test_batata_frita_nao_herda_kcal_da_batata_cozida(self):
        frita = lookup_food_nutrition('Batata frita', 100)['calories']
        assert frita != lookup_food_nutrition('Batata', 100)['calories']

    @pytest.mark.parametrize('name', ['Tilápia assada', 'Frango grelhado com ervas', 'Arroz branco',
                                      'Peito de frango desfiado', 'Banana prata madura', 'Ovos mexidos'])
    def test_variacoes_comuns_tem_bom_match(self, name):
        assert lookup_food_nutrition(name, 100)['_source'] in {'exact', 'fuzzy'}, name

    def test_fuzzy_fraco_conta_como_lacuna(self):
        # "Wrap de frango" casa só metade das palavras de "frango"
        assert lookup_food_nutrition('Wrap de frango', 100)['_source'] in _GAP_SOURCES

    def test_palavra_principal_obrigatoria(self):
        # Casar apenas a palavra secundária ("grelhado") não é match válido:
        # antes, "Hambúrguer grelhado" herdava os macros de "frango grelhado"
        r = lookup_food_nutrition('Hambúrguer grelhado', 100)
        assert r['_source'] in _GAP_SOURCES

    def test_fuzzy_weak_conta_na_cobertura(self, service):
        data = {'meals': [{'name': 'Almoço', 'foods': [
            {'name': 'Wrap de frango', 'quantity_g': 100},
            {'name': 'Doce de leite', 'quantity_g': 30},
            {'name': 'Arroz branco cozido', 'quantity_g': 100},
        ]}]}
        _, stats = service._enrich_foods_with_macros(data)
        with pytest.raises(NutritionDataGap):
            service._check_db_coverage(stats, MagicMock(user_id=1))


# ─────────────────────────────────────────────────────────────────────────────
#  Logs e configuração
# ─────────────────────────────────────────────────────────────────────────────

class TestLogsEConfig:

    def test_ai_model_lido_de_settings(self, settings):
        settings.AI_MODEL = 'modelo-de-teste'
        assert AIService().model == 'modelo-de-teste'

    def test_parse_response_nao_loga_conteudo(self, service, caplog):
        secret_content = 'CONTEUDO-SENSIVEL-DO-USUARIO {'
        with caplog.at_level(logging.DEBUG, logger='nutrition'):
            with pytest.raises(TransientAIError):
                service._parse_response({'choices': [{'message': {'content': secret_content}}]})
            with pytest.raises(TransientAIError):
                service._parse_response({'unexpected': secret_content})
        assert secret_content not in caplog.text
        assert 'CONTEUDO-SENSIVEL' not in caplog.text
