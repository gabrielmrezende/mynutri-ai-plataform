import logging
import unicodedata

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from user.email_validation import validate_email_full
from user.models import Profile, Testimonial

logger = logging.getLogger(__name__)

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    """
    Serializer para criação de conta.
    Endpoint: POST /api/v1/auth/register
    Campos esperados: nome (first_name), email, senha (password), accepted_terms (true)
    """
    nome = serializers.CharField(write_only=True)
    email = serializers.EmailField(write_only=True)
    senha = serializers.CharField(write_only=True, min_length=8)
    accepted_terms = serializers.BooleanField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ('nome', 'email', 'senha', 'accepted_terms')

    def validate_accepted_terms(self, value):
        if value is not True:
            raise serializers.ValidationError(
                'É necessário aceitar os Termos de Uso e a Política de Privacidade.'
            )
        return value

    def validate_email(self, value):
        """
        Validação de e-mail em múltiplas camadas:
          1. Unicidade no banco (case-insensitive)
          2. Formato (EmailField já garante, reforçado pelo serviço)
          3. DNS/MX — verifica se o domínio aceita e-mails
          4. API externa (se configurada) — verifica existência da caixa
        """
        email = value.strip().lower()

        # — Unicidade (iexact cobre registros antigos gravados com maiúsculas)
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError('Este e-mail já está em uso.')

        # — Validação em camadas (formato → DNS → API → SMTP)
        result = validate_email_full(email)
        if not result.is_valid:
            logger.info(
                'Cadastro rejeitado — e-mail inválido domínio=%s camada=%s',
                email.rsplit('@', 1)[-1], result.layer,
            )
            raise serializers.ValidationError(result.message)

        return email

    def validate(self, attrs):
        # Validadores de senha do Django (AUTH_PASSWORD_VALIDATORS): tamanho,
        # senhas comuns, só numéricas e similaridade com nome/e-mail.
        candidate = User(
            username=attrs.get('email', ''),
            email=attrs.get('email', ''),
            first_name=attrs.get('nome', ''),
        )
        try:
            validate_password(attrs.get('senha', ''), user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'senha': list(exc.messages)})
        return attrs

    def create(self, validated_data):
        """Cria o usuário usando os campos mapeados da documentação."""
        with transaction.atomic():
            user = User.objects.create_user(
                username=validated_data['email'],   # username = email para simplificar
                email=validated_data['email'],
                password=validated_data['senha'],
                first_name=validated_data['nome'],
            )
            # Registra a data de aceite dos Termos de Uso (LGPD)
            Profile.objects.update_or_create(
                user=user, defaults={'terms_accepted_at': timezone.now()},
            )
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serializer para leitura do perfil do usuário.
    Endpoint: GET /api/v1/user/profile
    """
    nome = serializers.SerializerMethodField()
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'nome', 'email', 'phone', 'date_of_birth', 'date_joined', 'has_password')

    def get_nome(self, obj):
        return obj.get_full_name() or obj.first_name or obj.email

    def get_has_password(self, obj):
        # False para contas criadas via Google (ou cuja senha foi invalidada no login Google)
        return obj.has_usable_password()


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


class TestimonialReadSerializer(serializers.ModelSerializer):
    """
    Serializer de leitura para depoimentos — expõe dados públicos.
    Endpoint: GET /api/v1/testimonials
    """
    nome = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = Testimonial
        fields = ('id', 'nome', 'avatar', 'text', 'rating', 'created_at')

    def get_nome(self, obj):
        return obj.user.get_full_name() or obj.user.first_name or obj.user.email

    def get_avatar(self, obj):
        name = self.get_nome(obj)
        parts = name.strip().split()
        return ''.join(p[0].upper() for p in parts[:2] if p)


class TestimonialCreateSerializer(serializers.ModelSerializer):
    """
    Serializer de escrita para criação de depoimentos.
    Endpoint: POST /api/v1/testimonials
    Sanitiza o texto para evitar XSS e injection.
    """
    class Meta:
        model = Testimonial
        fields = ('text', 'rating')

    def validate_text(self, value):
        # Normaliza unicode e remove caracteres de controle
        text = unicodedata.normalize('NFKC', value)
        text = ''.join(ch for ch in text if not unicodedata.category(ch).startswith('C'))
        text = text.strip()

        if not text:
            raise serializers.ValidationError('O depoimento não pode estar vazio.')
        if len(text) < 10:
            raise serializers.ValidationError('O depoimento deve ter pelo menos 10 caracteres.')
        if len(text) > 500:
            raise serializers.ValidationError('O depoimento deve ter no máximo 500 caracteres.')

        return text

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError('A nota deve ser entre 1 e 5.')
        return value
