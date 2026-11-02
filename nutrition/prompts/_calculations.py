"""
Cálculos determinísticos de calorias, macros e distribuição de refeições.
Executados 100% no backend — nenhum LLM faz aritmética nutricional.
"""

import math

from ._constants import (
    ACTIVITY_FACTORS,
    ADJUSTED_WEIGHT_BMI_THRESHOLD,
    ADJUSTED_WEIGHT_EXCESS_FACTOR,
    ADJUSTED_WEIGHT_IDEAL_BMI,
    CARBS_MAX_PCT,
    DEFICIT_MAX_KCAL,
    DEFICIT_MIN_PCT,
    DEFICIT_PCT,
    FAT_MAX_PCT,
    FAT_MAX_PER_KG,
    FAT_MIN_PCT,
    FAT_MIN_PER_KG,
    FAT_PER_KG,
    MAX_CALORIES,
    MEAL_PLANS,
    MIN_CALORIES,
    PROTEIN_MAX_PCT,
    PROTEIN_MAX_PER_KG,
    PROTEIN_MIN_PCT,
    PROTEIN_MIN_PER_KG,
    PROTEIN_PER_KG,
    SURPLUS_MAX_KCAL,
    SURPLUS_MIN_KCAL,
    SURPLUS_PCT,
)


def _tmb(anamnese) -> float:
    """Taxa metabólica basal via Mifflin-St Jeor."""
    w = float(anamnese.weight_kg)
    h = float(anamnese.height_cm)
    a = int(anamnese.age)

    if anamnese.gender == 'M':
        return (10 * w) + (6.25 * h) - (5 * a) + 5
    if anamnese.gender == 'F':
        return (10 * w) + (6.25 * h) - (5 * a) - 161
    return (10 * w) + (6.25 * h) - (5 * a) - 78


def calculate_energy_plan(anamnese) -> dict:
    """
    Calcula TMB, GET (TDEE) e meta calórica com regras de segurança.

    Regras:
      - Emagrecimento: déficit de 20% do GET, limitado a 750 kcal (mas nunca
        abaixo de 15% do GET).
      - Ganho: superávit de 10% do GET, entre 200 e 500 kcal.
      - Piso mínimo por sexo. Se o piso for ≥ GET, NÃO há déficit possível:
        a meta vira manutenção (meta = GET) e o plano é sinalizado.
        Se o piso só reduz o déficit, a meta fica no piso e é sinalizada.
      - Teto absoluto de MAX_CALORIES kcal (sinalizado quando aplicado).

    Retorna dict com:
      tmb, tdee, target_calories (int), goal, effective_goal,
      adjustment_kcal (int, com sinal), adjustment_label (str),
      warnings (list[str] — mensagens em português para o usuário).
    """
    tmb = _tmb(anamnese)
    factor = ACTIVITY_FACTORS.get(anamnese.activity_level, 1.375)
    tdee = tmb * factor
    goal = anamnese.goal
    min_cal = MIN_CALORIES.get(anamnese.gender, 1350)
    warnings: list[str] = []
    effective_goal = goal

    if goal == 'lose':
        deficit = min(tdee * DEFICIT_PCT, max(DEFICIT_MAX_KCAL, tdee * DEFICIT_MIN_PCT))
        target = tdee - deficit
        if min_cal >= tdee:
            # Piso mínimo ≥ gasto total: qualquer "déficit" seria abaixo do piso
            target = tdee
            effective_goal = 'maintain'
            warnings.append(
                'Seu gasto energético estimado já está no limite mínimo seguro de calorias; '
                'o plano foi calculado para manutenção de peso. Procure um nutricionista '
                'para orientar o emagrecimento.'
            )
        elif target < min_cal:
            target = min_cal
            warnings.append(
                f'O déficit calórico foi reduzido para respeitar o mínimo seguro de '
                f'{min_cal} kcal/dia.'
            )
    elif goal == 'gain':
        surplus = max(SURPLUS_MIN_KCAL, min(SURPLUS_MAX_KCAL, tdee * SURPLUS_PCT))
        target = tdee + surplus
    else:
        target = tdee

    target = max(target, min_cal)

    if target > MAX_CALORIES:
        target = MAX_CALORIES
        warnings.append(
            f'A meta calórica foi limitada a {MAX_CALORIES} kcal/dia. Necessidades acima '
            'disso devem ser acompanhadas por um nutricionista.'
        )

    tmb_i, tdee_i, target_i = round(tmb), round(tdee), round(target)
    adjustment = target_i - tdee_i

    if adjustment < 0:
        pct = round(-adjustment / tdee_i * 100) if tdee_i else 0
        label = f'Déficit de {-adjustment} kcal ({pct}% do gasto total — emagrecimento)'
    elif adjustment > 0 and effective_goal == 'gain':
        pct = round(adjustment / tdee_i * 100) if tdee_i else 0
        label = f'Superávit de {adjustment} kcal ({pct}% do gasto total — ganho de massa)'
    elif adjustment > 0:
        label = f'Acréscimo de {adjustment} kcal para atingir o mínimo seguro'
    else:
        label = 'Sem ajuste (manutenção)'

    return {
        'tmb':              tmb_i,
        'tdee':             tdee_i,
        'target_calories':  target_i,
        'goal':             goal,
        'effective_goal':   effective_goal,
        'adjustment_kcal':  adjustment,
        'adjustment_label': label,
        'warnings':         warnings,
    }


def calculate_calories(anamnese) -> tuple[int, int, int]:
    """
    Calcula TMB, TDEE e meta calórica via Mifflin-St Jeor.
    Retorna (tmb, tdee, target_calories) — todos inteiros arredondados.
    Ver calculate_energy_plan para as regras de déficit/superávit.
    """
    plan = calculate_energy_plan(anamnese)
    return plan['tmb'], plan['tdee'], plan['target_calories']


def reference_weight(anamnese) -> float:
    """
    Peso usado nas metas por kg. Com IMC > 30 usa o peso ajustado
    (peso ideal no IMC 25 + 25% do excesso) — metas por kg de peso real
    superestimam proteína e gordura em pessoas com obesidade.
    """
    w = float(anamnese.weight_kg)
    try:
        h_m = float(anamnese.height_cm) / 100
    except (TypeError, ValueError):
        return w
    if h_m <= 0:
        return w
    bmi = w / (h_m ** 2)
    if bmi <= ADJUSTED_WEIGHT_BMI_THRESHOLD:
        return w
    ideal = ADJUSTED_WEIGHT_IDEAL_BMI * h_m ** 2
    return ideal + ADJUSTED_WEIGHT_EXCESS_FACTOR * (w - ideal)


def calculate_macros(anamnese, target_calories: int) -> dict:
    """
    Calcula metas de macronutrientes:

      Passo 1 — Proteína: baseada em g/kg (preservar/construir massa magra)
      Passo 2 — Gordura:  baseada em g/kg (suporte hormonal, vitaminas lipossolúveis)
      Passo 3 — Carboidrato: restante das calorias, com teto de 60%
      Passo 4 — Se o carboidrato passar de 60%, o excedente é realocado para
                gordura (até 35%) e depois proteína (até 40%)

    O peso por kg é o peso de referência (ajustado quando IMC > 30).

    Faixas de segurança (por % das calorias), compatíveis com o validador
    services._validate_macro_ratios — a meta calculada sempre é aprovada:
      Proteína: 1.6–2.2g/kg, mínimo 16% e máximo 40% das calorias
      Gordura:  0.6–1.0g/kg, mínimo 20% e máximo 35% das calorias
      Carb:     restante, máximo 60% das calorias
    """
    w = reference_weight(anamnese)
    t = float(target_calories)

    # ── Passo 1: Proteína ────────────────────────────────────────────────────
    protein_per_kg = PROTEIN_PER_KG.get(anamnese.goal, 1.6)
    protein_g = round(w * protein_per_kg)
    protein_g = max(round(w * PROTEIN_MIN_PER_KG),
                    min(protein_g, round(w * PROTEIN_MAX_PER_KG)))
    protein_g = min(protein_g, math.floor(t * PROTEIN_MAX_PCT / 4))
    protein_g = max(protein_g, math.ceil(t * PROTEIN_MIN_PCT / 4))

    # ── Passo 2: Gordura ─────────────────────────────────────────────────────
    fat_per_kg = FAT_PER_KG.get(anamnese.goal, 0.8)
    fat_g = round(w * fat_per_kg)
    fat_g = max(round(w * FAT_MIN_PER_KG),
                min(fat_g, round(w * FAT_MAX_PER_KG)))
    fat_g = min(fat_g, math.floor(t * FAT_MAX_PCT / 9))
    fat_g = max(fat_g, math.ceil(t * FAT_MIN_PCT / 9))

    # ── Passo 3: Carboidrato = restante, com teto ────────────────────────────
    carbs_kcal = t - protein_g * 4 - fat_g * 9
    carbs_cap = t * CARBS_MAX_PCT
    if carbs_kcal > carbs_cap:
        # Passo 4: realoca o excedente para gordura e, se preciso, proteína
        excess = carbs_kcal - carbs_cap
        fat_room = max(0.0, math.floor(t * FAT_MAX_PCT / 9) * 9 - fat_g * 9)
        add_fat_g = math.ceil(min(excess, fat_room) / 9)
        fat_g += add_fat_g
        excess -= add_fat_g * 9
        if excess > 0:
            protein_room = max(0.0, math.floor(t * PROTEIN_MAX_PCT / 4) * 4 - protein_g * 4)
            add_protein_g = math.ceil(min(excess, protein_room) / 4)
            protein_g += add_protein_g
        carbs_kcal = t - protein_g * 4 - fat_g * 9

    carbs_kcal = max(0.0, carbs_kcal)
    carbs_g = math.floor(carbs_kcal / 4)

    protein_kcal = protein_g * 4
    fat_kcal = fat_g * 9
    return {
        'protein_g':      protein_g,
        'protein_pct':    round(protein_kcal / t * 100),
        'protein_per_kg': protein_per_kg,
        'fat_g':          fat_g,
        'fat_per_kg':     fat_per_kg,
        'fat_pct':        round(fat_kcal / t * 100),
        'carbs_g':        carbs_g,
        'carbs_pct':      round(carbs_g * 4 / t * 100),
    }


def build_meal_distribution_hint(meals_per_day: int, target_calories: int) -> str:
    """
    Gera lista de kcal esperada por refeição para incluir no prompt.
    Para >6 refeições distribui uniformemente com nomes genéricos.
    """
    plan = MEAL_PLANS.get(meals_per_day)
    if plan is None:
        frac = 1.0 / meals_per_day
        plan = [(f'Refeição {i + 1}', frac) for i in range(meals_per_day)]

    lines = []
    for name, frac in plan:
        kcal = round(target_calories * frac)
        lines.append(f'  - {name}: ~{kcal} kcal ({round(frac * 100)}%)')
    return '\n'.join(lines)
