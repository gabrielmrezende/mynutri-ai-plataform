"""
Constantes determinísticas usadas no cálculo calórico e de macros.
Nenhum LLM acessa este módulo — é usado exclusivamente pelo backend.
"""

# ─── Proteína (g/kg de peso corporal, por objetivo) ──────────────────────────
PROTEIN_PER_KG: dict[str, float] = {
    'lose':     2.0,   # alto para preservar massa magra no déficit
    'maintain': 1.6,
    'gain':     2.0,   # alto para síntese proteica
}

PROTEIN_MIN_PER_KG = 1.6   # mínimo para preservação de massa magra
PROTEIN_MAX_PER_KG = 2.2   # acima não traz benefício adicional

# ─── Gordura (g/kg de peso corporal, por objetivo) ───────────────────────────
FAT_PER_KG: dict[str, float] = {
    'lose':     0.8,   # moderado — preserva função hormonal no déficit
    'maintain': 0.8,
    'gain':     0.7,   # menor gordura = mais kcal restam para carboidratos
}

FAT_MIN_PER_KG = 0.6   # mínimo para produção hormonal e vitaminas lipossolúveis
FAT_MAX_PER_KG = 1.0   # acima não há benefício metabólico documentado

# ─── Fatores de atividade (Harris-Benedict / Mifflin-St Jeor) ────────────────
ACTIVITY_FACTORS: dict[str, float] = {
    'sedentary': 1.2,
    'light':     1.375,
    'moderate':  1.55,
    'intense':   1.725,
    'athlete':   1.9,
}

# ─── Ajustes calóricos por objetivo ──────────────────────────────────────────
# Déficit percentual do GET (gasto energético total): 20%, limitado a 750 kcal
# — mas nunca abaixo de 15% do GET (o teto absoluto só reduz até 15%).
DEFICIT_PCT       = 0.20
DEFICIT_MIN_PCT   = 0.15
DEFICIT_MAX_KCAL  = 750

# Superávit percentual do GET: 10%, entre 200 e 500 kcal.
SURPLUS_PCT       = 0.10
SURPLUS_MIN_KCAL  = 200
SURPLUS_MAX_KCAL  = 500

# ─── Calorias mínimas por sexo ────────────────────────────────────────────────
MIN_CALORIES: dict[str, int] = {
    'M': 1500,
    'F': 1200,
    'O': 1350,
}

# ─── Teto absoluto da meta calórica (kcal/dia) ───────────────────────────────
# Acima disso o plano automático deixa de ser razoável (porções enormes).
MAX_CALORIES = 4500

# ─── Peso de referência para obesidade ───────────────────────────────────────
# Com IMC > 30, metas por kg usam o peso ajustado:
#   ideal (IMC 25) + 25% do excesso — evita metas de proteína/gordura absurdas.
ADJUSTED_WEIGHT_BMI_THRESHOLD = 30.0
ADJUSTED_WEIGHT_IDEAL_BMI     = 25.0
ADJUSTED_WEIGHT_EXCESS_FACTOR = 0.25

# ─── Faixas de macros por % das calorias ─────────────────────────────────────
# Mantidas com folga em relação a services._validate_macro_ratios
# (carbo ≤ 65%, proteína ≥ 15%, gordura ≥ 15%) para que a meta calculada
# sempre seja aprovada pelo validador.
CARBS_MAX_PCT   = 0.60
PROTEIN_MIN_PCT = 0.16
PROTEIN_MAX_PCT = 0.40
FAT_MIN_PCT     = 0.20
FAT_MAX_PCT     = 0.35

# ─── Distribuição calórica por número de refeições ───────────────────────────
# Cada entrada: lista de (nome_da_refeição, fração_do_total_diário).
MEAL_PLANS: dict[int, list[tuple[str, float]]] = {
    1: [('Refeição principal', 1.00)],
    2: [('Café da manhã', 0.45), ('Jantar', 0.55)],
    3: [('Café da manhã', 0.25), ('Almoço', 0.40), ('Jantar', 0.35)],
    4: [('Café da manhã', 0.25), ('Almoço', 0.35), ('Lanche', 0.10), ('Jantar', 0.30)],
    5: [('Café da manhã', 0.20), ('Almoço', 0.30), ('Lanche da manhã', 0.10),
        ('Lanche da tarde', 0.10), ('Jantar', 0.30)],
    6: [('Café da manhã', 0.20), ('Almoço', 0.25), ('Lanche da manhã', 0.10),
        ('Lanche da tarde', 0.10), ('Jantar', 0.25), ('Ceia', 0.10)],
}
