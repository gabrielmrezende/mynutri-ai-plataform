"""
Sistema de substituições alimentares baseado em regras.

Gera substituições contextuais por refeição — como um nutricionista faria:
- Carboidratos de café da manhã (pão, tapioca, aveia) entre si
- Carboidratos de refeições principais (arroz, batata, macarrão) entre si
- Proteínas equivalentes entre si, com quantidades ajustadas

Quantidades são ajustadas proporcionalmente por densidade energética.
Não repete as mesmas sugestões em todas as refeições.
"""

import unicodedata
import re


def _norm(text: str) -> str:
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text.lower()


# ─────────────────────────────────────────────────────────────────────────────
#  BANCO DE SUBSTITUIÇÕES
#
#  Formato: (keyword, category, [(alt_name, ratio), ...])
#  keyword  : substring normalizada que identifica o alimento
#  category : agrupa alimentos que NÃO devem substituir entre categorias
#  ratio    : alt_quantidade = original_g * ratio  (equivalência calórica)
#
#  Ordem: mais específica primeiro — a primeira regra que casar é usada.
# ─────────────────────────────────────────────────────────────────────────────

_FOOD_RULES: list[tuple[str, str, list[tuple[str, float]]]] = [
    # ── CARBOIDRATOS — CAFÉ DA MANHÃ ──────────────────────────────────────────
    ("torrada integral",  "carbo_cafe", [("Pão integral", 1.1),      ("Tapioca", 1.1),         ("Cuscuz", 1.0)]),
    ("pao integral",      "carbo_cafe", [("Tapioca", 1.0),           ("Cuscuz", 0.9),           ("Aveia em flocos", 0.45)]),
    ("pao de forma",      "carbo_cafe", [("Pão integral", 1.0),      ("Tapioca", 1.0),          ("Cuscuz", 0.9)]),
    ("pao frances",       "carbo_cafe", [("Pão integral", 1.0),      ("Tapioca", 1.0),          ("Cuscuz", 0.9)]),
    ("pao",               "carbo_cafe", [("Tapioca", 1.0),           ("Cuscuz", 0.9),           ("Pão integral", 1.0)]),
    ("tapioca",           "carbo_cafe", [("Pão integral", 1.0),      ("Cuscuz", 1.0),           ("Beiju", 1.0)]),
    ("beiju",             "carbo_cafe", [("Tapioca", 1.0),           ("Pão integral", 1.0)]),
    ("aveia",             "carbo_cafe", [("Granola sem açúcar", 1.0), ("Pão integral", 2.0),    ("Tapioca", 2.0)]),
    ("granola",           "carbo_cafe", [("Aveia em flocos", 1.0),   ("Pão integral", 2.0)]),
    ("cuscuz",            "carbo_cafe", [("Pão integral", 1.1),      ("Tapioca", 1.0),          ("Aveia em flocos", 0.5)]),

    # ── CARBOIDRATOS — REFEIÇÕES PRINCIPAIS ──────────────────────────────────
    ("arroz",             "carbo_almoco", [("Batata inglesa", 1.35), ("Macarrão cozido", 0.75), ("Mandioca cozida", 1.2)]),
    ("batata doce",       "carbo_almoco", [("Arroz cozido", 0.9),    ("Mandioca cozida", 1.05), ("Batata inglesa", 1.1)]),
    ("batata",            "carbo_almoco", [("Arroz cozido", 0.75),   ("Batata doce", 0.9),      ("Mandioca cozida", 1.0)]),
    ("mandioca",          "carbo_almoco", [("Arroz cozido", 0.8),    ("Batata inglesa", 1.0),   ("Batata doce", 0.95)]),
    ("aipim",             "carbo_almoco", [("Arroz cozido", 0.8),    ("Batata inglesa", 1.0),   ("Batata doce", 0.95)]),
    ("macaxeira",         "carbo_almoco", [("Arroz cozido", 0.8),    ("Batata inglesa", 1.0),   ("Batata doce", 0.95)]),
    ("macarrao",          "carbo_almoco", [("Arroz cozido", 1.35),   ("Batata inglesa", 1.6),   ("Mandioca cozida", 1.6)]),
    ("espaguete",         "carbo_almoco", [("Arroz cozido", 1.35),   ("Batata inglesa", 1.6),   ("Macarrão cozido", 1.0)]),
    ("nhoque",            "carbo_almoco", [("Arroz cozido", 1.1),    ("Macarrão cozido", 1.0),  ("Batata inglesa", 1.4)]),

    # ── LEGUMINOSAS ───────────────────────────────────────────────────────────
    ("feijao preto",      "leguminosa", [("Feijão carioca", 1.0),    ("Lentilha cozida", 0.95), ("Grão de bico cozido", 0.95)]),
    ("feijao",            "leguminosa", [("Lentilha cozida", 0.95),  ("Grão de bico cozido", 0.95), ("Ervilha cozida", 1.0)]),
    ("lentilha",          "leguminosa", [("Feijão cozido", 1.05),    ("Grão de bico cozido", 1.0), ("Ervilha cozida", 1.0)]),
    ("grao de bico",      "leguminosa", [("Feijão cozido", 1.05),    ("Lentilha cozida", 1.0),  ("Ervilha cozida", 1.0)]),
    ("ervilha",           "leguminosa", [("Feijão cozido", 1.0),     ("Lentilha cozida", 1.0)]),

    # ── PROTEÍNAS ANIMAIS ─────────────────────────────────────────────────────
    ("peito de frango",   "proteina", [("Tilápia grelhada", 1.05),   ("Patinho grelhado", 1.0),  ("Atum em água", 0.6)]),
    ("file de frango",    "proteina", [("Tilápia grelhada", 1.05),   ("Carne moída magra", 1.0), ("Atum em água", 0.6)]),
    ("frango",            "proteina", [("Tilápia grelhada", 1.05),   ("Carne bovina magra", 1.0), ("Atum em água", 0.6)]),
    ("tilapia",           "proteina", [("Peito de frango grelhado", 1.0), ("Merluza grelhada", 1.0), ("Atum em água", 0.6)]),
    ("salmao",            "proteina", [("Tilápia grelhada", 1.1),    ("Atum em água", 0.65),    ("Sardinha em água", 0.9)]),
    ("merluza",           "proteina", [("Tilápia grelhada", 1.0),    ("Peito de frango grelhado", 0.95), ("Atum em água", 0.6)]),
    ("bacalhau",          "proteina", [("Tilápia grelhada", 1.0),    ("Atum em água", 0.65),    ("Peito de frango grelhado", 1.0)]),
    ("sardinha",          "proteina", [("Atum em água", 1.0),        ("Peito de frango cozido", 1.6)]),
    ("atum",              "proteina", [("Sardinha em água", 1.0),    ("Peito de frango cozido", 1.6), ("Ovo cozido", 1.4)]),
    ("camarao",           "proteina", [("Tilápia grelhada", 1.1),    ("Peito de frango grelhado", 1.0)]),
    ("robalo",            "proteina", [("Tilápia grelhada", 1.0),    ("Salmão grelhado", 0.9)]),
    ("patinho",           "proteina", [("Peito de frango grelhado", 1.0), ("Tilápia grelhada", 1.05), ("Carne moída magra", 1.0)]),
    ("alcatra",           "proteina", [("Patinho grelhado", 1.0),    ("Peito de frango grelhado", 1.0)]),
    ("picanha",           "proteina", [("Alcatra grelhada", 1.05),   ("Patinho grelhado", 1.05)]),
    ("carne moida",       "proteina", [("Peito de frango grelhado", 1.0), ("Patinho grelhado", 1.0)]),
    ("carne bovina",      "proteina", [("Peito de frango grelhado", 1.0), ("Tilápia grelhada", 1.05), ("Ovo cozido", 0.65)]),
    ("carne seca",        "proteina", [("Peito de frango grelhado", 1.1), ("Atum em água", 0.65)]),
    ("linguica",          "proteina", [("Peito de frango grelhado", 1.0), ("Carne moída magra", 1.0)]),
    ("peru",              "proteina", [("Peito de frango grelhado", 1.0), ("Tilápia grelhada", 1.05)]),

    # ── OVOS ─────────────────────────────────────────────────────────────────
    ("clara",             "proteina_ovo", [("Ovo inteiro cozido", 0.65), ("Atum em água", 0.5), ("Peito de frango cozido", 0.55)]),
    ("ovo",               "proteina_ovo", [("Clara de ovo", 1.55),   ("Atum em água", 0.75),    ("Peito de frango cozido", 0.8)]),

    # ── PROTEÍNAS VEGETAIS ────────────────────────────────────────────────────
    ("tofu",              "proteina_vegetal", [("Grão de bico cozido", 1.1), ("Lentilha cozida", 1.0), ("Ovo cozido", 0.85)]),
    ("whey",              "proteina_suplemento", [("Peito de frango cozido", 1.5), ("Atum em água", 1.0), ("Ovo cozido", 1.5)]),

    # ── LATICÍNIOS ────────────────────────────────────────────────────────────
    ("iogurte grego",     "laticinios", [("Cottage", 0.85),          ("Iogurte natural", 1.3),  ("Kefir", 1.3)]),
    ("iogurte",           "laticinios", [("Iogurte grego", 0.75),    ("Cottage", 0.65),         ("Kefir", 1.0)]),
    ("cottage",           "laticinios", [("Iogurte grego", 1.2),     ("Ricota", 0.9),           ("Iogurte natural", 1.5)]),
    ("kefir",             "laticinios", [("Iogurte natural", 1.0),   ("Iogurte grego", 0.75)]),
    ("leite",             "laticinios_liquido", [("Iogurte natural", 0.7), ("Leite de soja", 1.0), ("Leite desnatado", 1.0)]),

    # ── GORDURAS ─────────────────────────────────────────────────────────────
    ("pasta de amendoim", "gordura_pasta", [("Pasta de castanha", 1.0), ("Tahine", 1.0)]),
    ("azeite",            "gordura", [("Óleo de coco", 1.0),         ("Manteiga ghee", 0.9)]),
    ("oleo de coco",      "gordura", [("Azeite", 1.0),               ("Manteiga ghee", 0.9)]),
    ("manteiga",          "gordura", [("Azeite", 1.1),               ("Óleo de coco", 1.0)]),
    ("abacate",           "gordura_fruta", [("Castanha de caju", 0.3), ("Pasta de amendoim", 0.25), ("Amendoim torrado", 0.35)]),
    ("castanha",          "gordura_oleo", [("Amêndoas", 1.0),         ("Nozes", 0.8),            ("Amendoim torrado", 1.2)]),
    ("amendoa",           "gordura_oleo", [("Castanha de caju", 1.0), ("Nozes", 0.8),            ("Amendoim torrado", 1.2)]),
    ("noze",              "gordura_oleo", [("Castanha de caju", 1.2), ("Amêndoas", 1.2),         ("Amendoim torrado", 1.5)]),
    ("amendoim",          "gordura_oleo", [("Castanha de caju", 0.8), ("Amêndoas", 0.8),         ("Nozes", 0.6)]),

    # ── FRUTAS ───────────────────────────────────────────────────────────────
    ("banana",            "fruta", [("Maçã", 1.1),                   ("Pera", 1.1),              ("Manga", 0.9)]),
    ("maca",              "fruta", [("Pera", 1.0),                    ("Laranja", 1.1),           ("Banana", 0.9)]),
    ("laranja",           "fruta", [("Tangerina", 1.1),               ("Maçã", 0.9),              ("Kiwi", 0.85)]),
    ("tangerina",         "fruta", [("Laranja", 0.9),                 ("Maçã", 0.9)]),
    ("mamao",             "fruta", [("Melão", 1.0),                   ("Manga", 0.9),             ("Abacaxi", 1.0)]),
    ("manga",             "fruta", [("Mamão", 1.1),                   ("Abacaxi", 1.1),           ("Banana", 1.1)]),
    ("morango",           "fruta", [("Kiwi", 0.9),                    ("Uva", 0.9),               ("Maçã", 1.2)]),
    ("melancia",          "fruta", [("Melão", 1.0),                   ("Abacaxi", 0.9)]),
    ("abacaxi",           "fruta", [("Melancia", 1.1),                ("Manga", 0.9),             ("Laranja", 0.85)]),
    ("uva",               "fruta", [("Morango", 1.1),                 ("Kiwi", 1.0),              ("Maçã", 1.2)]),
    ("kiwi",              "fruta", [("Morango", 1.1),                 ("Laranja", 1.2),           ("Uva", 1.0)]),
]

# Tipos de refeição por palavras-chave
_CAFE_KEYWORDS   = frozenset(["cafe", "manha", "desjejum"])
_LANCHE_KEYWORDS = frozenset(["lanche"])
_CEIA_KEYWORDS   = frozenset(["ceia"])

# Categorias que não fazem sentido em determinados tipos de refeição
_INCOMPATIBLE: dict[str, set[str]] = {
    "cafe":   {"carbo_almoco"},           # não sugere arroz/batata no café da manhã
    "lanche": {"carbo_almoco"},           # não sugere arroz/batata em lanches
    "almoco": {"carbo_cafe"},             # não sugere pão/tapioca no almoço/jantar
    "jantar": {"carbo_cafe"},
    "ceia":   {"carbo_cafe"},
}


def _classify_meal(meal_name: str) -> str:
    n = _norm(meal_name)
    if any(k in n for k in _CAFE_KEYWORDS):
        return "cafe"
    if any(k in n for k in _LANCHE_KEYWORDS):
        return "lanche"
    if any(k in n for k in _CEIA_KEYWORDS):
        return "ceia"
    return "almoco"


def _find_rule(food_name: str) -> tuple[str, list[tuple[str, float]]] | None:
    """
    Retorna (category, alternatives) para o alimento, ou None se não há regra.
    Usa o match mais longo (mais específico) entre os keywords.
    """
    normalized = _norm(food_name)
    best: tuple[str, list[tuple[str, float]]] | None = None
    best_len = 0
    for keyword, category, alternatives in _FOOD_RULES:
        if keyword in normalized and len(keyword) > best_len:
            best = (category, alternatives)
            best_len = len(keyword)
    return best


def _food_contains_allergen(food_name: str, allergens: list[str]) -> bool:
    """Retorna True se o alimento contém algum alergeno da lista."""
    if not food_name or not allergens:
        return False
    normalized = _norm(food_name)
    for allergen in allergens:
        if ' ' in allergen:
            if allergen in normalized:
                return True
        else:
            if re.search(rf'\b{re.escape(allergen)}\b', normalized):
                return True
    return False


def generate_meal_substitutions(
    meals: list[dict],
    allergens: list[str] | None = None,
) -> list[dict]:
    """
    Gera substituições contextuais para cada alimento relevante do plano.

    Retorna lista de dicts no formato:
        [{"food": "Arroz branco (150g)", "alternatives": ["Batata inglesa (200g)", ...]}]

    Regras aplicadas:
    - Apenas alimentos com substituições no banco de regras recebem sugestões
    - Substituições são filtradas por tipo de refeição (não sugere arroz no café)
    - Alternativas que violam alergias são omitidas
    - Cada alimento aparece no máximo uma vez (sem duplicatas entre refeições)
    """
    if allergens is None:
        allergens = []

    result: list[dict] = []
    seen_foods: set[str] = set()

    for meal in meals:
        meal_name = meal.get("name", "")
        meal_type = _classify_meal(meal_name)
        blocked_categories = _INCOMPATIBLE.get(meal_type, set())

        for food in meal.get("foods", []):
            food_name = (food.get("name") or "").strip()
            if not food_name:
                continue

            norm_name = _norm(food_name)
            if norm_name in seen_foods:
                continue

            rule = _find_rule(food_name)
            if not rule:
                continue

            category, alternatives = rule
            if category in blocked_categories:
                continue

            qty_g = int(food.get("quantity_g") or 100)

            alt_strs: list[str] = []
            for alt_name, ratio in alternatives:
                if allergens and _food_contains_allergen(alt_name, allergens):
                    continue
                alt_qty = max(10, round(qty_g * ratio))
                alt_strs.append(f"{alt_name} ({alt_qty}g)")

            if not alt_strs:
                continue

            result.append({
                "food": f"{food_name} ({qty_g}g)",
                "alternatives": alt_strs,
            })
            seen_foods.add(norm_name)

    return result
