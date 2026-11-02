"""
Motor determinístico de alergias e restrições alimentares.

O LLM recebe as alergias/restrições no prompt, mas pode ignorá-las. Este
módulo é a última linha de defesa: verifica cada alimento do plano (e cada
alternativa de substituição) contra as declarações do usuário.

Um alérgeno declarado é expandido para a FAMÍLIA de alimentos que o contém:
"leite" bloqueia queijo, iogurte, whey, requeijão, manteiga...; "glúten"
bloqueia pão, macarrão, aveia comum, biscoito... O mesmo vale para restrições
de dieta: "vegetariano" bloqueia carnes, aves, peixes e frutos do mar.

Todo matching é por palavra inteira sobre texto canônico (ver textnorm.py).
"""

import re

from .textnorm import any_phrase, canonical, contains_phrase, normalize_text

# ─────────────────────────────────────────────────────────────────────────────
#  FAMÍLIAS DE ALIMENTOS
#
#  Formato: nome_da_familia → {
#      'terms':   alimentos que pertencem à família (bloqueados),
#      'exclude': expressões removidas antes do matching — produtos que
#                 contêm a palavra da família mas não o alérgeno
#                 (ex: "leite de coco" não é laticínio),
#      'safe':    marcadores que tornam o alimento inteiro seguro
#                 (ex: "sem lactose", "sem glúten").
#  }
# ─────────────────────────────────────────────────────────────────────────────

_VEGETABLE_MILKS = (
    'leite de coco', 'leite de soja', 'leite de amendoa', 'leite de aveia',
    'leite de arroz', 'leite de castanha', 'leite vegetal', 'bebida vegetal',
    'iogurte de soja', 'iogurte de coco', 'iogurte vegetal', 'queijo vegano',
    'queijo vegetal', 'manteiga de amendoim', 'manteiga de cacau',
    'creme de leite de coco',
)

_DAIRY_TERMS = (
    'leite', 'queijo', 'iogurte', 'whey', 'requeijao', 'manteiga', 'nata',
    'creme de leite', 'coalhada', 'ricota', 'cottage', 'kefir', 'ghee',
    'doce de leite', 'leite condensado', 'chantilly', 'caseina',
    'proteina do soro', 'soro de leite', 'mussarela', 'muçarela', 'parmesao',
    'provolone', 'catupiry', 'cream cheese', 'sorvete', 'lactose', 'laticinio',
)

_RED_MEAT_TERMS = (
    'carne', 'bovina', 'bovino', 'boi', 'vaca', 'vitela', 'patinho', 'alcatra',
    'picanha', 'file mignon', 'contrafile', 'musculo', 'acem', 'lagarto',
    'cupim', 'costela', 'maminha', 'fraldinha', 'coxao', 'carne moida',
    'carne seca', 'charque', 'hamburguer', 'almondega', 'figado', 'cordeiro',
    'carneiro', 'cabrito',
)

_PORK_TERMS = (
    'porco', 'suino', 'lombo', 'pernil', 'bacon', 'toucinho', 'banha',
    'linguica', 'presunto', 'salame', 'mortadela', 'paio', 'calabresa',
    'torresmo', 'copa',
)

_POULTRY_TERMS = (
    'frango', 'galinha', 'peru', 'peito de peru', 'chester', 'pato',
    'sobrecoxa', 'coxa', 'codorna', 'salsicha', 'caldo de galinha',
)

_FISH_TERMS = (
    'peixe', 'pescado', 'tilapia', 'salmao', 'atum', 'sardinha', 'merluza',
    'bacalhau', 'robalo', 'pescada', 'truta', 'dourado', 'pintado', 'linguado',
    'anchova', 'cavala', 'tambaqui', 'pacu', 'badejo', 'namorado', 'cacao',
    'surubim', 'arenque', 'pirarucu',
)

_CRUSTACEAN_TERMS = (
    'camarao', 'lagosta', 'caranguejo', 'siri', 'lagostim', 'krill',
    'fruto do mar',
)

_MOLLUSC_TERMS = (
    'lula', 'polvo', 'mexilhao', 'marisco', 'ostra', 'vieira', 'sururu',
    'berbigao', 'molusco', 'fruto do mar',
)

_FAMILIES: dict[str, dict[str, tuple[str, ...]]] = {
    'leite': {
        'terms':   _DAIRY_TERMS,
        'exclude': _VEGETABLE_MILKS,
    },
    'lactose': {
        'terms':   _DAIRY_TERMS,
        'exclude': _VEGETABLE_MILKS,
        'safe':    ('sem lactose', 'zero lactose', 'deslactosado', 'lactose free'),
    },
    'gluten': {
        'terms': (
            'gluten', 'trigo', 'pao', 'torrada', 'macarrao', 'massa', 'esparguete',
            'espaguete', 'penne', 'lasanha', 'nhoque', 'aveia', 'biscoito',
            'bolacha', 'farinha', 'cevada', 'centeio', 'malte', 'granola',
            'cereal matinal', 'cuscuz marroquino', 'bulgur', 'triguilho', 'quibe',
            'pizza', 'bolo', 'empanado', 'panqueca', 'wrap', 'tortilha',
            'cerveja', 'seitan', 'farelo', 'croissant', 'bisnaguinha',
        ),
        'exclude': (
            'pao de queijo', 'farinha de mandioca', 'farinha de milho',
            'farinha de arroz', 'farinha de amendoa', 'farinha de coco',
            'farinha de grao de bico', 'macarrao de arroz', 'massa de tapioca',
        ),
        'safe': ('sem gluten', 'gluten free'),
    },
    'ovo': {
        'terms':   ('ovo', 'clara', 'gema', 'omelete', 'maionese', 'gemada',
                    'suspiro', 'merengue', 'fritada'),
        'exclude': ('maionese vegana', 'maionese vegetal'),
    },
    'peixe': {
        'terms': _FISH_TERMS,
    },
    'crustaceos': {
        'terms': _CRUSTACEAN_TERMS,
    },
    'frutos_do_mar': {
        'terms': _CRUSTACEAN_TERMS + _MOLLUSC_TERMS,
    },
    'amendoim': {
        'terms': ('amendoim', 'pasta de amendoim', 'manteiga de amendoim',
                  'pacoca', 'pe de moleque'),
    },
    'oleaginosas': {
        'terms': ('castanha', 'castanha do para', 'castanha de caju', 'caju castanha',
                  'noz', 'nozes', 'amendoa', 'avela', 'pistache', 'macadamia',
                  'pecan', 'baru', 'pinoli', 'pasta de castanha'),
    },
    'soja': {
        'terms': ('soja', 'tofu', 'edamame', 'shoyu', 'missoshiru', 'misso', 'miso',
                  'tempeh', 'natto', 'proteina texturizada'),
    },
    'gergelim': {
        'terms': ('gergelim', 'tahine', 'tahini', 'homus'),
    },
    'mel': {
        'terms': ('mel',),
    },
    # ── Grupos usados pelas restrições de dieta ──────────────────────────────
    'carne_vermelha': {
        'terms': _RED_MEAT_TERMS,
    },
    'porco': {
        'terms': _PORK_TERMS,
    },
    'aves': {
        'terms': _POULTRY_TERMS,
    },
}

# Alias (termo canônico declarado pelo usuário) → famílias que ele bloqueia.
_ALLERGEN_ALIASES_RAW: dict[str, tuple[str, ...]] = {
    # Leite / laticínios
    'leite': ('leite',), 'laticinio': ('leite',), 'derivado de leite': ('leite',),
    'derivados do leite': ('leite',), 'proteina do leite': ('leite',),
    'caseina': ('leite',), 'aplv': ('leite',),
    'lactose': ('lactose',),
    # Glúten
    'gluten': ('gluten',), 'trigo': ('gluten',), 'cevada': ('gluten',),
    'centeio': ('gluten',), 'celiaco': ('gluten',), 'celiaca': ('gluten',),
    'doenca celiaca': ('gluten',),
    # Ovo
    'ovo': ('ovo',), 'clara': ('ovo',), 'gema': ('ovo',),
    # Peixes e frutos do mar
    'peixe': ('peixe',), 'pescado': ('peixe',),
    'fruto do mar': ('frutos_do_mar',), 'marisco': ('frutos_do_mar',),
    'crustaceo': ('crustaceos',), 'camarao': ('crustaceos',),
    'lagosta': ('crustaceos',), 'caranguejo': ('crustaceos',), 'siri': ('crustaceos',),
    'molusco': ('frutos_do_mar',),
    # Amendoim e oleaginosas
    'amendoim': ('amendoim',),
    'castanha': ('oleaginosas',), 'noz': ('oleaginosas',), 'nozes': ('oleaginosas',),
    'oleaginosa': ('oleaginosas',), 'amendoa': ('oleaginosas',),
    'castanha do para': ('oleaginosas',), 'castanha de caju': ('oleaginosas',),
    'avela': ('oleaginosas',), 'pistache': ('oleaginosas',),
    'macadamia': ('oleaginosas',),
    # Outros
    'soja': ('soja',), 'gergelim': ('gergelim',),
}

# Restrições de dieta → famílias bloqueadas
_DIET_RESTRICTIONS_RAW: dict[str, tuple[str, ...]] = {
    'vegetariano': ('carne_vermelha', 'porco', 'aves', 'peixe', 'frutos_do_mar'),
    'ovolactovegetariano': ('carne_vermelha', 'porco', 'aves', 'peixe', 'frutos_do_mar'),
    'vegano': ('carne_vermelha', 'porco', 'aves', 'peixe', 'frutos_do_mar',
               'ovo', 'leite', 'mel'),
    'pescetariano': ('carne_vermelha', 'porco', 'aves'),
    'pescatariano': ('carne_vermelha', 'porco', 'aves'),
    'carne vermelha': ('carne_vermelha', 'porco'),
    'porco': ('porco',),
    'carne de porco': ('porco',),
    'suino': ('porco',),
    'carne suina': ('porco',),
    'carne': ('carne_vermelha', 'porco', 'aves'),
    'frango': ('aves',),
    'ave': ('aves',),
}

# Prefixos removidos das entradas ("alergia a camarão" → "camarão")
_PREFIX_RE = re.compile(
    r'^(?:(?:eu\s+)?(?:sou|tenho|possuo)\s+)?'
    r'(?:alergi[ao]s?|alergic[oa]s?|intoleranci[ao]s?|intolerantes?|'
    r'restricao|restricoes|dieta|nao\s+(?:como|consumo|posso\s+comer|posso\s+consumir)|'
    r'evito|evitar|sem)'
    r'(?:\s+(?:a|ao|aos|as|à|de|do|da|dos|das|com|para))?\s+'
)

# Separadores aceitos no texto livre
_SPLIT_RE = re.compile(r'[,;.\n/]|\s+e\s+|\s+ou\s+')


def _canon_keys(raw: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    return {canonical(k): v for k, v in raw.items()}


_ALLERGEN_ALIASES = _canon_keys(_ALLERGEN_ALIASES_RAW)
_DIET_RESTRICTIONS = _canon_keys(_DIET_RESTRICTIONS_RAW)

# Versões canônicas pré-computadas das famílias
_FAMILIES_CANON: dict[str, dict[str, tuple[str, ...]]] = {
    name: {
        key: tuple(dict.fromkeys(canonical(t) for t in values if t))
        for key, values in fam.items()
    }
    for name, fam in _FAMILIES.items()
}


def _clean_entry(part: str) -> str:
    """Normaliza uma entrada (minúsculas, sem acento, '_' → espaço) e remove prefixos."""
    text = normalize_text(part)
    previous = None
    while previous != text:
        previous = text
        text = _PREFIX_RE.sub('', text).strip()
    return text


def _split_entries(text: str | None) -> list[str]:
    if not text or not str(text).strip():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in _SPLIT_RE.split(str(text)):
        cleaned = _clean_entry(part)
        if len(cleaned) >= 3 and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def parse_allergens(allergies_text: str | None) -> list[str]:
    """
    Parseia o campo de alergias (texto livre ou valores de checkbox) em lista
    de alérgenos normalizados (minúsculas, sem acento, '_' → espaço).

    Aceita separadores: vírgula, ponto-e-vírgula, ponto, barra, quebra de
    linha, " e ", " ou ". Remove prefixos como "alergia a", "intolerância a",
    "sou alérgico a". Descarta entradas com < 3 caracteres e duplicatas.
    """
    return _split_entries(allergies_text)


def _families_for_allergen(allergen: str) -> tuple[str, ...]:
    return _ALLERGEN_ALIASES.get(canonical(allergen), ())


def _food_in_family(food_canon: str, family: str) -> str | None:
    """Retorna o termo da família presente no alimento (canônico), ou None."""
    fam = _FAMILIES_CANON[family]
    if any_phrase(food_canon, fam.get('safe', ())):
        return None
    text = food_canon
    for phrase in fam.get('exclude', ()):
        if contains_phrase(text, phrase):
            text = f' {text} '.replace(f' {phrase} ', ' ').strip()
    return any_phrase(text, fam['terms'])


def food_contains_allergen(food_name: str | None, allergens: list[str]) -> str | None:
    """
    Retorna o alérgeno (como declarado em `allergens`) presente no alimento,
    ou None.

    Para alérgenos conhecidos, verifica toda a família de alimentos derivados
    (ex: 'leite' → queijo, iogurte, whey...). Para termos desconhecidos,
    verifica o próprio termo por palavra inteira ("novo" não casa com 'ovo').
    """
    if not food_name or not allergens:
        return None
    food_canon = canonical(food_name)
    if not food_canon:
        return None
    for allergen in allergens:
        allergen_canon = canonical(allergen)
        if not allergen_canon:
            continue
        families = _families_for_allergen(allergen)
        if families:
            if any(_food_in_family(food_canon, fam) for fam in families):
                return allergen
            continue
        if contains_phrase(food_canon, allergen_canon):
            return allergen
    return None


def _match_diet(canon: str) -> str | None:
    """
    Reconhece uma dieta na entrada canônica. Aceita variações de gênero
    ('vegetariana', 'sou vegana') comparando a raiz das dietas de uma palavra.
    """
    words = canon.split()
    for diet in _DIET_RESTRICTIONS:
        if ' ' in diet:
            if contains_phrase(canon, diet):
                return diet
            continue
        root = diet[:-1] if len(diet) > 5 else diet
        for w in words:
            if w == diet or (root != diet and w.startswith(root) and len(w) <= len(diet) + 1):
                return diet
    return None


def parse_restrictions(restrictions_text: str | None) -> list[str]:
    """
    Parseia o campo de restrições alimentares em lista de restrições
    reconhecidas (canônicas).

    Reconhece:
      - dietas: vegetariano, vegano, pescetariano, sem carne vermelha, sem porco…
      - alérgenos/intolerâncias declarados como restrição: "sem lactose",
        "sem glúten" e os valores dos checkboxes do questionário
        (gluten, lactose, ovo, soja, amendoim, frutos_do_mar, nozes, peixe)
      - "sem X" / "não como X" com X desconhecido → bloqueia X literalmente

    Texto não reconhecido sem prefixo de exclusão (ex: "low carb") é ignorado.
    """
    if not restrictions_text or not str(restrictions_text).strip():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in _SPLIT_RE.split(str(restrictions_text)):
        raw = normalize_text(part)
        if not raw:
            continue
        cleaned = _clean_entry(part)
        had_prefix = cleaned != raw
        canon = canonical(cleaned)
        if len(cleaned) < 3 or not canon:
            continue

        recognized = _match_diet(canon)
        if recognized is None and canon in _ALLERGEN_ALIASES:
            recognized = canon
        if recognized is None and had_prefix:
            recognized = canon

        if recognized and recognized not in seen:
            seen.add(recognized)
            out.append(recognized)
    return out


def food_violates_restriction(food_name: str | None, restrictions: list[str]) -> str | None:
    """Retorna a restrição violada pelo alimento, ou None."""
    if not food_name or not restrictions:
        return None
    food_canon = canonical(food_name)
    if not food_canon:
        return None
    for restriction in restrictions:
        families = _DIET_RESTRICTIONS.get(restriction) or _ALLERGEN_ALIASES.get(restriction)
        if families:
            if any(_food_in_family(food_canon, fam) for fam in families):
                return restriction
        elif contains_phrase(food_canon, restriction):
            return restriction
    return None


def is_allergen_term(term: str) -> bool:
    """True se o termo (canônico ou não) é um alérgeno conhecido (ex: 'gluten')."""
    return canonical(term) in _ALLERGEN_ALIASES


def food_is_blocked(
    food_name: str | None,
    allergens: list[str] | None = None,
    restrictions: list[str] | None = None,
) -> bool:
    """Atalho: True se o alimento viola alguma alergia ou restrição."""
    return bool(
        food_contains_allergen(food_name, allergens or [])
        or food_violates_restriction(food_name, restrictions or [])
    )
