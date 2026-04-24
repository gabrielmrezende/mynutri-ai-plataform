from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    """
    Autentica usando o cookie HttpOnly 'mynutri_access'.
    Fallback automático para header 'Authorization: Bearer' (API clients e testes).
    """

    def authenticate(self, request):
        # 1. Header Authorization presente → comportamento padrão do simplejwt
        if self.get_header(request):
            return super().authenticate(request)

        # 2. Cookie HttpOnly
        raw_token = request.COOKIES.get('mynutri_access')
        if not raw_token:
            return None

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
