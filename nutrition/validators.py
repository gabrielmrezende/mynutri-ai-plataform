"""
Validações determinísticas do plano gerado pelo LLM: estrutura mínima do
JSON e proporções de macronutrientes.
"""

from .errors import TransientAIError
from .prompts import calculate_macros


def _validate_plan_structure(diet_data, *, single_meal: bool = False) -> None:
    """
    Valida a estrutura mínima do JSON do LLM antes do processamento
    determinístico. Estrutura inválida → TransientAIError (retry).
    """
    meals = [diet_data] if single_meal else (diet_data or {}).get('meals') if isinstance(diet_data, dict) else None
    if not isinstance(meals, list) or not meals:
        raise TransientAIError('A IA não retornou refeições válidas. Tente novamente.')
    for meal in meals:
        if not isinstance(meal, dict):
            raise TransientAIError('A IA retornou refeições em formato inválido. Tente novamente.')
        foods = meal.get('foods')
        if not isinstance(foods, list) or not foods:
            raise TransientAIError('A IA retornou refeições sem alimentos válidos. Tente novamente.')
        for food in foods:
            if not isinstance(food, dict) or not isinstance(food.get('name'), str) or not food['name'].strip():
                raise TransientAIError('A IA retornou alimentos em formato inválido. Tente novamente.')
            if 'quantity_text' in food and not isinstance(food['quantity_text'], str):
                food['quantity_text'] = str(food['quantity_text'])


# Limites usados por macro_ratio_violations
MACRO_CARBS_MAX_PCT       = 0.65
MACRO_PROTEIN_MIN_PCT     = 0.15
MACRO_FAT_MIN_PCT         = 0.15
MACRO_FAT_MAX_PER_KG      = 1.2
MACRO_FAT_TARGET_TOLERANCE = 1.3
MACRO_PROTEIN_MIN_RATIO   = 0.65


def macro_ratio_violations(
    diet_data: dict,
    anamnese,
    target_calories: int,
) -> list[str]:
    """
    Retorna a lista de violações de proporção de macros (vazia se ok).

    Limites absolutos por % de calorias:
      - Carboidratos: máximo 65% das calorias
      - Proteína:     mínimo 15% das calorias
      - Gordura:      mínimo 15% das calorias

    Teto de gordura: o maior entre 1.2g/kg de peso corporal e 130% da meta
    de gordura calculada pelo backend (a meta pode passar de 1.2g/kg em
    pessoas leves com gasto alto, quando o carboidrato é limitado a 60%).

    Aderência à meta calculada:
      - Proteína: mínimo 65% da meta calculada pelo backend
    """
    macros    = diet_data.get('macros', {})
    total_cal = diet_data.get('calories', 0)
    if not total_cal:
        return []

    protein_g = macros.get('protein_g', 0)
    carbs_g   = macros.get('carbs_g', 0)
    fat_g     = macros.get('fat_g', 0)
    w         = float(anamnese.weight_kg) if anamnese.weight_kg else 1.0

    protein_pct = (protein_g * 4) / total_cal
    carbs_pct   = (carbs_g   * 4) / total_cal
    fat_pct     = (fat_g     * 9) / total_cal
    fat_per_kg  = fat_g / w

    targets = calculate_macros(anamnese, target_calories)
    fat_ceiling_g = max(
        MACRO_FAT_MAX_PER_KG * w,
        MACRO_FAT_TARGET_TOLERANCE * targets['fat_g'],
    )

    violations = []

    if carbs_pct > MACRO_CARBS_MAX_PCT:
        violations.append(
            f'carboidratos em {carbs_pct * 100:.0f}% das calorias (teto: 65%) — '
            f'excesso de alimentos ricos em amido/açúcar'
        )
    if protein_pct < MACRO_PROTEIN_MIN_PCT:
        violations.append(
            f'proteína em {protein_pct * 100:.0f}% das calorias (mínimo: 15%) — '
            f'fontes proteicas insuficientes no plano'
        )
    if fat_pct < MACRO_FAT_MIN_PCT:
        violations.append(
            f'gordura em {fat_pct * 100:.0f}% das calorias (mínimo: 15%) — '
            f'risco de deficiência de vitaminas lipossolúveis'
        )
    # Teto de gordura — detecta excesso de óleos/castanhas mesmo em %
    # aceitável (ex: 37% numa dieta de 3000 kcal parece ok em %, mas 126g para
    # 95kg = 1.33g/kg excede claramente o limite fisiológico de 1.0g/kg)
    if fat_g > fat_ceiling_g:
        violations.append(
            f'gordura {fat_g}g ({fat_per_kg:.1f}g/kg) excede o teto de '
            f'{fat_ceiling_g:.0f}g para {w:.0f}kg — desbalanceamento por excesso '
            f'de alimentos gordurosos (óleos, castanhas, queijo, manteiga)'
        )

    # Aderência à meta de proteína calculada
    protein_target = targets['protein_g']
    if protein_target > 0:
        protein_ratio = protein_g / protein_target
        if protein_ratio < MACRO_PROTEIN_MIN_RATIO:
            violations.append(
                f'proteína {protein_g}g é apenas {protein_ratio * 100:.0f}% da meta '
                f'({protein_target}g) — desbalanceamento de macros proteicos'
            )
    return violations
