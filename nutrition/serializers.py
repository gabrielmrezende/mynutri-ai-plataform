import re
import unicodedata

from .models import Anamnese, DietPlan, Meal
from rest_framework import serializers


MAX_TEXT_LENGTH = 500

# Caracteres de controle Unicode que são invisíveis mas podem escapar regex simples
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\ufeff]')

# Padrões de injeção de prompt — avaliados APÓS normalização Unicode (NFKC)
# Cobre variações comuns de bypass: espaços extras, sinônimos, idiomas, delimitadores
_INJECTION_PATTERNS = [
    # Tentativas diretas de sobreescrever instruções
    r'(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|context|rules?|prompts?)',
    r'(?i)(forget|disregard|override|bypass|reset)\s+(all\s+)?(previous|above|prior|your)',
    r'(?i)new\s+(instructions?|rules?|prompt|task)\s*[:\-]',
    r'(?i)you\s+(are\s+now|must\s+now|should\s+now|will\s+now)',
    r'(?i)act\s+as\s+(a\s+)?(new|different|another|unrestricted)',

    # Tentativas de injeção de role/sistema
    r'(?i)(^|\n)\s*system\s*:',
    r'(?i)(^|\n)\s*(user|assistant|human|ai|bot|gpt|claude)\s*:',
    r'(?i)<\s*(system|instruction|prompt|context|rule)\s*>',

    # Delimitadores de separação de contexto (técnica de "context break")
    r'[-=_*#]{6,}',        # ex: ------  ======  ######
    r'\[INST\]|\[/INST\]', # LLaMA instruction tags
    r'<\|im_start\|>|<\|im_end\|>',  # ChatML tags (GPT-4)
    r'<<SYS>>|<</SYS>>',   # LLaMA system tags

    # Tentativas de exfiltração / execução
    r'(?i)(print|output|reveal|show|return|display)\s+(your\s+)?(system\s+)?(prompt|instructions?|rules?|context)',
    r'(?i)what\s+(are\s+)?your\s+(instructions?|rules?|system\s+prompt)',

    # Português — variações locais
    r'(?i)ignore\s+(todas?\s+as?\s+)?(instruções|regras|contexto)\s*(anteriores?|acima)',
    r'(?i)(esqueça|ignore|descarte|substitua)\s+(todas?\s+as?\s+)?(instruções|regras)\s*(anteriores?|acima)',
    r'(?i)novas?\s+instruções?\s*[:\-]',
    r'(?i)você\s+(agora\s+)?(é|deve\s+ser|vai\s+ser)\s+(um|uma)',
]

_COMPILED_PATTERNS = [re.compile(p) for p in _INJECTION_PATTERNS]


def _normalize(text: str) -> str:
    """
    Normaliza o texto antes da varredura de injeção:
    1. NFKC colapsa caracteres Unicode equivalentes (ex: ｉ → i, ＳＹＳＴＥＭsystem)
    2. Remove caracteres de controle invisíveis usados como bypass
    3. Colapsa espaços duplicados para que padrões com \s+ funcionem corretamente
    """
    text = unicodedata.normalize('NFKC', text)
    text = _CONTROL_CHARS_RE.sub('', text)
    text = re.sub(r' {2,}', ' ', text)
    return text


def validate_free_text(value, field_name):
    """
    Valida campos de texto livre contra prompt injection e tamanho excessivo.

    Proteções em camadas:
    1. Limite de comprimento
    2. Remoção de caracteres de controle invisíveis
    3. Normalização Unicode (NFKC) antes da varredura — previne bypass com homoglifos
    4. Varredura com 20+ padrões cobrindo inglês, português e técnicas de delimiter injection
    5. Detecção de anomalias: razão anormal de caracteres especiais
    """
    if len(value) > MAX_TEXT_LENGTH:
        raise serializers.ValidationError(
            f'{field_name} não pode exceder {MAX_TEXT_LENGTH} caracteres.'
        )

    if not value.strip():
        return value

    normalized = _normalize(value)

    # Detecção de anomalia: texto legítimo raramente tem >30% de caracteres não-alfanuméricos
    # (exclui espaços da contagem para não penalizar frases normais)
    non_space = normalized.replace(' ', '')
    if non_space:
        special_ratio = sum(1 for c in non_space if not (c.isalnum() or c in '.,;:!?-\'\"()')) / len(non_space)
        if special_ratio > 0.35:
            raise serializers.ValidationError(
                f'{field_name} contém conteúdo não permitido.'
            )

    for pattern in _COMPILED_PATTERNS:
        if pattern.search(normalized):
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
    peso = serializers.DecimalField(source='weight_kg', max_digits=5, decimal_places=2, min_value=10, max_value=500)
    altura = serializers.DecimalField(source='height_cm', max_digits=5, decimal_places=2, min_value=50, max_value=280)
    meals_per_day = serializers.IntegerField(min_value=1, max_value=12, default=3, required=False)

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

    def validate(self, data):
        peso = data.get('weight_kg')
        altura = data.get('height_cm')
        if peso is not None and altura is not None:
            altura_m = float(altura) / 100
            bmi = float(peso) / (altura_m ** 2)
            if bmi < 10 or bmi > 70:
                raise serializers.ValidationError(
                    'A combinação de peso e altura não é fisiologicamente plausível.'
                )
        return data


class MealSerializer(serializers.ModelSerializer):
    """Serializer para cada refeição individual. Usado aninhado no DietPlanSerializer."""
    nome_refeicao = serializers.CharField(source='meal_name')
    descricao_refeicao = serializers.CharField(source='description')
    calorias_estimadas = serializers.IntegerField(source='calories')

    class Meta:
        model = Meal
        fields = ('id', 'nome_refeicao', 'descricao_refeicao', 'calorias_estimadas', 'order')


class DietPlanSummarySerializer(serializers.ModelSerializer):
    """
    Serializer compacto para listagem do histórico.
    Endpoint: GET /api/v1/diet/list
    Não inclui refeições detalhadas — apenas dados suficientes para a listagem.
    """
    calorias_totais = serializers.IntegerField(source='total_calories')
    macros = serializers.SerializerMethodField()

    class Meta:
        model = DietPlan
        fields = ('id', 'calorias_totais', 'goal_description', 'macros', 'created_at')
        read_only_fields = fields

    def get_macros(self, obj):
        return obj.raw_response.get('macros') if obj.raw_response else None


class DietPlanSerializer(serializers.ModelSerializer):
    """
    Serializer completo do Plano Alimentar com refeições aninhadas.
    Endpoint: GET /api/diet
    """
    refeicoes = MealSerializer(source='meals', many=True, read_only=True)
    calorias_totais = serializers.IntegerField(source='total_calories')
    macros = serializers.SerializerMethodField()
    substitutions = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()
    meals_raw = serializers.SerializerMethodField()
    explanation = serializers.SerializerMethodField()

    class Meta:
        model = DietPlan
        fields = (
            'id', 'calorias_totais', 'goal_description',
            'macros', 'substitutions', 'notes',
            'meals_raw', 'refeicoes', 'explanation', 'created_at',
        )
        read_only_fields = fields

    def get_macros(self, obj):
        return obj.raw_response.get('macros') if obj.raw_response else None

    def get_substitutions(self, obj):
        return obj.raw_response.get('substitutions', []) if obj.raw_response else []

    def get_notes(self, obj):
        return obj.raw_response.get('notes', '') if obj.raw_response else ''

    def get_meals_raw(self, obj):
        """Retorna as refeições com foods[] estruturados diretamente do JSON da IA."""
        return obj.raw_response.get('meals', []) if obj.raw_response else []

    def get_explanation(self, obj):
        """Retorna a explicação de transparência gerada pela IA."""
        return obj.raw_response.get('explanation') if obj.raw_response else None
