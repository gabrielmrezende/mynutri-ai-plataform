"""
Settings para ambiente de teste.

Herda de mynutri/settings.py (mesma configuração da aplicação real: middleware,
CSP, throttles, storages...) e sobrescreve só o necessário para rodar sem .env:
  - variáveis obrigatórias recebem valores fake ANTES do import
  - banco SQLite in-memory (ou arquivo, via TEST_DB_PATH — usado pelo E2E)
  - throttle global desabilitado, Celery síncrono, cache local
"""

import os
from datetime import timedelta

# ── Ambiente fake (antes do import de settings, que valida estas variáveis) ──
os.environ.setdefault('SECRET_KEY', 'test-secret-key-only-for-testing-do-not-use-in-production')
os.environ.setdefault('AI_API_KEY', 'test-ai-key')
os.environ.setdefault('AI_API_URL', 'https://test-api.example.com/v1/chat/completions')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'test-google-client-id.apps.googleusercontent.com')
# Forçados (não setdefault): um .env local não pode ligar Sentry, Redis ou
# modo produção durante os testes.
os.environ['DEBUG'] = 'True'
os.environ['SENTRY_DSN'] = ''
os.environ['CACHE_URL'] = ''
os.environ['CELERY_BROKER_URL'] = ''
os.environ['CELERY_RESULT_BACKEND'] = ''

from .settings import *  # noqa: E402,F401,F403
from .settings import INSTALLED_APPS as _BASE_INSTALLED_APPS  # noqa: E402

SECRET_KEY = os.environ['SECRET_KEY']

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = list(_BASE_INSTALLED_APPS)
if 'rest_framework_simplejwt.token_blacklist' not in INSTALLED_APPS:
    INSTALLED_APPS.append('rest_framework_simplejwt.token_blacklist')

# Sem NoCacheInDevMiddleware (DEBUG=True o adicionaria), GZip e WhiteNoise nos
# testes — o runserver do E2E serve os estáticos via django.contrib.staticfiles.
MIDDLEWARE = [
    m for m in MIDDLEWARE  # noqa: F405
    if m not in (
        'mynutri.middleware.NoCacheInDevMiddleware',
        'django.middleware.gzip.GZipMiddleware',
        'whitenoise.middleware.WhiteNoiseMiddleware',
    )
]

# Banco in-memory para testes unitários. O E2E (Playwright) precisa de arquivo,
# porque migrate e runserver são processos distintos: TEST_DB_PATH=/tmp/e2e.sqlite3
_test_db_path = os.getenv('TEST_DB_PATH', '')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': _test_db_path or ':memory:',
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'mynutri-tests',
    }
}

REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    'DEFAULT_THROTTLE_CLASSES': [],  # Desabilitado em testes
    'DEFAULT_THROTTLE_RATES': {
        'anon': '1000/hour',
        'user': '1000/hour',
        'diet_generate': '1000/day',
        'job_status': '100000/hour',
        'anamnese': '1000/hour',
        'login': '1000/hour',
        'contact': '1000/hour',
        'testimonial': '1000/day',
    },
    'NUM_PROXIES': None,
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

CORS_ALLOW_ALL_ORIGINS = True

# Variáveis de IA — valores fake para testes (AIService é mockado nos testes)
AI_API_KEY = os.environ['AI_API_KEY']
AI_API_URL = os.environ['AI_API_URL']
AI_MODEL = 'gpt-4o-mini'

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',  # Mais rápido em testes
]

EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

STATIC_URL = 'static/'

# Celery — executa tasks de forma síncrona em testes (sem worker/Redis necessário)
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Logging padrão do Django nos testes: sem handlers com propagate=False,
# para que o caplog do pytest consiga capturar os logs de 'nutrition'/'user'.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
}
