"""
Testes de infraestrutura HTTP — robots.txt, sitemap.xml, health check,
cabeçalhos de segurança (CSP/Permissions-Policy/Referrer-Policy) e
validações de settings de produção.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from rest_framework.test import APIClient

BASE_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestSeoFiles:

    def test_robots_txt(self, client):
        r = client.get('/robots.txt')
        assert r.status_code == 200
        assert r['Content-Type'].startswith('text/plain')
        body = r.content.decode()
        for page in ('/', '/auth/', '/termos/', '/privacidade/', '/contato/'):
            assert f'Allow: {page}\n' in body
        for page in ('/dieta/', '/perfil/', '/historico/', '/questionario/'):
            assert f'Disallow: {page}\n' in body
        assert 'Sitemap: http://testserver/sitemap.xml' in body

    def test_sitemap_xml(self, client):
        r = client.get('/sitemap.xml')
        assert r.status_code == 200
        assert r['Content-Type'].startswith('application/xml')
        body = r.content.decode()
        assert '<loc>http://testserver/termos/</loc>' in body
        assert '/dieta/' not in body
        assert '/perfil/' not in body


@pytest.mark.django_db
class TestSecurityHeaders:

    def test_csp_enforcing_em_paginas_e_api(self, client):
        for url in ('/health/', '/robots.txt', '/api/v1/diet'):
            r = client.get(url)
            csp = r['Content-Security-Policy']
            assert "default-src 'self'" in csp
            assert "script-src 'self' https://accounts.google.com" in csp
            assert "object-src 'none'" in csp
            assert "frame-src https://accounts.google.com" in csp
            assert "'unsafe-inline'" not in csp.split('script-src')[1].split(';')[0]

    def test_csp_contrato_c7_completo(self):
        from mynutri.middleware import CONTENT_SECURITY_POLICY
        expected = (
            "default-src 'self'; "
            "script-src 'self' https://accounts.google.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://accounts.google.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://accounts.google.com; "
            "frame-src https://accounts.google.com; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self' https://accounts.google.com"
        )
        assert CONTENT_SECURITY_POLICY == expected

    def test_permissions_e_referrer_policy(self, client):
        r = client.get('/health/')
        assert 'camera=()' in r['Permissions-Policy']
        assert 'geolocation=()' in r['Permissions-Policy']
        assert r['Referrer-Policy'] == 'strict-origin-when-cross-origin'

    def test_no_cache_in_dev_middleware(self, rf):
        from django.http import HttpResponse
        from mynutri.middleware import NoCacheInDevMiddleware
        response = NoCacheInDevMiddleware(lambda request: HttpResponse('ok'))(rf.get('/'))
        assert 'no-store' in response['Cache-Control']
        assert response['Pragma'] == 'no-cache'

    def test_view_pode_definir_csp_propria(self, rf):
        from django.http import HttpResponse
        from mynutri.middleware import SecurityHeadersMiddleware

        def view(request):
            r = HttpResponse('ok')
            r['Content-Security-Policy'] = "default-src 'none'"
            return r
        response = SecurityHeadersMiddleware(view)(rf.get('/'))
        assert response['Content-Security-Policy'] == "default-src 'none'"

    def test_health_banco_fora_retorna_503(self, client):
        from unittest.mock import patch
        with patch('mynutri.urls.connection.ensure_connection', side_effect=Exception('db down')):
            r = client.get('/health/')
        assert r.status_code == 503

    def test_health_sem_auth(self, client):
        r = client.get('/health/')
        assert r.status_code == 200


def _run_settings(extra_env):
    """Importa mynutri.settings num processo limpo com o ambiente dado."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DJANGO_', 'CACHE_', 'SENTRY_'))}
    env.update({
        'SECRET_KEY': 'fake-secret-key-for-settings-test-0123456789abcdef',
        'AI_API_KEY': 'x',
        'AI_API_URL': 'https://ai.example.com',
        'GOOGLE_CLIENT_ID': 'x.apps.googleusercontent.com',
        'DATABASE_URL': 'postgres://u:p@localhost:5432/db',
        'SENTRY_DSN': '',
    })
    env.update(extra_env)
    code = (
        'import mynutri.settings as s; '
        'print(s.STORAGES["staticfiles"]["BACKEND"]); '
        'print(s.CACHES["default"]["BACKEND"]); '
        'print(s.CACHES["default"].get("OPTIONS"))'
    )
    return subprocess.run(
        [sys.executable, '-c', code], cwd=BASE_DIR, env=env,
        capture_output=True, text=True, timeout=60,
    )


class TestProductionSettings:

    def test_producao_sem_cache_url_usa_cache_no_banco(self):
        # Sem Redis (ex.: Vercel) o cache precisa ser compartilhado → DatabaseCache
        r = _run_settings({'DEBUG': 'False', 'CACHE_URL': ''})
        assert r.returncode == 0, r.stderr
        assert 'django.core.cache.backends.db.DatabaseCache' in r.stdout

    def test_producao_com_cache_url(self):
        r = _run_settings({'DEBUG': 'False', 'CACHE_URL': 'redis://localhost:6379/1'})
        assert r.returncode == 0, r.stderr
        storage, cache_backend, options = r.stdout.split('\n')[:3]
        assert storage == 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        assert cache_backend == 'django.core.cache.backends.redis.RedisCache'
        # MAX_ENTRIES não é opção válida do RedisCache
        assert options == 'None'

    def test_dev_sem_cache_url_usa_locmem(self):
        r = _run_settings({'DEBUG': 'True', 'CACHE_URL': ''})
        assert r.returncode == 0, r.stderr
        assert 'LocMemCache' in r.stdout
        assert 'StaticFilesStorage' in r.stdout
