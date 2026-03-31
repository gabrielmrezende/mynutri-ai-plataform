import re

from .models import Anamnese, DietPlan, Meal
from rest_framework import serializers


MAX_TEXT_LENGTH = 500


def validate_free_text(value, field_name):
    """Valida campos de texto livre contra prompt injection e tamanho excessivo."""
    if len(value) > MAX_TEXT_LENGTH:
        raise serializers.ValidationError(
            f'{field_name} não pode exceder {MAX_TEXT_LENGTH} caracteres.'
        )
    # Rejeitar padrões que tentam manipular instruções da IA
    injection_patterns = [
        r'(?i)ignore\s+(all\s+)?previous\s+instructions',
        r'(?i)ignore\s+(all\s+)?above',
        r'(?i)system\s*:',
        r'(?i)you\s+are\s+now',
        r'(?i)new\s+instructions?\s*:',
        r'(?i)forget\s+(all\s+)?previous',
        r'(?i)disregard\s+(all\s+)?',
    ]
    for pattern in injection_patterns:
        if re.search(pattern, value):
            raise serializers.ValidationError(
                f'{field_name} contém conteúdo não permitido.'
            )
    return value


class AnamneseSerializer(serializers.ModelSerializer):
    """
    Serializer para criação da Anamnese nutricional.
    Endpoint: POST /api/v1/anamnese
    Mapeia os campos do body documentado em API.md para o model Anamnese.
    """
    # Remapeia o campo 'restricoes' do API.md para 'food_restrictions' do model
    restricoes = serializers.CharField(
        source='food_restrictions', required=False, allow_blank=True, default=''
    )
    nivel_atividade = serializers.ChoiceField(
        source='activity_level', choices=Anamnese.ACTIVITY_LEVEL_CHOICES
    )
    objetivo = serializers.ChoiceField(
        source='goal', choices=Anamnese.GOAL_CHOICES
    )
    idade = serializers.IntegerField(source='age', min_value=1, max_value=120)
    sexo = serializers.ChoiceField(source='gender', choices=Anamnese.GENDER_CHOICES)
    peso = serializers.DecimalField(source='weight_kg', max_digits=5, decimal_places=2)
    altura = serializers.DecimalField(source='height_cm', max_digits=5, decimal_places=2)

    class Meta:
        model = Anamnese
        fields = (
            'id', 'idade', 'sexo', 'peso', 'altura',
            'nivel_atividade', 'objetivo', 'restricoes',
            'food_preferences', 'allergies', 'meals_per_day',
            'answered_at',
        )
        read_only_fields = ('id', 'answered_at')

    def validate_restricoes(self, value):
        return validate_free_text(value, 'Restrições alimentares')

    def validate_food_preferences(self, value):
        return validate_free_text(value, 'Preferências alimentares')

    def validate_allergies(self, value):
        return validate_free_text(value, 'Alergias')


class MealSerializer(serializers.ModelSerializer):
    """Serializer para cada refeição individual. Usado aninhado no DietPlanSerializer."""
    nome_refeicao = serializers.CharField(source='meal_name')
    descricao_refeicao = serializers.CharField(source='description')
    calorias_estimadas = serializers.IntegerField(source='calories')

    class Meta:
        model = Meal
        fields = ('nome_refeicao', 'descricao_refeicao', 'calorias_estimadas', 'order')


class DietPlanSerializer(serializers.ModelSerializer):
    """
    Serializer completo do Plano Alimentar com refeições aninhadas.
    Endpoint: GET /api/diet
    """
    refeicoes = MealSerializer(source='meals', many=True, read_only=True)
    calorias_totais = serializers.IntegerField(source='total_calories')

    class Meta:
        model = DietPlan
        fields = (
            'id', 'calorias_totais', 'goal_description',
            'refeicoes', 'created_at',
        )
        read_only_fields = fields
