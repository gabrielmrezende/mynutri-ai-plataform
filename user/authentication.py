from rest_framework import exceptions
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


# Header exigido em requisições não seguras autenticadas por cookie (anti-CSRF).
# Formulários HTML cross-site não conseguem enviar headers customizados, e um
# fetch cross-origin com esse header dispara preflight CORS (bloqueado em produção).
CSRF_HEADER = 'HTTP_X_REQUESTED_WITH'
CSRF_HEADER_VALUE = 'XMLHttpRequest'
CSRF_ERROR_MESSAGE = 'Requisição bloqueada: header X-Requested-With ausente.'


def has_csrf_header(request):
    """True se a requisição traz 'X-Requested-With: XMLHttpRequest'."""
    return request.META.get(CSRF_HEADER, '') == CSRF_HEADER_VALUE


class CookieJWTAuthentication(JWTAuthentication):
    """
    Autentica usando o cookie HttpOnly 'mynutri_access'.
    Fallback automático para header 'Authorization: Bearer' (API clients e testes).

    Tokens inválidos/expirados no cookie são ignorados silenciosamente (retornam None)
    para não bloquear views públicas (AllowAny) quando o usuário tem cookie obsoleto.

    Proteção CSRF: cookies são enviados automaticamente pelo navegador, então
    métodos não seguros (POST/PUT/PATCH/DELETE) autenticados por cookie exigem
    o header X-Requested-With: XMLHttpRequest (senão 403). Bearer não exige.
    """

    def authenticate(self, request):
        # 1. Header Authorization presente → comportamento padrão do simplejwt
        if self.get_header(request):
            return super().authenticate(request)

        # 2. Cookie HttpOnly
        raw_token = request.COOKIES.get('mynutri_access')
        if not raw_token:
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
        except (InvalidToken, TokenError):
            # Token expirado ou inválido no cookie — não bloqueia views públicas.
            # Views que exigem autenticação rejeitarão a requisição via IsAuthenticated.
            return None

        if request.method not in SAFE_METHODS and not has_csrf_header(request):
            raise exceptions.PermissionDenied(CSRF_ERROR_MESSAGE)

        return user, validated_token


class RequireCSRFHeader(BasePermission):
    """
    Permissão para views públicas de autenticação (login, registro, refresh, logout):
    exige X-Requested-With em métodos não seguros, impedindo login CSRF e
    logout/refresh forçados por sites de terceiros.
    """
    message = CSRF_ERROR_MESSAGE

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS or has_csrf_header(request):
            return True
        # Levanta direto para responder 403 (e não 401) mesmo sem usuário autenticado
        raise exceptions.PermissionDenied(self.message)
