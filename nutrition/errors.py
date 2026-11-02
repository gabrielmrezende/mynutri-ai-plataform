"""
Hierarquia de exceções da geração de dieta.

TransientAIError → a task do Celery faz retry; PermanentAIError → falha
reportada ao usuário. As mensagens são em português e não contêm detalhes
internos (URL, chave, corpo de resposta) — podem ser exibidas ao usuário.
"""


class DietGenerationError(Exception):
    """Base para todos os erros de geração de dieta."""
    pass


class TransientAIError(DietGenerationError):
    """
    Erro transitório — a task Celery deve fazer retry.

    Indica que a falha pode ser resolvida tentando novamente:
    resposta mal formatada da IA, cobertura nutricional insuficiente,
    alérgeno detectado (a IA pode escolher outros alimentos), ou
    desequilíbrio de macros (a IA pode montar um plano melhor).
    """
    pass


class PermanentAIError(DietGenerationError):
    """
    Erro permanente — retry não resolve, falha deve ser reportada ao usuário.

    Indica problema de configuração ou dado inválido:
    chave de API ausente, anamnese corrompida, etc.
    """
    pass


class AllergenViolation(TransientAIError):
    """Plano gerado contém alimento que viola alergias declaradas."""
    pass


class NutritionDataGap(TransientAIError):
    """
    Muitos alimentos do plano caem no fallback genérico do nutrition_db
    (150 kcal/100g) — o cálculo calórico fica pouco confiável.
    """
    pass


class MacroImbalanceError(TransientAIError):
    """
    Proporções de macronutrientes fora dos limites fisiologicamente razoáveis.

    Exemplos: carboidratos > 65% das calorias, proteína < 65% da meta,
    gordura < 15% das calorias.
    """
    pass


class RestrictionViolation(AllergenViolation):
    """
    Plano gerado contém alimento que viola restrição alimentar declarada
    (vegetariano, vegano, sem lactose, sem glúten...). Subclasse de
    AllergenViolation para herdar o mesmo tratamento de retry.
    """
    pass
