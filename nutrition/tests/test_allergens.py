"""
Testes do motor determinístico de alergias e restrições alimentares
(nutrition/allergens.py) e da sua integração com services e substitutions.

Cobre os casos da auditoria: alérgeno declarado em termo "família"
(leite, glúten, frutos do mar, castanhas...) precisa bloquear os alimentos
derivados (queijo, pão, camarão, castanha-do-pará...).
"""


import pytest

from nutrition.allergens import (
    food_violates_restriction,
    parse_restrictions,
)
from nutrition.services import (
    AIService,
    AllergenViolation,
    RestrictionViolation,
    _food_contains_allergen,
    _parse_allergens,
)
from nutrition.substitutions import generate_meal_substitutions


# ─────────────────────────────────────────────────────────────────────────────
#  Alergias — casos da auditoria
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('allergies_text, food_name', [
    ('leite', 'Queijo minas frescal'),
    ('leite', 'Iogurte natural'),
    ('leite', 'Whey protein'),
    ('leite', 'Requeijão light'),
    ('leite', 'Manteiga'),
    ('lactose', 'Leite integral'),
    ('lactose', 'Queijo mussarela'),
    ('gluten', 'Pão integral'),
    ('glúten', 'Aveia em flocos'),
    ('trigo', 'Macarrão cozido'),
    ('trigo', 'Farinha de trigo'),
    ('ovos', 'Ovo cozido'),
    ('ovo', 'Omelete simples'),
    ('ovo', 'Clara de ovo'),
    ('frutos do mar', 'Camarão grelhado'),
    ('frutos_do_mar', 'Lula grelhada'),
    ('camarao', 'Camarões ao alho'),
    ('camarão', 'Lagosta cozida'),
    ('castanhas', 'Castanha-do-pará'),
    ('nozes', 'Castanha de caju'),
    ('oleaginosas', 'Amêndoas'),
    ('alergia a camarao', 'Camarão cozido'),
    ('Sou alérgico a amendoim', 'Pasta de amendoim'),
    ('intolerância a lactose', 'Iogurte grego'),
    ('peixe', 'Tilápia grelhada'),
    ('peixes', 'Salmão grelhado'),
    ('soja', 'Tofu grelhado'),
    ('soja', 'Leite de soja'),
])
def test_alergeno_familia_bloqueia_derivados(allergies_text, food_name):
    allergens = _parse_allergens(allergies_text)
    assert allergens, f'nenhum alérgeno reconhecido em {allergies_text!r}'
    assert _food_contains_allergen(food_name, allergens) is not None


@pytest.mark.parametrize('allergies_text, food_name', [
    ('leite', 'Leite de coco'),
    ('leite', 'Leite de amêndoas'),
    ('leite', 'Pasta de amendoim'),
    ('lactose', 'Leite sem lactose'),
    ('gluten', 'Tapioca'),
    ('gluten', 'Pão de queijo'),
    ('gluten', 'Farinha de mandioca'),
    ('gluten', 'Aveia sem glúten'),
    ('ovo', 'Prato novo'),
    ('peixe', 'Frango grelhado'),
    ('amendoim', 'Sabor amendoado'),
    ('camarao', 'Tilápia grelhada'),
])
def test_alimentos_seguros_nao_sao_bloqueados(allergies_text, food_name):
    allergens = _parse_allergens(allergies_text)
    assert _food_contains_allergen(food_name, allergens) is None


def test_parse_remove_prefixo_alergia():
    assert _parse_allergens('alergia a camarão') == ['camarao']
    assert _parse_allergens('intolerância a lactose') == ['lactose']


def test_parse_reconhece_valores_dos_checkboxes():
    # Valores dos checkboxes de frontend/public/questionario.html
    r = _parse_allergens('gluten, lactose, ovo, soja, amendoim, frutos_do_mar, nozes, peixe')
    assert r == ['gluten', 'lactose', 'ovo', 'soja', 'amendoim', 'frutos do mar', 'nozes', 'peixe']
    assert _food_contains_allergen('Camarão', r) == 'frutos do mar'
    assert _food_contains_allergen('Pão francês', r) == 'gluten'


# ─────────────────────────────────────────────────────────────────────────────
#  Restrições alimentares (food_restrictions)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('restricoes, food_name', [
    ('vegetariano', 'Peito de frango grelhado'),
    ('vegetariano', 'Atum em água'),
    ('vegetariano', 'Camarão cozido'),
    ('vegetariano', 'Patinho moído'),
    ('vegano', 'Ovo cozido'),
    ('vegano', 'Queijo minas'),
    ('vegano', 'Mel'),
    ('vegano', 'Carne bovina'),
    ('sem lactose', 'Leite desnatado'),
    ('sem glúten', 'Pão francês'),
    ('Não como carne de porco', 'Lombo suíno assado'),
    ('pescetariano', 'Frango grelhado'),
    # Checkboxes de alergia enviados no campo restricoes pelo frontend atual
    ('vegetariano, gluten, lactose', 'Macarrão cozido'),
])
def test_restricao_bloqueia_alimento(restricoes, food_name):
    restrictions = parse_restrictions(restricoes)
    assert food_violates_restriction(food_name, restrictions) is not None


@pytest.mark.parametrize('restricoes, food_name', [
    ('vegetariano', 'Ovo cozido'),
    ('vegetariano', 'Queijo minas'),
    ('vegetariano', 'Tofu grelhado'),
    ('vegano', 'Tofu grelhado'),
    ('vegano', 'Leite de soja'),
    ('sem lactose', 'Leite sem lactose'),
    ('pescetariano', 'Tilápia grelhada'),
    ('low carb', 'Arroz branco'),  # texto não reconhecido não bloqueia nada
    ('', 'Frango grelhado'),
])
def test_restricao_nao_bloqueia_alimento_compativel(restricoes, food_name):
    restrictions = parse_restrictions(restricoes)
    assert food_violates_restriction(food_name, restrictions) is None


# ─────────────────────────────────────────────────────────────────────────────
#  Substituições
# ─────────────────────────────────────────────────────────────────────────────

def _subs_for(food_name, **kwargs):
    meals = [{'name': 'Almoço', 'foods': [{'name': food_name, 'quantity_g': 100}]}]
    result = generate_meal_substitutions(meals, **kwargs)
    return result[0]['alternatives'] if result else []


def test_substituicao_filtra_alergeno_familia():
    alts = _subs_for('Frango grelhado', allergens=_parse_allergens('peixe'))
    assert not any('Tilápia' in a or 'Atum' in a for a in alts)


def test_substituicao_vegetariano_nao_sugere_atum_para_ovo():
    alts = _subs_for('Ovo cozido', restrictions=parse_restrictions('vegetariano'))
    assert not any('Atum' in a or 'frango' in a.lower() for a in alts)


def test_substituicao_vegano_nao_sugere_ovo_para_tofu():
    alts = _subs_for('Tofu grelhado', restrictions=parse_restrictions('vegano'))
    assert alts, 'deveria sobrar alternativa vegetal'
    assert not any('Ovo' in a for a in alts)


def test_substituicao_sem_lactose_nao_sugere_leite_desnatado():
    alts = _subs_for('Leite de soja', restrictions=parse_restrictions('sem lactose'))
    alts += _subs_for('Leite integral', restrictions=parse_restrictions('sem lactose'))
    assert not any('Leite desnatado' in a for a in alts)
    assert not any('Iogurte' in a for a in alts)


# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline — _enforce_allergies / _enforce_restrictions
# ─────────────────────────────────────────────────────────────────────────────

class _FakeAnamnese:
    def __init__(self, allergies='', food_restrictions=''):
        self.allergies = allergies
        self.food_restrictions = food_restrictions
        self.user_id = 1


def _plan(*food_names):
    return {'meals': [{'name': 'Almoço', 'foods': [{'name': n, 'quantity_g': 100} for n in food_names]}]}


def test_enforce_allergies_bloqueia_queijo_para_alergia_a_leite():
    with pytest.raises(AllergenViolation):
        AIService()._enforce_allergies(_plan('Arroz', 'Queijo minas'), _FakeAnamnese(allergies='leite'))


def test_enforce_allergies_aplica_checkbox_enviado_em_restricoes():
    # O frontend atual envia os checkboxes de alergia no campo restricoes
    with pytest.raises(AllergenViolation):
        AIService()._enforce_allergies(_plan('Pão francês'), _FakeAnamnese(food_restrictions='gluten'))


def test_enforce_restrictions_vegetariano_rejeita_frango():
    with pytest.raises(RestrictionViolation):
        AIService()._enforce_restrictions(_plan('Frango grelhado'), _FakeAnamnese(food_restrictions='vegetariano'))


def test_enforce_restrictions_plano_compativel_passa():
    AIService()._enforce_restrictions(
        _plan('Ovo cozido', 'Arroz', 'Feijão'), _FakeAnamnese(food_restrictions='vegetariano'),
    )


def test_restriction_violation_e_retryable():
    from nutrition.services import TransientAIError
    assert issubclass(RestrictionViolation, TransientAIError)
