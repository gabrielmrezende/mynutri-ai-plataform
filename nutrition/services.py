"""
Arquitetura de geração de dietas em passos:

  Passo 1 — LLM (temp=0.55): seleciona alimentos e quantidades (sem macros)
  Backend:  consulta nutrition_db.py e calcula macros deterministicamente;
            aplica alergias/restrições, ajusta porções e valida macros
  Passos 2+3 — LLM (temp=0.7, em paralelo): dicas e explicação usando os
            valores calculados

Isso elimina a variabilidade de macros causada por delegar aritmética ao modelo.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import Anamnese, DietPlan, Meal

# ── Módulos extraídos de services.py ─────────────────────────────────────────
#   ai_client.py  — HTTP da API de IA (retry, parse da resposta)
#   errors.py     — hierarquia de exceções
#   allergens.py  — alergias e restrições alimentares
#   portions.py   — palavras-chave, arredondamento e medidas caseiras
#   validators.py — estrutura do JSON do LLM e proporções de macros
# Os nomes abaixo são re-exportados para manter os imports existentes
# (views, tasks, testes e patches com caminho 'nutrition.services.X').
from .ai_client import AIClient
from .allergens import (  # noqa: F401
    declared_allergens as _declared_allergens,
    declared_restrictions as _declared_restrictions,
    food_contains_allergen,
    food_violates_restriction,
    parse_allergens,
    parse_restrictions,
)
from .errors import (  # noqa: F401
    AllergenViolation,
    DietGenerationError,
    MacroImbalanceError,
    NutritionDataGap,
    PermanentAIError,
    RestrictionViolation,
    TransientAIError,
)
from .nutrition_db import lookup_food_nutrition
from .portions import (  # noqa: F401
    MAX_QUANTITY_G,
    MIN_QUANTITY_G,
    _FAT_KEYWORDS,
    _PROTEIN_KEYWORDS,
    _ZERO_CALORIE_KEYWORDS,
    _coerce_quantity_g,
    _has,
    _household_measure,
    _round_food_quantity,
)
from .textnorm import canonical
from .validators import _validate_plan_structure, macro_ratio_violations


# Parsing e matching de alergias/restrições vivem em allergens.py; os nomes
# com prefixo "_" são mantidos por compatibilidade (views e testes os importam).
_parse_allergens = parse_allergens
_food_contains_allergen = food_contains_allergen
_parse_restrictions = parse_restrictions


from .prompts import (
    SYSTEM_PROMPT_EXPLANATION,
    SYSTEM_PROMPT_FOODS,
    SYSTEM_PROMPT_MEAL_REGEN,
    SYSTEM_PROMPT_NOTES,
    build_explanation_prompt,
    build_food_selection_prompt,
    build_meal_regen_prompt,
    build_notes_prompt,
    calculate_calories,
    calculate_energy_plan,
    calculate_macros,
)
from .substitutions import generate_meal_substitutions

logger = logging.getLogger(__name__)


def substitutions_for_plan(meals: list[dict], anamnese) -> list[dict]:
    """
    Gera substituições respeitando alergias E restrições do usuário.
    Ponto único para views/tasks gerarem substituições de um plano.
    """
    if anamnese is None:
        return generate_meal_substitutions(meals, [])
    return generate_meal_substitutions(
        meals,
        _declared_allergens(anamnese),
        restrictions=_declared_restrictions(anamnese),
    )


class AIService(AIClient):
    """
    Orquestra a geração de dieta via API compatível com OpenAI.
    A comunicação HTTP (_call_api, _parse_response) vem de ai_client.AIClient.
    """

    # ──────────────────────────────────────────────────────────────────────────
    #  ENRIQUECIMENTO NUTRICIONAL (backend — determinístico)
    # ──────────────────────────────────────────────────────────────────────────

    def _enrich_foods_with_macros(self, diet_data: dict) -> tuple[dict, dict]:
        """
        Consulta o nutrition_db para cada alimento e atribui calorias e macros.
        Também padroniza o campo 'quantity' para exibição no frontend.

        quantity_g do LLM é limitada a [5, 1000] g. Quantidade ausente, ≤ 0
        ou NaN conta como 'invalid' (lacuna de cobertura) e usa 100 g.

        Retorna (diet_data, stats), onde stats agrega contagem por camada de
        match do nutrition_db. Usado por _check_db_coverage para rejeitar planos
        com muitos alimentos sem cobertura confiável.
        """
        stats = {
            'total': 0, 'exact': 0, 'fuzzy': 0, 'fuzzy_weak': 0, 'category': 0,
            'generic': 0, 'invalid': 0, 'generic_names': [],
        }
        for meal in diet_data.get('meals', []):
            for food in meal.get('foods', []):
                raw_qty = food.get('quantity_g')
                coerced = _coerce_quantity_g(raw_qty)
                quantity_invalid = coerced is None
                qty_g = 100.0 if quantity_invalid else coerced
                food['quantity_g'] = round(qty_g)
                qty_text = food.get('quantity_text') or f'{qty_g:.0f}g'
                if not isinstance(raw_qty, (int, float)) or isinstance(raw_qty, bool) or float(raw_qty) != qty_g:
                    # Quantidade corrigida/limitada: o texto do LLM não vale mais
                    qty_text = f'{qty_g:.0f}g'
                food['quantity_text'] = qty_text

                nutrition = lookup_food_nutrition(food.get('name', ''), qty_g)
                food['calories']  = nutrition['calories']
                food['protein_g'] = nutrition['protein_g']
                food['carbs_g']   = nutrition['carbs_g']
                food['fat_g']     = nutrition['fat_g']

                source = 'invalid' if quantity_invalid else nutrition.get('_source', 'unknown')
                stats['total'] += 1
                stats[source] = stats.get(source, 0) + 1
                if source in self.DB_GAP_SOURCES:
                    stats['generic_names'].append(food.get('name', '?'))

                # Campo 'quantity' usado pelo frontend (combina texto + gramas)
                qty_g_int = round(qty_g)
                if str(qty_g_int) in qty_text or f'{qty_g_int}g' in qty_text:
                    food['quantity'] = qty_text
                else:
                    food['quantity'] = f'{qty_text} ({qty_g_int}g)'

        return diet_data, stats

    def _recalculate_totals(self, diet_data: dict) -> dict:
        """Recalcula macros e calorias totais somando os alimentos individuais."""
        total_cal  = 0
        total_prot = 0.0
        total_carb = 0.0
        total_fat  = 0.0

        for meal in diet_data.get('meals', []):
            for food in meal.get('foods', []):
                total_cal  += food.get('calories',  0) or 0
                total_prot += food.get('protein_g', 0) or 0
                total_carb += food.get('carbs_g',   0) or 0
                total_fat  += food.get('fat_g',     0) or 0

        diet_data['calories'] = total_cal
        diet_data['macros']   = {
            'protein_g': round(total_prot),
            'carbs_g':   round(total_carb),
            'fat_g':     round(total_fat),
        }
        return diet_data

    @staticmethod
    def _is_protein_food(food_name: str) -> bool:
        """Retorna True se o alimento é fonte proteica primária."""
        return _has(canonical(food_name), *_PROTEIN_KEYWORDS)

    @staticmethod
    def _is_fat_food(food_name: str) -> bool:
        """
        Retorna True se o alimento é denso em gordura (óleos, castanhas, manteiga).
        Usado em _adjust_to_calorie_target para evitar que escalas grandes
        multipliquem porções a valores absurdos (ex: azeite 10g → 60g).
        """
        return _has(canonical(food_name), *_FAT_KEYWORDS)

    @staticmethod
    def _is_zero_calorie_drink(food_name: str) -> bool:
        """
        Retorna True para bebidas zero/diet que não devem ser escaladas.
        Além da palavra-chave, exige densidade calórica desprezível no banco
        (≤ 10 kcal/100g) — "Água de coco" e "Bolacha de água e sal" não são zero.
        """
        if not _has(canonical(food_name), *_ZERO_CALORIE_KEYWORDS):
            return False
        return lookup_food_nutrition(food_name, 100)['calories'] <= 10

    # Ajuste de porções: tolerância, iterações e limites por categoria
    # (fator mínimo, fator máximo) relativos à quantidade ORIGINAL do LLM
    CALORIE_TOLERANCE    = 0.10
    ADJUST_MAX_ITERATIONS = 8
    _ADJUST_BOUNDS = {
        'zero':    (1.00, 1.00),   # bebidas zero: porção não afeta calorias
        'protein': (0.85, 1.15),   # preserva adequação proteica
        'fat':     (0.80, 1.20),   # evita explosão calórica de óleo/castanha
        'other':   (0.30, 3.00),   # carboidratos/vegetais absorvem o ajuste
    }

    def _food_adjust_category(self, name: str) -> str:
        if self._is_zero_calorie_drink(name):
            return 'zero'
        if self._is_protein_food(name):
            return 'protein'
        if self._is_fat_food(name):
            return 'fat'
        return 'other'

    @staticmethod
    def _set_food_quantity(food: dict, qty: int) -> None:
        """Atualiza quantidade, macros (via nutrition_db) e texto de exibição."""
        name = food.get('name', '')
        food['quantity_g'] = qty
        nutrition = lookup_food_nutrition(name, qty)
        food['calories']  = nutrition['calories']
        food['protein_g'] = nutrition['protein_g']
        food['carbs_g']   = nutrition['carbs_g']
        food['fat_g']     = nutrition['fat_g']
        measure = _household_measure(name, qty)
        food['quantity_text'] = f'{qty}g'
        food['quantity']      = f'{qty}g ({measure})' if measure else f'{qty}g'

    def _adjust_to_calorie_target(self, diet_data: dict, target_calories: int) -> dict:
        """
        Se o total calculado divergir mais de 10% do alvo, ajusta quantity_g
        iterativamente (até ADJUST_MAX_ITERATIONS passadas) com escala seletiva
        por categoria e teto por alimento relativo à quantidade original:

          - Proteínas (frango, peixe, ovo…):       0.85–1.15× — preserva adequação proteica
          - Gorduras densas (azeite, castanhas…):  0.80–1.20× — evita explosão calórica de óleo
          - Demais (arroz, batata, pão, vegetais…): 0.30–3.00× — absorvem o ajuste principal
          - Bebidas zero: inalteradas
        Toda quantidade fica em [5, 1000] g.

        Uma passada só não basta: os caps de proteína/gordura fazem o total
        ficar aquém do alvo; as passadas seguintes redistribuem o restante
        para os alimentos que ainda têm folga. Para quando entra na tolerância
        ou quando nenhum alimento pode mais ser ajustado.
        """
        actual = diet_data.get('calories', 0)
        if not actual or not target_calories:
            return diet_data

        divergence = abs(actual - target_calories) / target_calories
        if divergence <= self.CALORIE_TOLERANCE:
            return diet_data

        logger.warning(
            'Total calculado (%d kcal) diverge %.1f%% do alvo (%d kcal). Ajustando porções.',
            actual, divergence * 100, target_calories,
        )

        foods = [f for meal in diet_data.get('meals', []) for f in meal.get('foods', [])]
        originals = [float(f.get('quantity_g') or 100) for f in foods]
        categories = [self._food_adjust_category(f.get('name', '')) for f in foods]

        for _ in range(self.ADJUST_MAX_ITERATIONS):
            actual = diet_data.get('calories', 0)
            if not actual or abs(actual - target_calories) / target_calories <= self.CALORIE_TOLERANCE:
                break

            # Escala apenas a parcela ajustável: calorias dos alimentos travados
            # (no limite na direção desejada) não respondem à escala.
            growing = target_calories > actual
            adjustable_kcal = 0.0
            for food, orig, cat in zip(foods, originals, categories):
                lo, hi = self._ADJUST_BOUNDS[cat]
                qty = float(food.get('quantity_g') or 0)
                limit = min(MAX_QUANTITY_G, orig * hi) if growing else max(MIN_QUANTITY_G, orig * lo)
                if (growing and qty < limit) or (not growing and qty > limit):
                    adjustable_kcal += food.get('calories', 0) or 0
            if adjustable_kcal <= 0:
                break
            scale = max(0.0, 1 + (target_calories - actual) / adjustable_kcal)

            changed = False
            for food, orig, cat in zip(foods, originals, categories):
                lo, hi = self._ADJUST_BOUNDS[cat]
                qty = float(food.get('quantity_g') or 0)
                new_qty = qty * scale
                new_qty = min(orig * hi, max(orig * lo, new_qty))
                new_qty = round(min(MAX_QUANTITY_G, max(MIN_QUANTITY_G, new_qty)))
                if new_qty != round(qty):
                    changed = True
                self._set_food_quantity(food, new_qty)

            diet_data = self._recalculate_totals(diet_data)
            if not changed:
                break

        return diet_data

    def _round_portions(self, diet_data: dict, target_calories: int | None = None) -> dict:
        """
        Arredonda as quantidades de todos os alimentos para medidas práticas de consumo.

        Após arredondar, recalcula as calorias e macros de cada alimento via
        nutrition_db e atualiza os totais do plano. O campo 'quantity' ganha
        a medida caseira (ex: "300g (≈ 8 col. de sopa)") para exibição no frontend.
        """
        changed = 0
        for meal in diet_data.get('meals', []):
            for food in meal.get('foods', []):
                old_qty = int(food.get('quantity_g') or 10)
                new_qty = _round_food_quantity(food.get('name', ''), old_qty)
                if new_qty != old_qty:
                    changed += 1
                    food['quantity_g'] = new_qty
                    nutrition = lookup_food_nutrition(food.get('name', ''), new_qty)
                    food['calories']  = nutrition['calories']
                    food['protein_g'] = nutrition['protein_g']
                    food['carbs_g']   = nutrition['carbs_g']
                    food['fat_g']     = nutrition['fat_g']

                qty = int(food.get('quantity_g', old_qty))
                measure = _household_measure(food.get('name', ''), qty)
                food['quantity_text'] = f'{qty}g'
                food['quantity'] = f'{qty}g ({measure})' if measure else f'{qty}g'

        diet_data = self._recalculate_totals(diet_data)
        if changed:
            if target_calories:
                total = diet_data.get('calories', 0)
                dev = abs(total - target_calories) / target_calories * 100
                logger.info(
                    '[ROUND_PORTIONS] %d porções arredondadas. Total: %d kcal (desvio: %.1f%% do alvo %d kcal)',
                    changed, total, dev, target_calories,
                )
        return diet_data

    def _fit_portions(self, diet_data: dict, target_calories: int) -> dict:
        """
        Ajusta porções ao alvo e arredonda para medidas práticas. O
        arredondamento pode tirar o total da tolerância — nesse caso ajusta
        e arredonda de novo (uma vez) e registra se ainda ficou fora.
        """
        diet_data = self._adjust_to_calorie_target(diet_data, target_calories)
        diet_data = self._round_portions(diet_data, target_calories)
        if self._calorie_divergence(diet_data, target_calories) > self.CALORIE_TOLERANCE:
            diet_data = self._adjust_to_calorie_target(diet_data, target_calories)
            diet_data = self._round_portions(diet_data, target_calories)
            divergence = self._calorie_divergence(diet_data, target_calories)
            if divergence > self.CALORIE_TOLERANCE:
                logger.warning(
                    '[PORTIONS] Total %d kcal ainda diverge %.1f%% do alvo %d kcal após arredondamento.',
                    diet_data.get('calories', 0), divergence * 100, target_calories,
                )
        return diet_data

    @staticmethod
    def _calorie_divergence(diet_data: dict, target_calories: int) -> float:
        if not target_calories:
            return 0.0
        return abs((diet_data.get('calories') or 0) - target_calories) / target_calories

    def _check_protein_adequacy(
        self,
        diet_data: dict,
        anamnese: Anamnese,
        target_calories: int,
    ) -> None:
        """
        Verifica se a proteína calculada do plano está próxima da meta.
        Loga aviso se o modelo ignorou a instrução de macros — útil para
        identificar casos onde o prompt não está sendo respeitado.
        """
        target = calculate_macros(anamnese, target_calories)['protein_g']
        actual = diet_data.get('macros', {}).get('protein_g', 0)
        if not target:
            return

        ratio = actual / target
        if ratio < 0.75:
            logger.warning(
                '[PROTEIN_GAP] Proteína do plano: %dg — apenas %.0f%% da meta (%dg) '
                'para usuário %s. O modelo pode não ter respeitado a instrução de macros.',
                actual, ratio * 100, target, anamnese.user_id,
            )
        else:
            logger.info(
                '[PROTEIN_CHECK] Proteína: %dg/%dg (%.0f%% da meta) — usuário %s.',
                actual, target, ratio * 100, anamnese.user_id,
            )

    def _macro_ratio_violations(
        self,
        diet_data: dict,
        anamnese: Anamnese,
        target_calories: int,
    ) -> list[str]:
        """Lista de violações de proporção de macros (ver validators.macro_ratio_violations)."""
        return macro_ratio_violations(diet_data, anamnese, target_calories)

    def _validate_macro_ratios(
        self,
        diet_data: dict,
        anamnese: Anamnese,
        target_calories: int,
    ) -> None:
        """
        Valida que as proporções de macronutrientes do plano estão dentro de
        limites fisiologicamente razoáveis (ver _macro_ratio_violations).
        Levanta MacroImbalanceError (retryable) se algum limite for violado.
        """
        violations = self._macro_ratio_violations(diet_data, anamnese, target_calories)
        if violations:
            detail = '; '.join(violations)
            logger.error(
                '[MACRO_IMBALANCE] Desbalanceamento de macros para usuário %s: %s',
                anamnese.user_id, detail,
            )
            raise MacroImbalanceError(
                f'Desbalanceamento de macros no plano gerado: {detail}. '
                f'Tente gerar novamente.'
            )

        macros = diet_data.get('macros', {})
        logger.info(
            '[MACRO_VALID] Macros dentro dos limites — usuário %s: P=%sg C=%sg G=%sg (%s kcal)',
            anamnese.user_id,
            macros.get('protein_g', 0), macros.get('carbs_g', 0), macros.get('fat_g', 0),
            diet_data.get('calories', 0),
        )

    # ──────────────────────────────────────────────────────────────────────────
    #  COBERTURA DO BANCO NUTRICIONAL — confiabilidade calórica
    # ──────────────────────────────────────────────────────────────────────────

    # Limite acima do qual a cobertura é considerada insuficiente.
    # ≥2 alimentos no fallback genérico E ≥20% do total dispara rejeição.
    # O floor de 2 evita rejeição em planos pequenos onde 1 alimento exótico
    # pode legitimamente estar fora do TACO.
    DB_COVERAGE_MIN_GENERIC_COUNT = 2
    DB_COVERAGE_MAX_GENERIC_RATIO = 0.20
    # Camadas do nutrition_db que contam como lacuna de cobertura
    DB_GAP_SOURCES = ('generic', 'fuzzy_weak', 'invalid')

    def _check_db_coverage(self, stats: dict, anamnese: Anamnese) -> None:
        """
        Verifica quantos alimentos caíram no fallback genérico (sem cobertura
        no nutrition_db) e levanta NutritionDataGap se for excessivo.

        O fallback genérico atribui 150 kcal/100g a qualquer alimento desconhecido,
        o que mascara erros graves: pão de queijo (~330), hambúrguer (~280),
        coxinha (~280) — todos seriam subestimados em ~50%. Matches fuzzy fracos
        ('fuzzy_weak') e quantidades inválidas ('invalid') contam como lacuna.

        NutritionDataGap é TransientAIError — a task do Celery faz retry.
        """
        total = stats.get('total', 0)
        if total == 0:
            return

        generic = sum(stats.get(src, 0) for src in self.DB_GAP_SOURCES)
        ratio = generic / total

        if generic >= self.DB_COVERAGE_MIN_GENERIC_COUNT and ratio >= self.DB_COVERAGE_MAX_GENERIC_RATIO:
            names = stats.get('generic_names', [])
            preview = ', '.join(names[:5]) + ('...' if len(names) > 5 else '')
            logger.error(
                '[DB_COVERAGE] Plano para usuário %s: %d/%d (%.0f%%) alimentos sem '
                'cobertura no banco nutricional: %s',
                anamnese.user_id, generic, total, ratio * 100, names,
            )
            raise NutritionDataGap(
                f'Cobertura nutricional insuficiente: {generic} de {total} alimentos '
                f'({ratio * 100:.0f}%) sem dados nutricionais confiáveis ({preview}). '
                f'Tente gerar novamente.'
            )

        if generic > 0:
            logger.info(
                '[DB_COVERAGE] Usuário %s: %d/%d alimentos no fallback genérico (%.0f%%) — abaixo do limite.',
                anamnese.user_id, generic, total, ratio * 100,
            )

    # ──────────────────────────────────────────────────────────────────────────
    #  ENFORCEMENT DE ALERGIAS — segurança nutricional crítica
    # ──────────────────────────────────────────────────────────────────────────

    def _enforce_allergies(self, diet_data: dict, anamnese: Anamnese) -> None:
        """
        Verifica se algum alimento do plano viola as alergias declaradas.

        O LLM pode ignorar a instrução "evite completamente" no prompt. Esta
        camada determinística é a última linha de defesa antes de servir um
        plano potencialmente perigoso. Cada alérgeno é expandido para a sua
        família de alimentos (ex: 'leite' → queijo, iogurte, whey...).

        Levanta AllergenViolation (TransientAIError): a task do Celery faz
        retry automático — geração não-determinística pode produzir um plano
        válido na próxima tentativa.
        """
        allergens = _declared_allergens(anamnese)
        if not allergens:
            return

        violations = self._find_violations(
            diet_data, lambda name: food_contains_allergen(name, allergens),
        )
        if violations:
            logger.error(
                '[ALLERGY_VIOLATION] Plano para usuário %s viola alergias declaradas: %s',
                anamnese.user_id, self._format_violations(violations),
            )
            raise AllergenViolation(
                'O plano gerado contém alimentos incompatíveis com as alergias '
                f'declaradas ({self._format_violations(violations)}). Tente gerar novamente.'
            )

    def _enforce_restrictions(self, diet_data: dict, anamnese: Anamnese) -> None:
        """
        Verifica se algum alimento do plano viola as restrições de dieta
        declaradas (vegetariano, vegano, sem lactose, sem glúten...).
        Levanta RestrictionViolation (retryable), como _enforce_allergies.
        """
        restrictions = _declared_restrictions(anamnese)
        if not restrictions:
            return

        violations = self._find_violations(
            diet_data, lambda name: food_violates_restriction(name, restrictions),
        )
        if violations:
            logger.error(
                '[RESTRICTION_VIOLATION] Plano para usuário %s viola restrições declaradas: %s',
                anamnese.user_id, self._format_violations(violations),
            )
            raise RestrictionViolation(
                'O plano gerado contém alimentos incompatíveis com as restrições '
                f'alimentares declaradas ({self._format_violations(violations)}). '
                'Tente gerar novamente.'
            )

    @staticmethod
    def _find_violations(diet_data: dict, matcher) -> list[tuple[str, str, str]]:
        """Lista (refeição, alimento, termo violado) para cada alimento bloqueado."""
        violations: list[tuple[str, str, str]] = []
        for meal in diet_data.get('meals', []):
            meal_name = meal.get('name', '?')
            for food in meal.get('foods', []):
                food_name = food.get('name', '')
                matched = matcher(food_name)
                if matched:
                    violations.append((meal_name, food_name, matched))
        return violations

    @staticmethod
    def _format_violations(violations: list[tuple[str, str, str]]) -> str:
        return '; '.join(
            f'"{food}" em "{meal}" ({term})' for meal, food, term in violations[:5]
        )

    # ──────────────────────────────────────────────────────────────────────────
    #  DICAS PERSONALIZADAS (chamada separada, falha silenciosamente)
    # ──────────────────────────────────────────────────────────────────────────

    def _generate_notes(
        self,
        diet_data: dict,
        anamnese: Anamnese,
        target_calories: int,
    ) -> dict:
        """
        Gera dicas práticas e personalizadas com base no perfil e plano reais.

        Retorna um dict com:
          - 'notes': string com dicas gerais formatadas em bullet points (ou None)
          - 'meal_notes': dict {int(index): str} com dicas por refeição (ou {})

        Falha silenciosamente — o plano é válido mesmo sem dicas.
        """
        prompt = build_notes_prompt(diet_data, anamnese, target_calories)
        try:
            raw = self._call_api(
                prompt,
                system_prompt=SYSTEM_PROMPT_NOTES,
                temperature=0.7,
                json_mode=True,
                max_tokens=800,  # 3–5 dicas gerais + meal_notes por refeição
            )
            result = self._parse_response(raw)

            # Dicas gerais
            tips = result.get('tips')
            notes_str = None
            if tips and isinstance(tips, list):
                cleaned = [t.strip() for t in tips if isinstance(t, str) and t.strip()]
                notes_str = '\n'.join(f'• {t}' for t in cleaned) if cleaned else None

            # Dicas por refeição — o modelo usa o nome da refeição como chave.
            # Converte para índice inteiro mapeando pelo nome real das refeições,
            # com fallback para chaves numéricas (0-based e 1-based) por compatibilidade.
            meal_notes_raw = result.get('meal_notes', {})
            meal_notes: dict[int, str] = {}
            if isinstance(meal_notes_raw, dict):
                meals = diet_data.get('meals', [])
                meal_name_to_index = {
                    m.get('name', ''): i for i, m in enumerate(meals)
                }
                for k, v in meal_notes_raw.items():
                    if not (isinstance(v, str) and v.strip()):
                        continue
                    if k in meal_name_to_index:
                        meal_notes[meal_name_to_index[k]] = v.strip()
                    elif k.isdigit():
                        idx = int(k)
                        # aceita tanto 0-based quanto 1-based
                        if 0 <= idx < len(meals):
                            meal_notes[idx] = v.strip()
                        elif 1 <= idx <= len(meals):
                            meal_notes[idx - 1] = v.strip()

            return {'notes': notes_str, 'meal_notes': meal_notes}

        except Exception as exc:
            logger.warning('Falha ao gerar dicas personalizadas (não crítico): %s', exc)
            return {'notes': None, 'meal_notes': {}}

    # ──────────────────────────────────────────────────────────────────────────
    #  PASSO 2 — EXPLICAÇÃO (chamada separada, falha silenciosamente)
    # ──────────────────────────────────────────────────────────────────────────

    def _generate_explanation(
        self,
        diet_data: dict,
        anamnese: Anamnese,
        tmb: int,
        tdee: int,
        target_calories: int,
    ) -> dict | None:
        """
        Gera o objeto 'explanation' em chamada separada com temperature mais alta.
        Retorna None se falhar — a explicação é opcional e o frontend tem fallback.
        """
        prompt = build_explanation_prompt(diet_data, anamnese, tmb, tdee, target_calories)
        try:
            raw = self._call_api(
                prompt,
                system_prompt=SYSTEM_PROMPT_EXPLANATION,
                temperature=0.7,
                json_mode=True,
                max_tokens=1200,  # 5 seções × ~3 parágrafos × ~80 tokens cada
            )
            explanation = self._parse_response(raw)
            # Valida que os 5 campos obrigatórios existem
            required = {'calorie_calculation', 'macro_distribution', 'food_choices',
                        'meal_structure', 'goal_alignment'}
            if not required.issubset(explanation.keys()):
                logger.warning('Explanation incompleta: campos faltando. Ignorando.')
                return None
            return explanation
        except Exception as exc:
            logger.warning('Falha ao gerar explanation (não crítico): %s', exc)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    #  MÉTODO PRINCIPAL
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _food_selection_max_tokens(meals_per_day) -> int:
        """
        max_tokens do Passo 1 proporcional ao número de refeições:
        ~5 alimentos × ~80 tokens por refeição + overhead do JSON.
        """
        try:
            meals = int(meals_per_day or 3)
        except (TypeError, ValueError):
            meals = 3
        return max(1500, min(6000, 450 * meals + 500))

    def generate_diet(self, anamnese: Anamnese) -> DietPlan:
        """
        Gera e persiste um DietPlan completo.

        Fluxo:
          1. Backend calcula alvo calórico e macros (Mifflin-St Jeor) — determinístico
          2. LLM Passo 1 (temp=0.55): seleciona alimentos + quantidades
          3. Backend: enriquece com macros do nutrition_db, ajusta porções — determinístico
          4. Backend: gera substituições — determinístico
          5. LLM Passos 2+3 (temp=0.7) em paralelo: notas e explicação — simultâneos
          6. Persiste DietPlan + Meals no banco
        """
        energy = calculate_energy_plan(anamnese)
        tmb, tdee, target_calories = energy['tmb'], energy['tdee'], energy['target_calories']
        logger.info(
            'Alvo calórico para usuário %s: TMB=%d, TDEE=%d, meta=%d kcal (objetivo: %s, efetivo: %s)',
            anamnese.user_id, tmb, tdee, target_calories, anamnese.goal, energy['effective_goal'],
        )

        # ── Passo 1: seleção de alimentos ────────────────────────────────────
        prompt = build_food_selection_prompt(anamnese)
        logger.info('Passo 1 — chamando IA para seleção de alimentos (usuário %s)...', anamnese.user_id)

        # Erros da API já chegam tipados (TransientAIError/PermanentAIError) —
        # propagam sem embrulho para a task decidir sobre retry.
        raw_response = self._call_api(
            prompt,
            system_prompt=SYSTEM_PROMPT_FOODS,
            temperature=0.55,
            json_mode=True,
            max_tokens=self._food_selection_max_tokens(anamnese.meals_per_day),
        )

        diet_data = self._parse_response(raw_response)
        _validate_plan_structure(diet_data)

        # ── Enforcement de alergias e restrições (fail-fast) ──────────────────
        self._enforce_allergies(diet_data, anamnese)
        self._enforce_restrictions(diet_data, anamnese)

        # ── Backend: enriquece com macros do banco nutricional ────────────────
        logger.info('Calculando macros via banco nutricional para usuário %s...', anamnese.user_id)
        diet_data, db_stats = self._enrich_foods_with_macros(diet_data)
        # Rejeita planos com cobertura insuficiente — força retry da task
        self._check_db_coverage(db_stats, anamnese)
        diet_data = self._recalculate_totals(diet_data)
        diet_data = self._fit_portions(diet_data, target_calories)

        logger.info(
            'Macros calculados: %d kcal | P=%dg | C=%dg | G=%dg (alvo: %d kcal)',
            diet_data.get('calories', 0),
            diet_data.get('macros', {}).get('protein_g', 0),
            diet_data.get('macros', {}).get('carbs_g', 0),
            diet_data.get('macros', {}).get('fat_g', 0),
            target_calories,
        )
        self._check_protein_adequacy(diet_data, anamnese, target_calories)
        self._validate_macro_ratios(diet_data, anamnese, target_calories)

        # ── Substituições inteligentes (determinístico — backend, sem IA) ──────
        diet_data['substitutions'] = substitutions_for_plan(
            diet_data.get('meals', []), anamnese
        )
        logger.info(
            '[SUBSTITUTIONS] %d substituições geradas para usuário %s.',
            len(diet_data['substitutions']), anamnese.user_id,
        )

        # ── Passos 2 e 3 em paralelo (independentes entre si) ────────────────
        # Notas e explicação dependem apenas do diet_data do Passo 1 — não há
        # dependência entre elas, então rodam simultaneamente em threads separadas.
        logger.info('Passos 2 e 3 — gerando notas e explicação em paralelo (usuário %s)...', anamnese.user_id)
        notes: dict | None = None
        explanation: dict | None = None

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_notes = executor.submit(
                self._generate_notes, diet_data, anamnese, target_calories
            )
            fut_explanation = executor.submit(
                self._generate_explanation, diet_data, anamnese, tmb, tdee, target_calories
            )
            for fut in as_completed([fut_notes, fut_explanation]):
                try:
                    result = fut.result()
                    if fut is fut_notes:
                        notes = result
                    else:
                        explanation = result
                except Exception as exc:
                    logger.warning('Falha em chamada paralela à IA (não crítico): %s', exc)

        if isinstance(notes, dict):
            if notes.get('notes'):
                diet_data['notes'] = notes['notes']
            meal_notes_map = notes.get('meal_notes', {})
            for i, meal in enumerate(diet_data.get('meals', [])):
                note = meal_notes_map.get(i)
                if note:
                    meal['meal_notes'] = note
        diet_data['explanation'] = explanation

        # Sinaliza ajustes de segurança na meta (piso mínimo, teto, déficit anulado)
        diet_data['energy_plan'] = {
            'target_calories':  target_calories,
            'tdee':             tdee,
            'effective_goal':   energy['effective_goal'],
            'adjustment_kcal':  energy['adjustment_kcal'],
            'adjustment_label': energy['adjustment_label'],
        }
        diet_data['calorie_warnings'] = energy['warnings']

        # ── Persiste DietPlan ─────────────────────────────────────────────────
        diet_plan = DietPlan.objects.create(
            user=anamnese.user,
            anamnese=anamnese,
            raw_response=diet_data,
            total_calories=diet_data.get('calories'),
            goal_description=diet_data.get('goal_description', ''),
        )

        # ── Persiste Meals ────────────────────────────────────────────────────
        meals_to_create = []
        for idx, meal in enumerate(diet_data.get('meals', [])):
            foods = meal.get('foods', [])

            food_lines = [
                f'• {f.get("name", "")} — {f.get("quantity", f.get("quantity_text", ""))}'
                for f in foods if f.get('name')
            ]
            description = '\n'.join(food_lines) if food_lines else ', '.join(
                f.get('name', '') for f in foods
            )

            meal_kcal = sum(f.get('calories', 0) for f in foods)

            meal_name = meal.get('name', f'Refeição {idx + 1}')
            time_suggestion = meal.get('time_suggestion', '')
            if time_suggestion:
                meal_name = f'{meal_name} ({time_suggestion})'

            meals_to_create.append(Meal(
                diet_plan=diet_plan,
                meal_name=meal_name,
                description=description,
                calories=meal_kcal,
                order=idx,
            ))

        Meal.objects.bulk_create(meals_to_create)

        logger.info(
            'DietPlan#%s criado: %d refeições, %d kcal (usuário %s)',
            diet_plan.pk, len(meals_to_create), diet_plan.total_calories, anamnese.user_id,
        )
        return diet_plan

    # ──────────────────────────────────────────────────────────────────────────
    #  REGENERAÇÃO PONTUAL DE REFEIÇÃO
    # ──────────────────────────────────────────────────────────────────────────

    def _check_regenerated_plan_ratios(self, diet_plan: DietPlan, meal_index: int, new_meal: dict) -> None:
        anamnese = diet_plan.anamnese
        meals = (diet_plan.raw_response or {}).get('meals', [])
        _, _, target_calories = calculate_calories(anamnese)

        old_plan = self._recalculate_totals({'meals': list(meals)})
        if self._macro_ratio_violations(old_plan, anamnese, target_calories):
            return
        new_meals = list(meals)
        new_meals[meal_index] = new_meal
        new_plan = self._recalculate_totals({'meals': new_meals})
        self._validate_macro_ratios(new_plan, anamnese, target_calories)

    def regenerate_meal(
        self,
        diet_plan: DietPlan,
        meal_index: int,
        reason: str = '',
    ) -> dict:
        """
        Regenera uma refeição específica sem alterar as demais do plano.

        Fluxo (mesmas salvaguardas da geração completa):
          1. Monta prompt com contexto do plano completo e perfil do usuário
          2. Chama IA (temp=0.7 para variedade, max_tokens=800)
          3. Aplica alergias e restrições (fail-fast)
          4. Enriquece com macros do nutrition_db e checa cobertura
          5. Ajusta à meta calórica da refeição e DEPOIS arredonda
          6. Valida proporções de macros do plano inteiro (quando aplicável)
          7. Retorna dict com os dados da nova refeição (não persiste — a view persiste)

        Returns dict com:
          new_raw_meal     — meal dict enriquecido para raw_response['meals'][meal_index]
          new_description  — string de bullet points para Meal.description
          new_calories     — int para Meal.calories
          new_meal_name    — str com horário para Meal.meal_name
        """
        raw = diet_plan.raw_response or {}
        meals = raw.get('meals', [])

        if not (0 <= meal_index < len(meals)):
            raise ValueError(f'Índice de refeição inválido: {meal_index}')

        if not diet_plan.anamnese_id:
            raise ValueError('DietPlan sem anamnese associada — não é possível regenerar.')

        current_meal = meals[meal_index]
        prompt = build_meal_regen_prompt(diet_plan, meal_index, reason)

        logger.info(
            'Regenerando refeição %d ("%s") do DietPlan#%s (usuário %s)...',
            meal_index,
            current_meal.get('name', '?'),
            diet_plan.pk,
            diet_plan.user_id,
        )

        raw_response = self._call_api(
            prompt,
            system_prompt=SYSTEM_PROMPT_MEAL_REGEN,
            temperature=0.7,
            json_mode=True,
            max_tokens=800,  # JSON compacto de uma refeição + meal_notes
        )

        new_meal_data = self._parse_response(raw_response)

        if not new_meal_data.get('foods'):
            raise TransientAIError('A IA não retornou alimentos válidos para a refeição.')
        _validate_plan_structure(new_meal_data, single_meal=True)

        # Preserva nome e horário caso a IA omita ou altere
        new_meal_data.setdefault('name', current_meal.get('name', f'Refeição {meal_index + 1}'))
        new_meal_data.setdefault('time_suggestion', current_meal.get('time_suggestion', ''))

        # Enforcement de alergias e restrições antes de enriquecer (fail-fast)
        self._enforce_allergies({'meals': [new_meal_data]}, diet_plan.anamnese)
        self._enforce_restrictions({'meals': [new_meal_data]}, diet_plan.anamnese)

        # Enriquece com macros do banco nutricional (determinístico)
        enriched, db_stats = self._enrich_foods_with_macros({'meals': [new_meal_data]})
        # Rejeita refeição com cobertura insuficiente — usuário pode tentar de novo manualmente
        self._check_db_coverage(db_stats, diet_plan.anamnese)
        enriched = self._recalculate_totals(enriched)

        # Ajusta calorias da refeição ao alvo original (±10%) e SÓ DEPOIS
        # arredonda — mesma ordem da geração completa (_fit_portions).
        meal_calorie_target = sum(
            f.get('calories', 0) for f in current_meal.get('foods', [])
        )
        if meal_calorie_target > 0:
            enriched = self._fit_portions(enriched, meal_calorie_target)
        else:
            enriched = self._round_portions(enriched)

        # Proporções de macros do plano inteiro com a nova refeição. Só rejeita
        # se o plano atual estava dentro dos limites ("quando aplicável") —
        # planos antigos já fora dos limites não bloqueiam a regeneração.
        self._check_regenerated_plan_ratios(diet_plan, meal_index, enriched['meals'][0])

        new_meal = enriched['meals'][0]

        foods = new_meal.get('foods', [])
        food_lines = [
            f'• {f.get("name", "")} — {f.get("quantity", f.get("quantity_text", ""))}'
            for f in foods if f.get('name')
        ]
        new_description = '\n'.join(food_lines) if food_lines else ', '.join(
            f.get('name', '') for f in foods
        )
        new_calories = sum(f.get('calories', 0) for f in foods)

        meal_name = new_meal.get('name', f'Refeição {meal_index + 1}')
        time_suggestion = new_meal.get('time_suggestion', '')
        new_meal_name = f'{meal_name} ({time_suggestion})' if time_suggestion else meal_name

        logger.info(
            'Refeição %d regenerada: %d kcal, %d alimentos (DietPlan#%s)',
            meal_index, new_calories, len(foods), diet_plan.pk,
        )

        return {
            'new_raw_meal':    new_meal,
            'new_description': new_description,
            'new_calories':    new_calories,
            'new_meal_name':   new_meal_name,
        }
