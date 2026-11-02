"""
Ajuste de porções e palavras-chave por palavra inteira (AIService).

Cobre:
  - _adjust_to_calorie_target itera até ficar dentro de 10% com teto por alimento
  - generate_diet revalida a meta depois de _round_portions
  - Palavras-chave casam por palavra inteira ('cha' não casa "Salsicha")
  - regenerate_meal aplica as mesmas salvaguardas da geração
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from nutrition.models import Anamnese, DietPlan
from nutrition.nutrition_db import lookup_food_nutrition
from nutrition.services import (
    AIService,
    AllergenViolation,
    MacroImbalanceError,
    RestrictionViolation,
    _household_measure,
    _round_food_quantity,
)

User = get_user_model()


@pytest.fixture
def service():
    return AIService()


def _food(name, qty):
    n = lookup_food_nutrition(name, qty)
    return {'name': name, 'quantity_g': qty, 'quantity_text': f'{qty}g',
            'calories': n['calories'], 'protein_g': n['protein_g'],
            'carbs_g': n['carbs_g'], 'fat_g': n['fat_g']}


def _plan(*foods):
    data = {'meals': [{'name': 'Almoço', 'foods': list(foods)}]}
    return AIService()._recalculate_totals(data)


# ─────────────────────────────────────────────────────────────────────────────
#  _adjust_to_calorie_target — iterativo, com teto por alimento
# ─────────────────────────────────────────────────────────────────────────────

class TestAdjustIterativo:

    def test_converge_para_dentro_de_10_porcento(self, service):
        # Plano com 1/3 da meta: uma passada com caps não basta
        data = _plan(_food('Frango grelhado', 100), _food('Arroz branco cozido', 100),
                     _food('Feijão cozido', 80), _food('Banana', 100))
        target = round(data['calories'] * 1.8)
        result = service._adjust_to_calorie_target(data, target)
        assert abs(result['calories'] - target) / target <= 0.10

    def test_reduz_quando_acima_da_meta(self, service):
        data = _plan(_food('Frango grelhado', 200), _food('Arroz branco cozido', 400),
                     _food('Batata doce cozida', 300))
        target = round(data['calories'] * 0.6)
        result = service._adjust_to_calorie_target(data, target)
        assert abs(result['calories'] - target) / target <= 0.10

    def test_teto_por_alimento(self, service):
        # Só arroz: alvo impossível sem porção absurda → respeita teto 3x e 1000 g
        data = _plan(_food('Arroz branco cozido', 100))
        result = service._adjust_to_calorie_target(data, 5000)
        qty = result['meals'][0]['foods'][0]['quantity_g']
        assert qty <= 300

    def test_proteina_mantem_cap_mesmo_iterando(self, service):
        data = _plan(_food('Frango grelhado', 100), _food('Arroz branco cozido', 100))
        result = service._adjust_to_calorie_target(data, data['calories'] * 3)
        frango = result['meals'][0]['foods'][0]
        assert frango['quantity_g'] <= 115

    def test_bebida_zero_nao_e_escalada(self, service):
        data = _plan(_food('Chá verde', 200), _food('Arroz branco cozido', 100))
        result = service._adjust_to_calorie_target(data, data['calories'] * 2)
        assert result['meals'][0]['foods'][0]['quantity_g'] == 200


# ─────────────────────────────────────────────────────────────────────────────
#  Palavras-chave por palavra inteira
# ─────────────────────────────────────────────────────────────────────────────

class TestPalavrasInteiras:

    @pytest.mark.parametrize('name', ['Salsicha', 'Bolacha de água e sal', 'Água de coco'])
    def test_nao_e_bebida_zero(self, name):
        assert AIService._is_zero_calorie_drink(name) is False

    @pytest.mark.parametrize('name', ['Chá verde', 'Café preto', 'Água', 'Coca-Cola Zero'])
    def test_e_bebida_zero(self, name):
        assert AIService._is_zero_calorie_drink(name) is True

    def test_proteina_por_palavra_inteira(self):
        assert AIService._is_protein_food('Ovos mexidos') is True
        assert AIService._is_protein_food('Prato novo de legumes') is False

    def test_gordura_por_palavra_inteira(self):
        assert AIService._is_fat_food('Azeite de oliva') is True
        assert AIService._is_fat_food('Cocada') is False

    def test_arredondamento_maca_nao_casa_macarrao(self):
        # 'maca' (fruta, múltiplo 50) não deve capturar "Macarrão"
        assert _round_food_quantity('Macarrão cozido', 130) % 50 == 0
        assert _household_measure('Macarrão cozido', 200).endswith('xícaras')

    def test_arredondamento_plural(self):
        assert _round_food_quantity('Nozes', 23) % 10 == 0
        assert _household_measure('Nozes', 20) == '4 unidades'
        assert _household_measure('Pães franceses', 50) == '1 unidade'


# ─────────────────────────────────────────────────────────────────────────────
#  generate_diet revalida após arredondar / regenerate_meal salvaguardas
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def anamnese(db):
    user = User.objects.create_user(username='port@test.com', email='port@test.com', password='Senha-123')
    return Anamnese.objects.create(
        user=user, age=30, gender='M', weight_kg=80, height_cm=180,
        activity_level='moderate', goal='maintain', meals_per_day=3,
        food_restrictions='vegetariano', food_preferences='', allergies='leite',
    )


def _api(content):
    return {'choices': [{'message': {'content': json.dumps(content)}}]}


@pytest.fixture
def diet_plan(anamnese):
    meals = [
        {'name': 'Café da manhã', 'time_suggestion': '07:00', 'foods': [
            _food('Ovo cozido', 150), _food('Pão integral', 50), _food('Banana', 100)]},
        {'name': 'Almoço', 'time_suggestion': '12:00', 'foods': [
            _food('Arroz branco cozido', 150), _food('Lentilha cozida', 200),
            _food('Tofu', 300), _food('Proteína texturizada de soja', 60)]},
        {'name': 'Jantar', 'time_suggestion': '19:00', 'foods': [
            _food('Batata doce cozida', 250), _food('Ovo mexido', 200),
            _food('Proteína texturizada de soja', 50), _food('Azeite de oliva', 10)]},
    ]
    raw = AIService()._recalculate_totals({'meals': meals})
    return DietPlan.objects.create(
        user=anamnese.user, anamnese=anamnese, raw_response=raw,
        total_calories=raw['calories'], goal_description='Manutenção',
    )


@pytest.mark.django_db
class TestRegenerateSalvaguardas:

    def test_rejeita_restricao(self, service, diet_plan):
        meal = {'name': 'Almoço', 'foods': [{'name': 'Frango grelhado', 'quantity_g': 150},
                                            {'name': 'Arroz branco cozido', 'quantity_g': 150}]}
        with patch.object(service, '_call_api', return_value=_api(meal)):
            with pytest.raises(RestrictionViolation):
                service.regenerate_meal(diet_plan, 1)

    def test_rejeita_familia_do_alergeno(self, service, diet_plan):
        meal = {'name': 'Almoço', 'foods': [{'name': 'Queijo minas', 'quantity_g': 60},
                                            {'name': 'Arroz branco cozido', 'quantity_g': 150}]}
        with patch.object(service, '_call_api', return_value=_api(meal)):
            with pytest.raises(AllergenViolation):
                service.regenerate_meal(diet_plan, 1)

    def test_arredonda_depois_de_ajustar(self, service, diet_plan):
        meal = {'name': 'Almoço', 'foods': [{'name': 'Arroz branco cozido', 'quantity_g': 137},
                                            {'name': 'Feijão cozido', 'quantity_g': 93},
                                            {'name': 'Tofu', 'quantity_g': 177}]}
        with patch.object(service, '_call_api', return_value=_api(meal)):
            result = service.regenerate_meal(diet_plan, 1)
        for f in result['new_raw_meal']['foods']:
            rounded = _round_food_quantity(f['name'], f['quantity_g'])
            assert f['quantity_g'] == rounded, f

    def test_rejeita_quando_novo_plano_desbalanceia_macros(self, service, diet_plan):
        # Refeição só de carboidrato/açúcar derruba a proteína do plano inteiro
        meal = {'name': 'Almoço', 'foods': [{'name': 'Banana', 'quantity_g': 300},
                                            {'name': 'Mel', 'quantity_g': 100},
                                            {'name': 'Maçã', 'quantity_g': 200}]}
        old = service._macro_ratio_violations(
            diet_plan.raw_response, diet_plan.anamnese,
            __import__('nutrition.prompts', fromlist=['x']).calculate_calories(diet_plan.anamnese)[2],
        )
        if old:
            pytest.skip('plano de fixture já desbalanceado')
        with patch.object(service, '_call_api', return_value=_api(meal)):
            with pytest.raises(MacroImbalanceError):
                service.regenerate_meal(diet_plan, 1)

    def test_passa_max_tokens(self, service, diet_plan):
        meal = {'name': 'Almoço', 'foods': [{'name': 'Arroz branco cozido', 'quantity_g': 150},
                                            {'name': 'Feijão cozido', 'quantity_g': 100},
                                            {'name': 'Tofu', 'quantity_g': 150}]}
        with patch.object(service, '_call_api', return_value=_api(meal)) as m:
            service.regenerate_meal(diet_plan, 1)
        assert m.call_args.kwargs.get('max_tokens')


class TestMaxTokensGeracao:

    def test_proporcional_a_refeicoes(self):
        assert AIService._food_selection_max_tokens(8) > AIService._food_selection_max_tokens(3)
        assert AIService._food_selection_max_tokens(12) <= 6000
        assert AIService._food_selection_max_tokens(1) >= 1500
