from .models import Anamnese, DietPlan, Meal
from rest_framework import serializers


class AnamneseSerializer(serializers.ModelSerializer):
    """
    Serializer para criação da Anamnese nutricional.
    Endpoint: POST /api/anamnese
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
