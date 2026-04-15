import logging

from django.contrib.auth import get_user_model
from rest_framework import serializers

from user.email_validation import validate_email_full

logger = logging.getLogger(__name__)

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    """
    Serializer para criação de conta.
    Endpoint: POST /api/v1/auth/register
    Campos esperados: nome (first_name), email, senha (password)
    """
    nome = serializers.CharField(write_only=True)
    email = serializers.EmailField(write_only=True)
    senha = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ('nome', 'email', 'senha')

    def validate_email(self, value):
        """
        Validação de e-mail em múltiplas camadas:
          1. Unicidade no banco
          2. Formato (EmailField já garante, reforçado pelo serviço)
          3. DNS/MX — verifica se o domínio aceita e-mails
          4. API externa (se configurada) — verifica existência da caixa
        """
        email = value.strip().lower()

        # — Unicidade
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError('Este e-mail já está em uso.')

        # — Validação em camadas (formato → DNS → API → SMTP)
        result = validate_email_full(email)
        if not result.is_valid:
            logger.info(
                'Cadastro rejeitado — e-mail inválido [%s] camada=%s detalhe=%s',
                email, result.layer, result.details,
            )
            raise serializers.ValidationError(result.message)

        return email

    def create(self, validated_data):
        """Cria o usuário usando os campos mapeados da documentação."""
        user = User.objects.create_user(
            username=validated_data['email'],   # username = email para simplificar
            email=validated_data['email'],
            password=validated_data['senha'],
            first_name=validated_data['nome'],
        )
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serializer para leitura do perfil do usuário.
    Endpoint: GET /api/v1/user/profile
    """
    nome = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'nome', 'email', 'phone', 'date_of_birth', 'date_joined')

    def get_nome(self, obj):
        return obj.get_full_name() or obj.first_name or obj.email


class UpdateProfileSerializer(serializers.ModelSerializer):
    """
    Serializer para atualização parcial do perfil do usuário.
    Endpoint: PATCH /api/v1/user/profile
    Campos aceitos: first_name, last_name, phone, date_of_birth
    """
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'phone', 'date_of_birth')
        extra_kwargs = {
            'first_name': {'required': False},
            'last_name':  {'required': False},
            'phone':      {'required': False},
            'date_of_birth': {'required': False},
        }
