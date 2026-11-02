"""
Django settings — MyNutri AI
Funciona tanto em desenvolvimento (SQLite + DEBUG=True) quanto em produção (PostgreSQL + Render).
"""

import os
from pathlib import Path
from datetime import timedelta

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega .env local (ignorado em produção — o Render injeta as vars diretamente)
load_dotenv(BASE_DIR / '.env')

# =============================================================================
# Validação de variáveis obrigatórias
# =============================================================================
_REQUIRED_VARS = {
    'SECRET_KEY': (
        'Django secret key (gere com: python -c "from django.core.management.utils '
        'import get_random_secret_key; print(get_random_secret_key())")'
    ),
    'AI_API_KEY': 'Chave da API de IA (OpenAI, Gemini, etc.)',
    'AI_API_URL': 'URL do endpoint da API de IA',
    'DATABASE_URL': 'Connection string do Postgres do Supabase (Dashboard → Connect → Session pooler)',
}

for _var, _desc in _REQUIRED_VARS.items():
    if not os.getenv(_var):
        raise ValueError(
            f'\n❌ Variável "{_var}" não configurada.\n'
            f'   {_desc}\n'
            f'   Configure em .env (local) ou nas Environment Variables do Vercel.\n'
        )

# =============================================================================
# Core
# =============================================================================
SECRET_KEY = os.getenv('SECRET_KEY')
DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')

# ALLOWED_HOSTS: lista do .env + domínios automáticos do Vercel, Render ou Railway
_allowed = os.getenv('ALLOWED_HOSTS', '').split(',') if os.getenv('ALLOWED_HOSTS') else []
_auto_hosts = (
    os.getenv('VERCEL_URL'),                        # URL única do deploy (Vercel)
    os.getenv('VERCEL_BRANCH_URL'),                 # URL da branch (Vercel)
    os.getenv('VERCEL_PROJECT_PRODUCTION_URL'),     # domínio de produção (Vercel)
    os.getenv('RENDER_EXTERNAL_HOSTNAME'),          # injetado automaticamente pelo Render
    os.getenv('RAILWAY_PUBLIC_DOMAIN'),             # injetado automaticamente pelo Railway
)
for _auto_host in _auto_hosts:
    if _auto_host:
        _allowed.append(_auto_host)
ALLOWED_HOSTS = [h.strip() for h in _allowed if h.strip()] or (['localhost', '127.0.0.1'] if DEBUG else [])

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# =============================================================================
# Apps
# =============================================================================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',  # revogação de refresh tokens (logout, troca de senha)
    'corsheaders',
    # Projeto
    'user',
    'nutrition',
]

# =============================================================================
# Middleware — WhiteNoise logo após SecurityMiddleware
# =============================================================================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.gzip.GZipMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',       # serve static sem nginx
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'mynutri.middleware.SecurityHeadersMiddleware',     # CSP + Permissions-Policy + Referrer-Policy
]

if DEBUG:
    MIDDLEWARE.append('mynutri.middleware.NoCacheInDevMiddleware')

ROOT_URLCONF = 'mynutri.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'frontend' / 'public'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'mynutri.wsgi.application'

# =============================================================================
# Banco de Dados — Supabase (PostgreSQL)
# DATABASE_URL obrigatória em todos os ambientes (sem fallback para SQLite).
# Use a connection string do "Session pooler" (porta 5432): é IPv4 e mantém
# conexões persistentes. A conexão direta (db.<ref>.supabase.co) é só IPv6.
# O "Transaction pooler" (porta 6543) é detectado e ajustado automaticamente.
# =============================================================================
_db_url = os.getenv('DATABASE_URL')
_transaction_pooler = ':6543/' in _db_url

DATABASES = {
    'default': dj_database_url.parse(
        _db_url,
        conn_max_age=int(os.getenv('DB_CONN_MAX_AGE', '0' if _transaction_pooler else '600')),
        conn_health_checks=True,
        ssl_require=True,
    )
}
# Transaction pooler (PgBouncer/Supavisor) não suporta server-side cursors
DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = _transaction_pooler

# =============================================================================
# Autenticação
# =============================================================================
AUTH_USER_MODEL = 'user.CustomUser'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# =============================================================================
# Internacionalização
# =============================================================================
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

# =============================================================================
# Arquivos estáticos — WhiteNoise + collectstatic
# =============================================================================
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Django 4.2+ usa STORAGES (STATICFILES_STORAGE foi removido no Django 5.1 e é ignorado).
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG else
            'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}
STATICFILES_DIRS = [BASE_DIR / 'frontend']
# Vale para arquivos referenciados SEM hash (o HTML usa /static/src/... direto).
# Arquivos com hash do manifest são sempre servidos como immutable (1 ano) pelo
# WhiteNoise. 1 ano aqui deixaria usuários com JS/CSS antigos após cada deploy.
WHITENOISE_MAX_AGE = 0 if DEBUG else 3600

# =============================================================================
# Django REST Framework
# =============================================================================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'user.authentication.CookieJWTAuthentication',  # cookie HttpOnly primeiro
        'rest_framework_simplejwt.authentication.JWTAuthentication',  # Bearer fallback
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '20/hour',
        'user': '300/hour',
        # Anti-abuso de /diet/generate (conta toda requisição, inclusive falhas).
        # A cota de negócio (gerações bem-sucedidas/dia) é DIET_GENERATE_DAILY_LIMIT.
        'diet_generate': '10/day',
        'job_status': '1200/hour',     # polling a cada 3s do frontend
        'anamnese': '20/hour',
        'contact': '5/hour',
        'login': '5/minute',
        'change_password': '5/hour',
        'delete_account': '5/hour',
    },
    # Quantos proxies reversos ficam na frente do Django (Render = 1). O DRF usa
    # X-Forwarded-For com este valor para achar o IP real no throttle anônimo.
    'NUM_PROXIES': int(os.getenv('NUM_PROXIES', '1')),
}

# Cota diária de gerações de dieta por usuário (janela de 24h). Jobs que
# falharam ou expiraram não contam — ver DietGenerateAPIView.
DIET_GENERATE_DAILY_LIMIT = int(os.getenv('DIET_GENERATE_DAILY_LIMIT', '3'))

# =============================================================================
# SimpleJWT
# =============================================================================
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,  # refresh antigo não pode ser reutilizado após rotação
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# =============================================================================
# Google OAuth — client ID usado para validar o 'aud' do id_token
# Obrigatório em produção; em dev cai no client ID público do frontend.
# =============================================================================
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
if not GOOGLE_CLIENT_ID:
    if not DEBUG:
        raise ValueError(
            f'\n❌ Variável "GOOGLE_CLIENT_ID" não configurada.\n'
            f'   Client ID OAuth do Google (console.cloud.google.com → Credenciais).\n'
            f'   Configure em .env (local) ou nas Environment Variables do Render.\n'
        )
    GOOGLE_CLIENT_ID = '806980657199-js2h4t4o9cq8577c7geulvgosdt777t2.apps.googleusercontent.com'

# =============================================================================
# CORS
# Dev: libera tudo. Prod: usa CORS_ALLOWED_ORIGINS do .env
# Formato: CORS_ALLOWED_ORIGINS=https://meusite.com,https://www.meusite.com
# =============================================================================
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    _cors_origins = os.getenv('CORS_ALLOWED_ORIGINS', '')
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_origins.split(',') if o.strip()]

CORS_ALLOW_CREDENTIALS = True

# =============================================================================
# Segurança — ativo apenas em produção (DEBUG=False)
# =============================================================================
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000        # 1 ano
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Health check do Render pode chegar via HTTP interno — não redireciona para HTTPS
    SECURE_REDIRECT_EXEMPT = [r'^health/$']

SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# =============================================================================
# Cache — Redis (CACHE_URL) quando disponível; senão banco (prod) ou LocMem (dev)
# Usado pelo throttle do DRF, validação de e-mail e cache de páginas.
# Em produção o cache PRECISA ser compartilhado entre processos/instâncias:
# LocMemCache é por processo, então com vários workers gunicorn (ou várias
# funções serverless no Vercel) o rate limit seria multiplicado. Sem Redis,
# usa DatabaseCache no Postgres (requer `python manage.py createcachetable`).
# Para Redis: CACHE_URL=redis://localhost:6379/1
# =============================================================================
_cache_url = os.getenv('CACHE_URL', '')
if _cache_url:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': _cache_url,
            'TIMEOUT': 86400,               # 24 h padrão
            'KEY_PREFIX': 'mynutri',        # isola das chaves do Celery no mesmo Redis
        }
    }
elif not DEBUG:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
            'LOCATION': 'mynutri_cache',
            'TIMEOUT': 86400,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'mynutri-default',
        }
    }

# =============================================================================
# Validação de e-mail em múltiplas camadas
# Veja: user/email_validation.py para documentação completa.
# =============================================================================
# EMAIL_DNS_TIMEOUT=5            — timeout DNS em segundos
# EMAIL_SMTP_ENABLED=False       — ativa verificação SMTP (lento, opcional)
# EMAIL_SMTP_TIMEOUT=10          — timeout SMTP em segundos
# EMAIL_VALIDATION_USE_API=False — ativa validação via API externa
# EMAIL_VALIDATION_PROVIDER=zerobounce  — 'zerobounce' ou 'hunter'
# EMAIL_VALIDATION_API_KEY=<key> — chave da API escolhida
# EMAIL_VALIDATION_CACHE_TTL=86400 — cache de resultados em segundos (24 h)
#
# Todas as opções acima são lidas via os.getenv() em email_validation.py.
# Não é necessário declará-las aqui; basta configurar no .env.

# =============================================================================
# E-mail — Gmail SMTP via App Password (configure no .env)
# Desenvolvimento: use EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
# Produção: preencha EMAIL_HOST_USER e EMAIL_HOST_PASSWORD com App Password do Gmail
# Guia App Password: https://myaccount.google.com/apppasswords
# =============================================================================
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.smtp.EmailBackend' if not DEBUG
    else 'django.core.mail.backends.console.EmailBackend',
)
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() in ('true', '1', 'yes')
EMAIL_USE_TLS = not EMAIL_USE_SSL  # mutuamente exclusivos: SSL=465, TLS=587
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('EMAIL_HOST_USER', 'mynutriai.app@gmail.com')
CONTACT_EMAIL = os.getenv('CONTACT_EMAIL', 'mynutriai.app@gmail.com')

# =============================================================================
# Celery
# Dev (sem Redis): CELERY_TASK_ALWAYS_EAGER=True → tasks rodam inline/síncrono
# Prod (com Redis): define CELERY_BROKER_URL=redis://<host>:6379/0
# =============================================================================
_celery_broker = os.getenv('CELERY_BROKER_URL', '')

CELERY_BROKER_URL = _celery_broker or 'memory://'
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', CELERY_BROKER_URL if _celery_broker else 'cache+memory://')
# Sem broker Redis configurado → executa tasks de forma síncrona (modo dev)
CELERY_TASK_ALWAYS_EAGER = not bool(_celery_broker)
CELERY_TASK_EAGER_PROPAGATES = True   # propaga exceções em modo eager (útil para dev/testes)
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
# Com acks_late, mensagens não confirmadas voltam para a fila após este tempo;
# precisa ser maior que o time_limit da task (9 min).
CELERY_BROKER_TRANSPORT_OPTIONS = {'visibility_timeout': 60 * 60}
CELERY_WORKER_PREFETCH_MULTIPLIER = 1   # tasks longas: não reserva mensagens à toa

# =============================================================================
# Logging — INFO em dev, WARNING em prod, erros sempre visíveis
# =============================================================================
_log_level = os.getenv('LOG_LEVEL', 'INFO' if DEBUG else 'WARNING')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': _log_level,
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': _log_level,
            'propagate': False,
        },
        'nutrition': {
            'handlers': ['console'],
            'level': 'INFO',  # logs da IA sempre visíveis
            'propagate': False,
        },
        'user.email_validation': {
            'handlers': ['console'],
            'level': 'INFO',  # acompanhar rejeições de e-mail
            'propagate': False,
        },
        'user': {
            'handlers': ['console'],
            'level': 'INFO',  # erros de envio de e-mail e eventos de conta (sem dados pessoais)
            'propagate': False,
        },
    },
}

# =============================================================================
# Sentry — monitoramento de erros em produção
# Configure SENTRY_DSN no .env ou nas vars de ambiente do Render.
# Em desenvolvimento (sem SENTRY_DSN), este bloco é ignorado.
# =============================================================================
_sentry_dsn = os.getenv('SENTRY_DSN', '')
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    import logging as _logging

    # Campos da anamnese/dados de saúde e credenciais que nunca devem sair do servidor
    _SENTRY_SENSITIVE_KEYS = {
        'idade', 'sexo', 'peso', 'altura', 'nivel_atividade', 'objetivo',
        'restricoes', 'food_preferences', 'allergies', 'health_conditions',
        'meals_per_day', 'reason', 'anamnese', 'raw_response',
        'password', 'new_password', 'old_password', 'current_password',
        'token', 'refresh', 'access', 'credential',
    }

    def _sentry_scrub(value):
        if isinstance(value, dict):
            return {
                k: ('[Filtered]' if str(k).lower() in _SENTRY_SENSITIVE_KEYS else _sentry_scrub(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_sentry_scrub(v) for v in value]
        return value

    def _sentry_before_send(event, hint):
        """Remove corpo de requisição, cookies e dados de anamnese/saúde dos eventos."""
        request = event.get('request')
        if isinstance(request, dict):
            request.pop('data', None)
            request.pop('cookies', None)
            headers = request.get('headers')
            if isinstance(headers, dict):
                for h in list(headers):
                    if h.lower() in ('cookie', 'authorization', 'x-csrftoken'):
                        headers[h] = '[Filtered]'
        if 'extra' in event:
            event['extra'] = _sentry_scrub(event['extra'])
        for exc in (event.get('exception') or {}).get('values', []) or []:
            for frame in (exc.get('stacktrace') or {}).get('frames', []) or []:
                if 'vars' in frame:
                    frame['vars'] = _sentry_scrub(frame['vars'])
        return event

    sentry_sdk.init(
        dsn=_sentry_dsn,
        before_send=_sentry_before_send,
        max_request_body_size='never',  # nunca anexa o corpo da requisição
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            LoggingIntegration(
                level=_logging.INFO,        # captura logs INFO como breadcrumbs
                event_level=_logging.ERROR, # envia ao Sentry só a partir de ERROR
            ),
        ],
        traces_sample_rate=float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', '0.1')),
        profiles_sample_rate=float(os.getenv('SENTRY_PROFILES_SAMPLE_RATE', '0.1')),
        environment=os.getenv('ENVIRONMENT', 'production'),
        send_default_pii=False,  # nunca envia dados pessoais por padrão
    )
