class NoCacheInDevMiddleware:
    """Força no-store em DEBUG para evitar que o browser sirva HTML/JS antigos."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response


# Content-Security-Policy em modo enforcing (contrato C7 com o frontend).
# Consequência: o frontend NÃO pode ter <script> inline nem handlers inline
# (onclick=...); todo JS fica em arquivos servidos de 'self'. Google Identity
# Services (login com Google) é a única origem externa de script/frame.
CONTENT_SECURITY_POLICY = '; '.join([
    "default-src 'self'",
    "script-src 'self' https://accounts.google.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://accounts.google.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: https:",
    "connect-src 'self' https://accounts.google.com",
    "frame-src https://accounts.google.com",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self' https://accounts.google.com",
])

# Recursos do navegador que a aplicação não usa ficam desabilitados
PERMISSIONS_POLICY = ', '.join([
    'accelerometer=()',
    'camera=()',
    'geolocation=()',
    'gyroscope=()',
    'magnetometer=()',
    'microphone=()',
    'payment=()',
    'usb=()',
])

REFERRER_POLICY = 'strict-origin-when-cross-origin'


class SecurityHeadersMiddleware:
    """
    Adiciona cabeçalhos de segurança a todas as respostas:
      - Content-Security-Policy (enforcing)
      - Permissions-Policy
      - Referrer-Policy

    Usa setdefault: uma view que precise de política específica pode definir
    o próprio cabeçalho e ele é preservado.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault('Content-Security-Policy', CONTENT_SECURITY_POLICY)
        response.headers.setdefault('Permissions-Policy', PERMISSIONS_POLICY)
        response.headers.setdefault('Referrer-Policy', REFERRER_POLICY)
        return response
