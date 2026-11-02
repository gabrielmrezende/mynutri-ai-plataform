import logging
from datetime import datetime, time

from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from rest_framework import status, serializers as drf_serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from user.models import Profile

from .authentication import RequireCSRFHeader
from .forms import ContatoForm
from .models import Testimonial
from .serializers import (
    RegisterSerializer, UserProfileSerializer, UpdateProfileSerializer,
    TestimonialReadSerializer, TestimonialCreateSerializer,
)

logger = logging.getLogger(__name__)

User = get_user_model()


# =============================================================================
# Cookie helpers
# =============================================================================

def _set_auth_cookies(response, access_token, refresh_token):
    """Define os cookies HttpOnly para access e refresh tokens."""
    secure = not settings.DEBUG
    response.set_cookie(
        'mynutri_access',
        str(access_token),
        max_age=8 * 3600,       # 8 horas — igual ao ACCESS_TOKEN_LIFETIME
        httponly=True,
        secure=secure,
        samesite='Lax',
        path='/',
    )
    response.set_cookie(
        'mynutri_refresh',
        str(refresh_token),
        max_age=7 * 24 * 3600,  # 7 dias — igual ao REFRESH_TOKEN_LIFETIME
        httponly=True,
        secure=secure,
        samesite='Lax',
        path='/',
    )


def _clear_auth_cookies(response):
    """Remove os cookies de autenticação (logout)."""
    response.delete_cookie('mynutri_access', path='/')
    response.delete_cookie('mynutri_refresh', path='/')


def _user_payload(user):
    """Dados públicos do usuário devolvidos em login/registro/Google."""
    return {
        'id': user.id,
        'email': user.email,
        'nome': user.get_full_name() or user.first_name or user.email,
    }


def _attach_new_session(response, user):
    """Emite um novo par JWT (registrado em OutstandingToken) e grava nos cookies."""
    refresh = RefreshToken.for_user(user)
    _set_auth_cookies(response, refresh.access_token, refresh)
    return response


def _login_response(user, status_code=status.HTTP_200_OK):
    """
    Autentica o usuário e devolve só os dados públicos dele.
    Os tokens vão exclusivamente em cookies HttpOnly — nunca no JSON —
    para não ficarem expostos a JavaScript (XSS).
    """
    return _attach_new_session(Response({'user': _user_payload(user)}, status=status_code), user)


def _revoke_all_refresh_tokens(user):
    """
    Blacklista todos os refresh tokens emitidos para o usuário — derruba
    as sessões em todos os dispositivos (troca de senha, exclusão de conta,
    vínculo com Google). Access tokens já emitidos expiram sozinhos.
    """
    pending = OutstandingToken.objects.filter(user=user).exclude(
        id__in=BlacklistedToken.objects.filter(token__user=user).values('token_id')
    )
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in pending],
        ignore_conflicts=True,
    )


def _blacklist_refresh_cookie(request):
    """Blacklista o refresh token do cookie da requisição, se válido."""
    raw = request.COOKIES.get('mynutri_refresh')
    if not raw:
        return
    try:
        RefreshToken(raw).blacklist()
    except TokenError:
        pass  # expirado/inválido/já revogado — nada a fazer


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Substitui o campo 'username' por 'email' na autenticação JWT.
    Como o sistema usa username=email internamente, apenas renomeamos o campo.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'] = drf_serializers.EmailField()
        del self.fields[self.username_field]

    def validate(self, attrs):
        attrs[self.username_field] = attrs.pop('email', '').strip().lower()
        return super().validate(attrs)


class LoginThrottle(AnonRateThrottle):
    """5 tentativas de login por 10 minutos por IP — previne brute force."""
    scope = 'login'

    def parse_rate(self, rate):
        # DRF doesn't support multi-minute periods; hardcode 5 per 10 minutes
        return (5, 600)


class EmailTokenObtainPairView(TokenObtainPairView):
    """
    POST /api/v1/auth/login
    Aceita { email, password }, seta os cookies HttpOnly e retorna { user }.
    O campo 'user' é incluído para que o frontend possa salvar os dados
    do usuário sem precisar de uma chamada adicional.
    """
    serializer_class = EmailTokenObtainPairSerializer
    throttle_classes = [LoginThrottle]
    permission_classes = [RequireCSRFHeader]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0])

        # O serializer já carregou o usuário e emitiu o par de tokens — sem query extra
        response = Response({'user': _user_payload(serializer.user)})
        _set_auth_cookies(
            response,
            serializer.validated_data['access'],
            serializer.validated_data['refresh'],
        )
        return response


class RegisterAPIView(APIView):
    """
    POST /api/v1/auth/register
    Cria uma nova conta e já autentica o usuário via cookies HttpOnly.
    Exige accepted_terms=true (aceite dos Termos de Uso).
    """
    permission_classes = [RequireCSRFHeader]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = serializer.save()
        except IntegrityError:
            # Corrida entre dois cadastros com o mesmo e-mail (constraint case-insensitive)
            return Response(
                {'email': ['Este e-mail já está em uso.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info('New user registered — user_id=%d', user.id)
        return _login_response(user, status_code=status.HTTP_201_CREATED)


class ContactThrottle(AnonRateThrottle):
    """5 envios por hora por IP — protege contra spam no formulário de contato."""
    scope = 'contact'


class ContactAPIView(APIView):
    """
    POST /api/v1/contact
    Recebe o formulário de contato, valida e envia e-mail para mynutriai.app@gmail.com.
    Aberto ao público (AllowAny), com rate-limit de 5/hora por IP.
    """
    permission_classes = [AllowAny]
    throttle_classes = [ContactThrottle]

    def post(self, request):
        form = ContatoForm(request.data)
        if not form.is_valid():
            return Response({'errors': form.errors}, status=status.HTTP_400_BAD_REQUEST)

        data = form.cleaned_data
        nome     = data['nome']
        email    = data['email']
        assunto  = data['assunto']
        mensagem = data['mensagem']

        body_lines = []

        # Inclui info do usuário autenticado (se logado)
        if request.user.is_authenticated:
            body_lines += [
                f'[Usuário autenticado: {request.user.email} — ID {request.user.id}]',
                '',
            ]

        body_lines += [
            f'Nome: {nome}',
            f'E-mail: {email}',
            f'Assunto: {assunto}',
            '',
            'Mensagem:',
            mensagem,
        ]

        try:
            send_mail(
                subject=f'[MyNutri AI - Contato] {assunto}',
                message='\n'.join(body_lines),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.CONTACT_EMAIL],
                fail_silently=False,
            )
            logger.info('Contact email sent — authenticated=%s', request.user.is_authenticated)
        except Exception as exc:
            logger.error('Contact email failed — %s', type(exc).__name__, exc_info=True)
            return Response(
                {'error': 'Não foi possível enviar sua mensagem. Tente novamente mais tarde.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({'message': 'Mensagem enviada com sucesso.'}, status=status.HTTP_200_OK)


# =============================================================================
# Google OAuth
# =============================================================================

class GoogleTokenError(Exception):
    """Falha na validação do id_token Google. `code` vai na URL de erro do redirect."""

    def __init__(self, code, message, http_status=status.HTTP_401_UNAUTHORIZED):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# Sessão HTTP reaproveitada para buscar os certificados públicos do Google
_google_request = google_requests.Request()


def _verify_google_credential(credential):
    """
    Valida o id_token localmente: assinatura (certificados do Google), expiração,
    'aud' == GOOGLE_CLIENT_ID e 'iss' == accounts.google.com. Exige e-mail verificado.
    Retorna os claims do token ou levanta GoogleTokenError.
    """
    try:
        claims = google_id_token.verify_oauth2_token(
            credential, _google_request, settings.GOOGLE_CLIENT_ID,
        )
    except google_exceptions.TransportError as exc:
        logger.error('Google certs fetch failed — %s', type(exc).__name__)
        raise GoogleTokenError(
            'service_unavailable', 'Não foi possível validar o token Google.',
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except (ValueError, google_exceptions.GoogleAuthError):
        # Assinatura inválida, expirado, aud/iss incorretos, formato inválido
        raise GoogleTokenError('invalid_token', 'Token Google inválido ou expirado.')

    email = (claims.get('email') or '').strip().lower()
    if not email:
        raise GoogleTokenError(
            'no_email', 'E-mail não retornado pelo Google.', status.HTTP_400_BAD_REQUEST,
        )

    # email_verified pode vir como bool ou string dependendo do emissor
    if claims.get('email_verified') not in (True, 'true'):
        raise GoogleTokenError('unverified_email', 'O e-mail da conta Google não foi verificado.')

    claims['email'] = email
    return claims


def _get_or_create_google_user(claims):
    """
    Busca a conta pelo e-mail (case-insensitive) ou cria uma nova sem senha.

    Proteção contra pré-sequestro: se a conta já existia com senha utilizável,
    quem a criou pode não ser o dono do e-mail (ninguém verificou a caixa no
    cadastro). Como o Google comprovou a posse do e-mail, a senha antiga é
    invalidada e todas as sessões abertas são revogadas.
    """
    email = claims['email']
    user = User.objects.filter(email__iexact=email).first()

    if user is None:
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=None,  # senha inutilizável — login só via Google
                    first_name=claims.get('given_name', ''),
                    last_name=claims.get('family_name', ''),
                )
                Profile.objects.get_or_create(user=user)
            logger.info('New user created via Google OAuth — user_id=%d', user.id)
            return user
        except IntegrityError:
            # Corrida com outro login/cadastro do mesmo e-mail
            user = User.objects.get(email__iexact=email)

    if user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=['password'])
        _revoke_all_refresh_tokens(user)
        logger.info(
            'Google OAuth linked to existing account — password invalidated, '
            'sessions revoked — user_id=%d', user.id,
        )

    return user


class GoogleAuthAPIView(APIView):
    """
    POST /api/v1/auth/google
    Recebe { id_token } do Google Sign-In, valida localmente (assinatura, aud,
    iss, email_verified), seta os cookies HttpOnly e retorna { user }.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        id_token = request.data.get('id_token')
        if not id_token or not isinstance(id_token, str):
            return Response({'error': 'id_token é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            claims = _verify_google_credential(id_token)
        except GoogleTokenError as exc:
            return Response({'error': exc.message}, status=exc.http_status)

        user = _get_or_create_google_user(claims)
        if not user.is_active:
            return Response({'error': 'Conta desativada.'}, status=status.HTTP_403_FORBIDDEN)

        return _login_response(user)


@method_decorator(csrf_exempt, name='dispatch')
class GoogleOAuthCallbackView(APIView):
    """
    POST /api/v1/auth/google/callback
    Recebe { credential, g_csrf_token } do Google Sign-In no modo redirect.
    Google envia um POST form-encoded após autenticação; esta view valida o
    double-submit CSRF do Google, processa o credential e redireciona para /dieta/.
    Usa @csrf_exempt porque o CSRF aqui é gerenciado pelo próprio Google.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        credential = request.POST.get('credential') or request.data.get('credential', '')
        g_csrf_body = request.POST.get('g_csrf_token') or request.data.get('g_csrf_token', '')
        g_csrf_cookie = request.COOKIES.get('g_csrf_token', '')

        if not g_csrf_body or not g_csrf_cookie or not constant_time_compare(g_csrf_body, g_csrf_cookie):
            # Não loga os valores do token — apenas o fato
            logger.warning('Google OAuth callback: g_csrf_token mismatch')
            return HttpResponseRedirect('/auth/?google_error=csrf')

        if not credential or not isinstance(credential, str):
            return HttpResponseRedirect('/auth/?google_error=no_credential')

        try:
            claims = _verify_google_credential(credential)
        except GoogleTokenError as exc:
            return HttpResponseRedirect(f'/auth/?google_error={exc.code}')

        user = _get_or_create_google_user(claims)
        if not user.is_active:
            return HttpResponseRedirect('/auth/?google_error=inactive')

        return _attach_new_session(HttpResponseRedirect('/dieta/'), user)


class LogoutAPIView(APIView):
    """
    POST /api/v1/auth/logout
    Revoga o refresh token do cookie (blacklist) e remove os cookies HttpOnly.
    Público (cookie pode estar expirado), mas exige X-Requested-With (anti-CSRF).
    """
    permission_classes = [RequireCSRFHeader]
    authentication_classes = []

    def post(self, request):
        _blacklist_refresh_cookie(request)
        response = Response({'message': 'Logout realizado com sucesso.'})
        _clear_auth_cookies(response)
        return response


class CookieTokenRefreshView(APIView):
    """
    POST /api/v1/auth/token/refresh
    Lê o refresh token exclusivamente do cookie HttpOnly 'mynutri_refresh',
    rotaciona (o antigo vai para a blacklist) e atualiza os cookies.
    Não devolve tokens no corpo da resposta.
    """
    # Mantém as authentication_classes padrão: com elas o DRF responde 401
    # (e não 403) para refresh inválido, sinalizando ao frontend que deve relogar.
    permission_classes = [RequireCSRFHeader]

    def post(self, request):
        refresh_raw = request.COOKIES.get('mynutri_refresh')
        if not refresh_raw:
            return Response(
                {'detail': 'Refresh token não encontrado.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Valida assinatura/expiração e checa a blacklist
            old_refresh = RefreshToken(refresh_raw)
        except TokenError as exc:
            raise InvalidToken(exc.args[0])

        user_id = old_refresh.payload.get(jwt_settings.USER_ID_CLAIM)
        user = User.objects.filter(**{jwt_settings.USER_ID_FIELD: user_id}).first()
        if user is None or not jwt_settings.USER_AUTHENTICATION_RULE(user):
            raise InvalidToken('Usuário inexistente ou inativo.')

        # Rotação manual: blacklista o antigo e emite um novo par registrado em
        # OutstandingToken (o serializer padrão não registra o token rotacionado,
        # o que impediria revogá-lo depois em "derrubar todas as sessões").
        old_refresh.blacklist()
        new_refresh = RefreshToken.for_user(user)

        response = Response({'detail': 'Sessão renovada.'})
        _set_auth_cookies(response, new_refresh.access_token, new_refresh)
        return response


class TestimonialAPIView(APIView):
    """
    GET  /api/v1/testimonials  — lista os depoimentos aprovados (público)
    POST /api/v1/testimonials  — cria um novo depoimento (requer autenticação)
    Limite: 3 depoimentos por usuário por dia (dia no fuso local do projeto).
    """
    DAILY_LIMIT = 3

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get(self, request):
        qs = Testimonial.objects.filter(is_approved=True).select_related('user')[:30]
        serializer = TestimonialReadSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = TestimonialCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Início do dia no fuso do projeto (America/Sao_Paulo), não em UTC
        start_of_day = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))

        with transaction.atomic():
            # Trava a linha do usuário para serializar envios simultâneos —
            # contagem + criação viram uma operação atômica (sem estourar o limite)
            User.objects.select_for_update().filter(pk=request.user.pk).first()
            today_count = Testimonial.objects.filter(
                user=request.user,
                created_at__gte=start_of_day,
            ).count()
            if today_count >= self.DAILY_LIMIT:
                return Response(
                    {'error': 'Você já enviou 3 depoimentos hoje. Tente novamente amanhã.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            testimonial = serializer.save(user=request.user)

        logger.info('New testimonial — user_id=%d rating=%s', request.user.id, testimonial.rating)
        return Response(TestimonialReadSerializer(testimonial).data, status=status.HTTP_201_CREATED)


class ProfileAPIView(APIView):
    """
    GET  /api/v1/user/profile  — retorna dados do usuário autenticado (inclui has_password)
    PATCH /api/v1/user/profile  — atualiza first_name, last_name, phone, date_of_birth
    Requer autenticação (cookie HttpOnly ou Authorization: Bearer).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        serializer = UpdateProfileSerializer(
            request.user, data=request.data, partial=True
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(UserProfileSerializer(request.user).data, status=status.HTTP_200_OK)


class ChangePasswordAPIView(APIView):
    """
    POST /api/v1/user/change-password
    Altera a senha do usuário autenticado.
    Body: { current_password, new_password }
    Revoga todas as sessões (refresh tokens) e reemite cookies para a sessão atual.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle, ScopedRateThrottle]
    throttle_scope = 'change_password'

    def post(self, request):
        user = request.user

        if not user.has_usable_password():
            return Response(
                {'error': 'Sua conta usa login com Google e não possui senha. '
                          'Continue entrando com o Google.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        current_password = request.data.get('current_password', '')
        new_password = request.data.get('new_password', '')

        if not current_password or not new_password:
            return Response(
                {'error': 'current_password e new_password são obrigatórios.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not user.check_password(current_password):
            return Response(
                {'error': 'Senha atual incorreta.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if current_password == new_password:
            return Response(
                {'error': 'A nova senha deve ser diferente da senha atual.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validadores do Django (AUTH_PASSWORD_VALIDATORS): tamanho mínimo,
        # senhas comuns, só numéricas, similaridade com nome/e-mail
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response(
                {'error': ' '.join(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=['password'])

        # Derruba as sessões de outros dispositivos e mantém a atual com tokens novos
        _revoke_all_refresh_tokens(user)
        logger.info('Password changed — sessions revoked — user_id=%d', user.id)

        response = Response({'message': 'Senha alterada com sucesso.'}, status=status.HTTP_200_OK)
        return _attach_new_session(response, user)


class DeleteAccountAPIView(APIView):
    """
    DELETE (ou POST) /api/v1/user/delete-account
    Exclui permanentemente a conta do usuário autenticado e todos os dados relacionados.
    Body:
      - conta com senha: { password }
      - conta sem senha (Google): { confirm: "EXCLUIR" }
    Revoga os refresh tokens e limpa os cookies de autenticação.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle, ScopedRateThrottle]
    throttle_scope = 'delete_account'

    CONFIRM_WORD = 'EXCLUIR'

    def delete(self, request):
        user = request.user

        if user.has_usable_password():
            password = request.data.get('password', '')
            if not password:
                return Response(
                    {'error': 'A senha é obrigatória para confirmar a exclusão da conta.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not user.check_password(password):
                return Response(
                    {'error': 'Senha incorreta. Não foi possível excluir a conta.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            if request.data.get('confirm') != self.CONFIRM_WORD:
                return Response(
                    {'error': f'Digite {self.CONFIRM_WORD} para confirmar a exclusão da conta.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        user_id = user.id
        with transaction.atomic():
            _revoke_all_refresh_tokens(user)
            user.delete()
        logger.info('Account permanently deleted — user_id=%d', user_id)

        response = Response({'message': 'Conta excluída com sucesso.'}, status=status.HTTP_200_OK)
        _clear_auth_cookies(response)
        return response

    def post(self, request):
        # Alguns clientes/proxies descartam corpo em DELETE — POST é equivalente
        return self.delete(request)
