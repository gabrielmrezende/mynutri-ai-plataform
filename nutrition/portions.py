"""
Porções práticas: categorias de alimentos por palavra-chave, arredondamento
para medidas de consumo, medidas caseiras e validação de quantidades vindas
do LLM.

Todas as palavras-chave casam por PALAVRA INTEIRA no nome canônico
(textnorm.canonical) — 'cha' não casa "Salsicha", 'maca' não casa "Macarrão".
"""

import math
import re

from .errors import TransientAIError
from .textnorm import canonical, contains_phrase

# Limites de quantidade aceitos do LLM (gramas por alimento)
MIN_QUANTITY_G = 5
MAX_QUANTITY_G = 1000

_QUANTITY_RE = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s*(?:g|gr|grs|grama|gramas|ml)?\s*$', re.IGNORECASE)


# Palavras-chave que identificam fontes proteicas primárias.
# Usadas em _adjust_to_calorie_target para preservar porções de proteína.
_PROTEIN_KEYWORDS = frozenset([
    'frango', 'carne', 'peixe', 'atum', 'salmao', 'tilapia', 'merluza',
    'bacalhau', 'sardinha', 'camarao', 'robalo', 'ovo', 'ovos', 'clara',
    'whey', 'proteina', 'feijao', 'lentilha', 'tofu', 'soja',
    'patinho', 'alcatra', 'picanha', 'file', 'musculo', 'contrafile',
    'acem', 'lagarto', 'peru', 'presunto', 'queijo', 'iogurte', 'cottage',
])

# Palavras-chave que identificam alimentos densos em gordura.
# Usadas em _adjust_to_calorie_target para evitar que escalas grandes
# multipliquem óleos/castanhas/manteiga a porções absurdas.
_FAT_KEYWORDS = frozenset([
    'azeite', 'oleo', 'manteiga', 'margarina', 'creme',
    'castanha', 'nozes', 'amendoim', 'amendoa', 'pasta amendoim',
    'abacate', 'coco', 'bacon', 'banha', 'toucinho',
])

# Bebidas de calorias zero ou negligenciáveis — nunca devem ser escaladas
# para compensar déficit calórico de outros alimentos.
_ZERO_CALORIE_KEYWORDS = frozenset([
    'refrigerante zero', 'refrigerante diet', 'refrigerante light',
    'coca zero', 'coca cola zero', 'pepsi zero', 'guarana zero',
    'bebida zero', 'agua', 'cha verde', 'cha', 'cafe preto', 'cafe',
])


def _has(name_canon: str, *keywords: str) -> bool:
    """
    True se alguma palavra-chave aparece no nome como PALAVRA INTEIRA.
    `name_canon` deve vir de textnorm.canonical(); as palavras-chave são
    canonicalizadas aqui (singular, sem acento) — 'cha' não casa "Salsicha",
    'maca' não casa "Macarrão", 'nozes' casa "Noz".
    """
    return any(contains_phrase(name_canon, canonical(kw)) for kw in keywords)

# ─────────────────────────────────────────────────────────────────────────────
#  ARREDONDAMENTO DE PORÇÕES — medidas práticas de consumo
# ─────────────────────────────────────────────────────────────────────────────
#
# Regras: (frozenset de palavras-chave, múltiplo de arredondamento, mínimo)
#
# A ordem importa: a primeira regra que casar é usada.
# Palavras-chave são testadas por palavra inteira no nome canônico (ver _has).

_ROUNDING_RULES: list[tuple[frozenset, int, int]] = [
    # Óleos e gorduras puras: colher de chá = 5g
    (frozenset(['azeite', 'oleo', 'manteiga', 'margarina', 'banha']),        5,   5),
    # Proteína em pó, aveia, farinha, granola: colher de sopa ≈ 10g
    (frozenset(['aveia', 'whey', 'farinha', 'granola', 'cereal']),          10,  10),
    # Castanhas e oleaginosas: porção = 10g
    (frozenset(['castanha', 'amendoa', 'nozes', 'pasta amendoim']),         10,  10),
    # Amendoim (inteiro): punhado ≈ 15g
    (frozenset(['amendoim torrado', 'amendoim']),                            15,  15),
    # Tapioca: meia tapioca ≈ 40g, inteira ≈ 80g → múltiplo de 20
    (frozenset(['tapioca']),                                                 20,  20),
    # Queijo e laticínios sólidos: fatia ≈ 30g
    (frozenset(['queijo', 'requeijao', 'cottage']),                         30,  30),
    # Ovos: 1 ovo médio ≈ 50g (para arredondar 1, 2, 3 ovos)
    (frozenset(['ovo', 'ovos', 'clara', 'omelete']),                        50,  50),
    # Embutidos e pão: fatia/unidade ≈ 25g
    (frozenset(['pao', 'presunto', 'peito peru', 'salsicha', 'linguica']),  25,  25),
    # Carnes, aves e peixes: filé/bife ≈ 25g de precisão, mínimo 50g
    (frozenset(['frango', 'carne', 'peixe', 'tilapia', 'salmao', 'atum',
                'sardinha', 'camarao', 'file', 'patinho', 'alcatra',
                'picanha', 'musculo', 'contrafile', 'acem', 'lagarto',
                'bacalhau', 'merluza', 'robalo', 'peru', 'carne moida',
                'carne seca', 'paio']),                                     25,  50),
    # Arroz, massas, tubérculos, leguminosas: medida de colher/concha ≈ 50g
    (frozenset(['arroz', 'macarrao', 'esparguete', 'massa', 'batata',
                'mandioca', 'aipim', 'macaxeira', 'cuscuz', 'feijao',
                'lentilha', 'grao', 'ervilha', 'milho', 'soja']),           50,  50),
    # Leite e iogurte: copo/pote ≈ 50g de precisão, mínimo 100g
    (frozenset(['leite', 'iogurte']),                                        50, 100),
    # Frutas: unidade ≈ 50g de precisão, mínimo 50g
    (frozenset(['banana', 'maca', 'laranja', 'mamao', 'manga', 'uva',
                'morango', 'melancia', 'kiwi', 'pera', 'abacaxi', 'caju',
                'tangerina', 'mexerica', 'pessego', 'goiaba']),              50,  50),
]


def _round_food_quantity(food_name: str, qty_g: float) -> int:
    """
    Arredonda a quantidade de um alimento para o múltiplo prático mais próximo.

    Usa as regras de _ROUNDING_RULES por categoria; para alimentos sem
    categoria específica aplica arredondamento graduado:
      ≤ 50g  → múltiplos de 5g
      ≤ 200g → múltiplos de 25g
       > 200g → múltiplos de 50g
    """
    normalized = canonical(food_name)

    for keywords, multiple, minimum in _ROUNDING_RULES:
        if _has(normalized, *keywords):
            rounded = round(qty_g / multiple) * multiple
            return int(max(minimum, rounded))

    # Arredondamento graduado para alimentos sem categoria específica
    if qty_g <= 50:
        return int(max(5, round(qty_g / 5) * 5))
    elif qty_g <= 200:
        return int(round(qty_g / 25) * 25)
    else:
        return int(round(qty_g / 50) * 50)


def _household_measure(food_name: str, qty_g: int) -> str:
    """
    Retorna a medida caseira aproximada para exibição ao usuário.

    Exemplos: '300g' → '≈ 8 col. de sopa' (arroz), '150g' → '≈ 1 filé médio' (frango).
    Retorna string vazia se não houver medida conhecida para o alimento.
    """
    n = canonical(food_name)
    q = qty_g

    # ── Ovos ─────────────────────────────────────────────────────────────────
    if _has(n, 'clara'):
        count = max(1, round(q / 33))
        return f'{count} {"clara" if count == 1 else "claras"}'
    if _has(n, *('ovo', 'ovos', 'omelete')):
        count = max(1, round(q / 50))
        return f'{count} {"unidade" if count == 1 else "unidades"}'

    # ── Óleos e gorduras ─────────────────────────────────────────────────────
    if _has(n, *('azeite', 'oleo', 'manteiga', 'margarina')):
        if q <= 5:   return '1 col. de chá'
        if q <= 10:  return '1 col. de sopa'
        if q <= 15:  return '1 col. de sopa cheia'
        return f'{round(q / 15)} col. de sopa'

    # ── Cereais e tubérculos ─────────────────────────────────────────────────
    if _has(n, 'arroz'):
        col = max(1, round(q / 35))
        return f'{col} col. de sopa'
    if _has(n, *('macarrao', 'esparguete', 'massa', 'penne')):
        xic = round(q / 100)
        return f'{max(1, xic)} {"xícara" if xic <= 1 else "xícaras"}'
    if _has(n, 'batata doce') or _has(n, 'batata-doce'):
        if q <= 100: return '½ unid. média'
        if q <= 180: return '1 unid. média'
        return '1 unid. grande'
    if _has(n, 'batata'):
        if q <= 100: return '1 batata pequena'
        if q <= 180: return '1 batata média'
        return '1 batata grande'
    if _has(n, 'mandioca') or _has(n, 'aipim') or _has(n, 'macaxeira'):
        if q <= 100: return '1 pedaço pequeno'
        return f'{round(q / 100)} pedaços'
    if _has(n, 'cuscuz'):
        col = max(1, round(q / 40))
        return f'{col} col. de sopa'

    # ── Leguminosas ───────────────────────────────────────────────────────────
    if _has(n, *('feijao', 'lentilha', 'grao', 'ervilha')):
        conchas = max(1, round(q / 80))
        return f'{conchas} {"concha" if conchas == 1 else "conchas"}'

    # ── Pão e tapioca ─────────────────────────────────────────────────────────
    if _has(n, 'tapioca'):
        if q <= 45:  return '½ tapioca'
        if q <= 90:  return '1 tapioca'
        if q <= 130: return '1½ tapioca'
        return f'{round(q / 80)} tapiocas'
    if _has(n, 'pao'):
        if q <= 35:  return '½ unidade'
        if q <= 65:  return '1 unidade'
        return f'{round(q / 50)} unidades'

    # ── Cereais e sementes ────────────────────────────────────────────────────
    if _has(n, *('aveia', 'granola')):
        col = max(1, round(q / 10))
        return f'{col} col. de sopa'
    if _has(n, *('whey', 'farinha')):
        col = max(1, round(q / 10))
        return f'{col} col. de sopa'

    # ── Laticínios ────────────────────────────────────────────────────────────
    if _has(n, 'leite'):
        if q <= 100: return '½ copo'
        if q <= 200: return '1 copo'
        return f'{round(q / 200)} copos'
    if _has(n, 'iogurte'):
        if q <= 120: return '½ pote'
        if q <= 220: return '1 pote'
        return f'{round(q / 180)} potes'
    if _has(n, *('queijo', 'requeijao')):
        fatias = max(1, round(q / 25))
        return f'{fatias} {"fatia" if fatias == 1 else "fatias"}'

    # ── Oleaginosas ───────────────────────────────────────────────────────────
    if _has(n, *('castanha', 'amendoa', 'nozes')):
        unid = max(1, round(q / 5))
        return f'{unid} unidades'
    if _has(n, 'amendoim') and not _has(n, 'pasta'):
        if q <= 15: return '1 punhado'
        return f'{round(q / 15)} punhados'
    if _has(n, 'pasta') and _has(n, 'amendoim'):
        col = max(1, round(q / 15))
        return f'{col} col. de sopa'

    # ── Carnes, aves e peixes ─────────────────────────────────────────────────
    if _has(n, *('frango', 'tilapia', 'salmao', 'peixe',
                             'file', 'merluza', 'bacalhau', 'robalo')):
        if q <= 100: return '1 filé pequeno'
        if q <= 160: return '1 filé médio'
        if q <= 220: return '1 filé grande'
        return f'{round(q / 150)} filés'
    if _has(n, *('patinho', 'alcatra', 'picanha', 'contrafile',
                             'carne bovina', 'carne moida', 'musculo', 'acem')):
        if q <= 120: return '1 bife pequeno'
        if q <= 180: return '1 bife médio'
        return '1 bife grande'
    if _has(n, 'atum'):
        latas = max(1, round(q / 85))
        return f'{latas} {"lata" if latas == 1 else "latas"}'
    if _has(n, 'sardinha'):
        return '1 lata' if q <= 100 else '2 latas'

    # ── Frutas ────────────────────────────────────────────────────────────────
    if _has(n, *('banana',)):
        if q <= 80: return '½ banana'
        if q <= 130: return '1 banana'
        return '1 banana grande'
    if _has(n, *('maca', 'pera', 'pessego')):
        if q <= 100: return '½ unidade'
        return '1 unidade'
    if _has(n, *('laranja', 'tangerina', 'mexerica')):
        if q <= 80: return '½ unidade'
        return '1 unidade'
    if _has(n, *('mamao', 'manga')):
        if q <= 100: return '1 fatia'
        if q <= 200: return '2 fatias'
        return '3 fatias'

    # ── Legumes e folhas ──────────────────────────────────────────────────────
    if _has(n, *('alface', 'rucula', 'espinafre', 'acelga', 'salada')):
        if q <= 40: return '½ prato'
        return '1 prato'
    if _has(n, *('brocolis', 'couve', 'cenoura', 'abobrinha', 'chuchu')):
        if q <= 80: return '½ xícara'
        return '1 xícara'

    return ''


def _coerce_quantity_g(value) -> float | None:
    """
    Converte quantity_g vindo do LLM em gramas dentro de [5, 1000].

    Aceita número ou texto simples como "150", "150g", "150,5 g".
    Retorna None para quantidade ausente, ≤ 0, NaN ou infinita (o alimento
    conta como lacuna de cobertura). Levanta TransientAIError para valores
    que não são quantidades (ex: "um pouco", listas) — o LLM errou o formato.
    """
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise TransientAIError('A IA retornou quantidades em formato inválido. Tente novamente.')
    if isinstance(value, (int, float)):
        qty = float(value)
    elif isinstance(value, str):
        match = _QUANTITY_RE.match(value)
        if not match:
            raise TransientAIError('A IA retornou quantidades em formato inválido. Tente novamente.')
        qty = float(match.group(1).replace(',', '.'))
    else:
        raise TransientAIError('A IA retornou quantidades em formato inválido. Tente novamente.')
    if math.isnan(qty) or math.isinf(qty) or qty <= 0:
        return None
    return float(min(MAX_QUANTITY_G, max(MIN_QUANTITY_G, qty)))
