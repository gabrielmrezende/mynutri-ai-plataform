"""
Normalização de texto compartilhada pelos módulos de matching de alimentos
(alergias, restrições, palavras-chave de porções).

Todo matching é feito por PALAVRA INTEIRA sobre tokens normalizados:
minúsculas, sem acentos, no singular e sem preposições/artigos. Isso evita
os falsos positivos de substring ('cha' casando com "Salsicha", 'ovo' com
"novo") e os falsos negativos de plural ("Camarões" x 'camarao').
"""

import re
import unicodedata

# Preposições e artigos ignorados no matching ("castanha-do-pará" ≡ "castanha para")
_STOPWORDS = frozenset({
    'a', 'o', 'as', 'os', 'e', 'de', 'do', 'da', 'dos', 'das',
    'em', 'no', 'na', 'nos', 'nas', 'ao', 'aos', 'com',
})

# Sufixos de plural → singular (ordem importa: o primeiro que casar é usado)
_PLURAL_RULES: tuple[tuple[str, str], ...] = (
    ('oes', 'ao'),   # camarões → camarao, limões → limao
    ('aes', 'ao'),   # pães → pao
    ('ais', 'al'),   # cereais → cereal
    ('eis', 'el'),   # pastéis → pastel
    ('ois', 'ol'),   # anzóis → anzol
    ('ns',  'm'),    # amendoins → amendoim
    ('zes', 'z'),    # nozes → noz
    ('res', 'r'),    # colheres → colher
)


def strip_accents(text: str) -> str:
    text = unicodedata.normalize('NFD', text)
    return ''.join(c for c in text if unicodedata.category(c) != 'Mn')


def normalize_text(text: str | None) -> str:
    """Minúsculas, sem acentos, '_'/'-' viram espaço e pontuação é removida."""
    if not text:
        return ''
    text = strip_accents(str(text)).lower()
    text = re.sub(r'[_\-/]+', ' ', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def singularize(word: str) -> str:
    """Singular aproximado do português — suficiente para nomes de alimentos."""
    if len(word) <= 3:
        return word
    for suffix, repl in _PLURAL_RULES:
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            return word[: -len(suffix)] + repl
    if word.endswith('s') and not word.endswith('ss'):
        return word[:-1]
    return word


def tokens(text: str | None) -> list[str]:
    """Tokens normalizados, no singular e sem stopwords."""
    return [
        singularize(w) for w in normalize_text(text).split()
        if w not in _STOPWORDS
    ]


def canonical(text: str | None) -> str:
    """Forma canônica para matching: tokens unidos por espaço."""
    return ' '.join(tokens(text))


def contains_phrase(haystack_canonical: str, phrase_canonical: str) -> bool:
    """
    True se a frase (canônica) aparece como sequência de palavras inteiras
    no texto (canônico). Ambos já devem ter passado por canonical().
    """
    if not haystack_canonical or not phrase_canonical:
        return False
    return f' {phrase_canonical} ' in f' {haystack_canonical} '


def any_phrase(haystack_canonical: str, phrases) -> str | None:
    """Retorna a primeira frase (canônica) presente no texto, ou None."""
    for p in phrases:
        if contains_phrase(haystack_canonical, p):
            return p
    return None
