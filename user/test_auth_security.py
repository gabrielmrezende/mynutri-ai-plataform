"""
Testes de segurança da autenticação — MyNutri AI
Cobre: Google OAuth (API e callback), pré-sequestro de conta, blacklist de tokens
(logout, refresh, troca de senha, exclusão), header anti-CSRF, aceite de termos,
validadores de senha, contato, depoimentos e validação de e-mail.
"""

import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import override_settings
from google.auth import exceptions as google_exceptions
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from user import email_validation
from user.email_validation import EmailValidationResult
from user.models import Profile
from user.models import Testimonial as TestimonialModel  # alias: evita coleta pelo pytest

User = get_user_model()

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
VERIFY_PATH = 'user.views.google_id_token.verify_oauth2_token'

STRONG_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Cliente sem cookies, enviando X-Requested-With como o frontend."""
    return APIClient(**XHR)


@pytest.fixture(autouse=True)
def email_validation_ok():
    """Evita DNS/rede real no cadastro e no formulário de contato."""
    ok = EmailValidationResult(is_valid=True, layer='all')
    with patch('user.serializers.validate_email_full', return_value=ok), \
            patch('user.forms.validate_email_full', return_value=ok):
        yield


@pytest.fixture
def password_user(db):
    return User.objects.create_user(
        username='senha@teste.com', email='senha@teste.com',
        password='SenhaForte!2024', first_name='Senha',
    )


@pytest.fixture
def google_user(db):
    user = User.objects.create_user(
        username='google@teste.com', email='google@teste.com',
        password=None, first_name='Google',
    )
    return user


def cookie_client(user, csrf_header=True):
    """Cliente autenticado pelos cookies HttpOnly (como o navegador)."""
    refresh = RefreshToken.for_user(user)
    c = APIClient(**XHR) if csrf_header else APIClient()
    c.cookies['mynutri_access'] = str(refresh.access_token)
    c.cookies['mynutri_refresh'] = str(refresh)
    return c, refresh


def google_claims(**overrides):
    claims = {
        'iss': 'https://accounts.google.com',
        'aud': 'test-client-id.apps.googleusercontent.com',
        'email': 'novo.google@teste.com',
        'email_verified': True,
        'given_name': 'Novo',
        'family_name': 'Google',
    }
    claims.update(overrides)
    return claims


def is_blacklisted(refresh):
    return BlacklistedToken.objects.filter(token__jti=refresh['jti']).exists()


# ---------------------------------------------------------------------------
# Google OAuth — POST /api/v1/auth/google
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGoogleAuth:

    def test_valida_token_com_client_id(self, client):
        with patch(VERIFY_PATH, return_value=google_claims()) as verify:
            response = client.post('/api/v1/auth/google', {'id_token': 'tok'}, format='json')
        assert response.status_code == 200
        args = verify.call_args[0]
        assert args[0] == 'tok'
        assert args[2] == 'test-client-id.apps.googleusercontent.com'  # aud validado

    def test_cria_usuario_sem_senha_e_profile(self, client):
        with patch(VERIFY_PATH, return_value=google_claims()):
            response = client.post('/api/v1/auth/google', {'id_token': 'tok'}, format='json')
        assert response.status_code == 200
        user = User.objects.get(email='novo.google@teste.com')
        assert not user.has_usable_password()
        assert Profile.objects.filter(user=user).exists()
        assert response.data == {'user': {'id': user.id, 'email': user.email, 'nome': 'Novo Google'}}
        assert response.cookies['mynutri_access'].value

    def test_token_invalido_ou_aud_errado_retorna_401(self, client):
        with patch(VERIFY_PATH, side_effect=ValueError('Token has wrong audience')):
            response = client.post('/api/v1/auth/google', {'id_token': 'tok'}, format='json')
        assert response.status_code == 401
        assert not User.objects.exists()

    def test_issuer_errado_retorna_401(self, client):
        with patch(VERIFY_PATH, side_effect=google_exceptions.GoogleAuthError('Wrong issuer')):
            response = client.post('/api/v1/auth/google', {'id_token': 'tok'}, format='json')
        assert response.status_code == 401

    def test_email_nao_verificado_retorna_401(self, client):
        with patch(VERIFY_PATH, return_value=google_claims(email_verified=False)):
            response = client.post('/api/v1/auth/google', {'id_token': 'tok'}, format='json')
        assert response.status_code == 401
        assert not User.objects.exists()

    def test_falha_de_rede_retorna_503(self, client):
        with patch(VERIFY_PATH, side_effect=google_exceptions.TransportError('down')):
            response = client.post('/api/v1/auth/google', {'id_token': 'tok'}, format='json')
        assert response.status_code == 503

    def test_sem_id_token_retorna_400(self, client):
        response = client.post('/api/v1/auth/google', {}, format='json')
        assert response.status_code == 400

    def test_conta_existente_com_senha_tem_senha_invalidada_e_sessoes_revogadas(self, client, password_user):
        """Pré-sequestro: quem cadastrou com senha pode não ser o dono do e-mail."""
        old_refresh = RefreshToken.for_user(password_user)
        claims = google_claims(email='SENHA@teste.com')  # caixa diferente
        with patch(VERIFY_PATH, return_value=claims):
            response = client.post('/api/v1/auth/google', {'id_token': 'tok'}, format='json')
        assert response.status_code == 200
        assert response.data['user']['id'] == password_user.id
        password_user.refresh_from_db()
        assert not password_user.has_usable_password()
        assert is_blacklisted(old_refresh)
        assert User.objects.count() == 1

    def test_refresh_do_atacante_nao_funciona_apos_login_google(self, password_user):
        attacker, refresh = cookie_client(password_user)
        with patch(VERIFY_PATH, return_value=google_claims(email='senha@teste.com')):
            APIClient(**XHR).post('/api/v1/auth/google', {'id_token': 'tok'}, format='json')
        response = attacker.post('/api/v1/auth/token/refresh')
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Google OAuth — POST /api/v1/auth/google/callback (redirect mode)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGoogleCallback:

    def _post(self, body_csrf='abc', cookie_csrf='abc', credential='cred'):
        c = APIClient()  # Google posta form-encoded, sem X-Requested-With
        if cookie_csrf is not None:
            c.cookies['g_csrf_token'] = cookie_csrf
        return c.post(
            '/api/v1/auth/google/callback',
            {'credential': credential, 'g_csrf_token': body_csrf},
        )

    def test_sucesso_redireciona_e_seta_cookies(self):
        with patch(VERIFY_PATH, return_value=google_claims()):
            response = self._post()
        assert response.status_code == 302
        assert response['Location'] == '/dieta/'
        assert response.cookies['mynutri_access'].value
        assert response.cookies['mynutri_refresh']['httponly']

    def test_csrf_divergente_redireciona_sem_logar_valores(self, caplog):
        with caplog.at_level(logging.WARNING, logger='user'):
            response = self._post(body_csrf='valor-body-secreto', cookie_csrf='valor-cookie-secreto')
        assert response['Location'] == '/auth/?google_error=csrf'
        assert 'valor-body-secreto' not in caplog.text
        assert 'valor-cookie-secreto' not in caplog.text

    def test_sem_cookie_csrf_redireciona(self):
        response = self._post(cookie_csrf=None)
        assert response['Location'] == '/auth/?google_error=csrf'

    def test_token_invalido_redireciona(self):
        with patch(VERIFY_PATH, side_effect=ValueError('bad')):
            response = self._post()
        assert response['Location'] == '/auth/?google_error=invalid_token'
        assert 'mynutri_access' not in response.cookies

    def test_email_nao_verificado_redireciona(self):
        with patch(VERIFY_PATH, return_value=google_claims(email_verified='false')):
            response = self._post()
        assert response['Location'] == '/auth/?google_error=unverified_email'

    def test_callback_tambem_invalida_senha_existente(self, password_user):
        with patch(VERIFY_PATH, return_value=google_claims(email='senha@teste.com')):
            self._post()
        password_user.refresh_from_db()
        assert not password_user.has_usable_password()


# ---------------------------------------------------------------------------
# Header anti-CSRF (X-Requested-With)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCSRFHeader:

    def test_cookie_sem_header_em_metodo_nao_seguro_retorna_403(self, password_user):
        c, _ = cookie_client(password_user, csrf_header=False)
        response = c.patch('/api/v1/user/profile', {'first_name': 'X'}, format='json')
        assert response.status_code == 403
        password_user.refresh_from_db()
        assert password_user.first_name == 'Senha'

    def test_cookie_com_header_funciona(self, password_user):
        c, _ = cookie_client(password_user)
        response = c.patch('/api/v1/user/profile', {'first_name': 'X'}, format='json')
        assert response.status_code == 200

    def test_cookie_sem_header_em_get_funciona(self, password_user):
        c, _ = cookie_client(password_user, csrf_header=False)
        assert c.get('/api/v1/user/profile').status_code == 200

    def test_bearer_nao_exige_header(self, password_user):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(password_user).access_token}')
        response = c.patch('/api/v1/user/profile', {'first_name': 'X'}, format='json')
        assert response.status_code == 200

    @pytest.mark.parametrize('url', [
        '/api/v1/auth/login', '/api/v1/auth/register',
        '/api/v1/auth/token/refresh', '/api/v1/auth/logout',
    ])
    def test_views_de_auth_exigem_header(self, url):
        response = APIClient().post(url, {}, format='json')
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Registro — termos, senha, e-mail case-insensitive
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRegisterSecurity:
    payload = {'nome': 'Ana', 'email': 'ana@teste.com', 'senha': 'SenhaForte!2024', 'accepted_terms': True}

    def test_sem_aceite_de_termos_retorna_400(self, client):
        data = {k: v for k, v in self.payload.items() if k != 'accepted_terms'}
        response = client.post('/api/v1/auth/register', data, format='json')
        assert response.status_code == 400
        assert 'accepted_terms' in response.data

    def test_termos_false_retorna_400(self, client):
        response = client.post('/api/v1/auth/register', {**self.payload, 'accepted_terms': False}, format='json')
        assert response.status_code == 400
        assert 'accepted_terms' in response.data

    def test_grava_data_de_aceite_no_profile(self, client):
        response = client.post('/api/v1/auth/register', self.payload, format='json')
        assert response.status_code == 201
        profile = Profile.objects.get(user__email='ana@teste.com')
        assert profile.terms_accepted_at is not None

    @override_settings(AUTH_PASSWORD_VALIDATORS=STRONG_VALIDATORS)
    def test_senha_comum_rejeitada_pelos_validadores_do_django(self, client):
        response = client.post('/api/v1/auth/register', {**self.payload, 'senha': 'password123'}, format='json')
        assert response.status_code == 400
        assert 'senha' in response.data

    def test_email_duplicado_com_caixa_diferente(self, client, password_user):
        response = client.post(
            '/api/v1/auth/register', {**self.payload, 'email': 'SENHA@Teste.com'}, format='json',
        )
        assert response.status_code == 400
        assert 'email' in response.data

    def test_banco_rejeita_email_duplicado_case_insensitive(self, db):
        User.objects.create(username='a1', email='Caixa@Teste.com')
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.create(username='a2', email='caixa@teste.com')

    def test_banco_permite_varios_emails_vazios(self, db):
        User.objects.create(username='admin1', email='')
        User.objects.create(username='admin2', email='')
        assert User.objects.filter(email='').count() == 2

    def test_login_normaliza_email(self, client, password_user):
        response = client.post(
            '/api/v1/auth/login', {'email': '  SENHA@teste.com ', 'password': 'SenhaForte!2024'}, format='json',
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Logout e refresh por cookie
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestLogoutERefresh:

    def test_logout_blacklista_refresh_e_limpa_cookies(self, password_user):
        c, refresh = cookie_client(password_user)
        response = c.post('/api/v1/auth/logout')
        assert response.status_code == 200
        assert is_blacklisted(refresh)
        assert response.cookies['mynutri_access'].value == ''
        assert response.cookies['mynutri_refresh'].value == ''

    def test_refresh_apos_logout_falha(self, password_user):
        c, refresh = cookie_client(password_user)
        c.post('/api/v1/auth/logout')
        c2 = APIClient(**XHR)
        c2.cookies['mynutri_refresh'] = str(refresh)
        assert c2.post('/api/v1/auth/token/refresh').status_code == 401

    def test_logout_sem_cookie_funciona(self, client):
        assert client.post('/api/v1/auth/logout').status_code == 200

    def test_refresh_ignora_token_no_body(self, client, password_user):
        refresh = RefreshToken.for_user(password_user)
        response = client.post('/api/v1/auth/token/refresh', {'refresh': str(refresh)}, format='json')
        assert response.status_code == 400

    def test_refresh_rotacionado_nao_pode_ser_reutilizado(self, password_user):
        c, refresh = cookie_client(password_user)
        assert c.post('/api/v1/auth/token/refresh').status_code == 200
        reuse = APIClient(**XHR)
        reuse.cookies['mynutri_refresh'] = str(refresh)
        assert reuse.post('/api/v1/auth/token/refresh').status_code == 401

    def test_refresh_rotacionado_fica_registrado_para_revogacao(self, password_user):
        c, _ = cookie_client(password_user)
        response = c.post('/api/v1/auth/token/refresh')
        new_raw = response.cookies['mynutri_refresh'].value
        assert OutstandingToken.objects.filter(token=new_raw, user=password_user).exists()

    def test_refresh_de_usuario_inativo_falha(self, password_user):
        c, _ = cookie_client(password_user)
        password_user.is_active = False
        password_user.save()
        assert c.post('/api/v1/auth/token/refresh').status_code == 401


# ---------------------------------------------------------------------------
# Troca de senha
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestChangePassword:
    url = '/api/v1/user/change-password'

    def test_sucesso_revoga_sessoes_e_reemite_cookies(self, password_user):
        other_device = RefreshToken.for_user(password_user)
        c, current = cookie_client(password_user)
        response = c.post(self.url, {
            'current_password': 'SenhaForte!2024', 'new_password': 'OutraSenha!2025',
        }, format='json')
        assert response.status_code == 200
        password_user.refresh_from_db()
        assert password_user.check_password('OutraSenha!2025')
        assert is_blacklisted(other_device)
        assert is_blacklisted(current)
        new_refresh = response.cookies['mynutri_refresh'].value
        assert new_refresh and new_refresh != str(current)
        assert not BlacklistedToken.objects.filter(token__token=new_refresh).exists()
        assert 'token' not in response.data

    def test_senha_atual_errada(self, password_user):
        c, _ = cookie_client(password_user)
        response = c.post(self.url, {'current_password': 'errada', 'new_password': 'OutraSenha!2025'}, format='json')
        assert response.status_code == 400

    @override_settings(AUTH_PASSWORD_VALIDATORS=STRONG_VALIDATORS)
    def test_nova_senha_fraca_rejeitada(self, password_user):
        c, _ = cookie_client(password_user)
        response = c.post(self.url, {'current_password': 'SenhaForte!2024', 'new_password': '12345678'}, format='json')
        assert response.status_code == 400
        password_user.refresh_from_db()
        assert password_user.check_password('SenhaForte!2024')

    def test_usuario_google_sem_senha_recebe_400_claro(self, google_user):
        c, _ = cookie_client(google_user)
        response = c.post(self.url, {'current_password': 'x', 'new_password': 'OutraSenha!2025'}, format='json')
        assert response.status_code == 400
        assert 'Google' in response.data['error']

    def test_sem_autenticacao(self, client):
        assert client.post(self.url, {}, format='json').status_code == 401


# ---------------------------------------------------------------------------
# Perfil e exclusão de conta
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDeleteAccount:
    url = '/api/v1/user/delete-account'

    def test_profile_expoe_has_password(self, password_user, google_user):
        c1, _ = cookie_client(password_user)
        c2, _ = cookie_client(google_user)
        assert c1.get('/api/v1/user/profile').data['has_password'] is True
        assert c2.get('/api/v1/user/profile').data['has_password'] is False

    def test_senha_errada_nao_exclui(self, password_user):
        c, _ = cookie_client(password_user)
        response = c.delete(self.url, {'password': 'errada'}, format='json')
        assert response.status_code == 400
        assert User.objects.filter(pk=password_user.pk).exists()

    def test_senha_correta_exclui_limpa_cookies_e_revoga(self, password_user):
        c, refresh = cookie_client(password_user)
        response = c.delete(self.url, {'password': 'SenhaForte!2024'}, format='json')
        assert response.status_code == 200
        assert not User.objects.filter(pk=password_user.pk).exists()
        assert response.cookies['mynutri_access'].value == ''
        assert response.cookies['mynutri_refresh'].value == ''
        assert is_blacklisted(refresh)

    def test_usuario_google_exige_confirmacao(self, google_user):
        c, _ = cookie_client(google_user)
        response = c.delete(self.url, {}, format='json')
        assert response.status_code == 400
        assert User.objects.filter(pk=google_user.pk).exists()

    def test_usuario_google_confirma_com_excluir(self, google_user):
        c, _ = cookie_client(google_user)
        response = c.delete(self.url, {'confirm': 'EXCLUIR'}, format='json')
        assert response.status_code == 200
        assert not User.objects.filter(pk=google_user.pk).exists()

    def test_post_tambem_exclui(self, google_user):
        c, _ = cookie_client(google_user)
        response = c.post(self.url, {'confirm': 'EXCLUIR'}, format='json')
        assert response.status_code == 200
        assert not User.objects.filter(pk=google_user.pk).exists()

    def test_log_nao_contem_email(self, password_user, caplog):
        c, _ = cookie_client(password_user)
        with caplog.at_level(logging.INFO, logger='user'):
            c.delete(self.url, {'password': 'SenhaForte!2024'}, format='json')
        assert 'senha@teste.com' not in caplog.text


# ---------------------------------------------------------------------------
# Contato
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestContact:
    url = '/api/v1/contact'
    data = {'nome': 'Fulano', 'email': 'fulano@teste.com', 'assunto': 'Dúvida', 'mensagem': 'Olá, tenho uma dúvida sobre a dieta.'}

    @pytest.fixture(autouse=True)
    def contact_settings(self, settings):
        settings.CONTACT_EMAIL = 'contato@mynutri.test'
        settings.DEFAULT_FROM_EMAIL = 'noreply@mynutri.test'

    def test_envia_email(self, client, mailoutbox, caplog):
        with caplog.at_level(logging.INFO, logger='user'):
            response = client.post(self.url, self.data, format='json')
        assert response.status_code == 200
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ['contato@mynutri.test']
        assert 'fulano@teste.com' not in caplog.text

    def test_dados_invalidos_retorna_400(self, client):
        response = client.post(self.url, {'nome': ''}, format='json')
        assert response.status_code == 400

    def test_falha_no_envio_retorna_503(self, client):
        with patch('user.views.send_mail', side_effect=OSError('smtp down')):
            response = client.post(self.url, self.data, format='json')
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# Depoimentos
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTestimonials:
    url = '/api/v1/testimonials'
    data = {'text': 'Plano excelente, recomendo!', 'rating': 5}

    def test_get_publico(self, client, password_user):
        TestimonialModel.objects.create(user=password_user, text='Muito bom mesmo', rating=4)
        response = APIClient().get(self.url)
        assert response.status_code == 200
        assert len(response.data) == 1

    def test_post_exige_autenticacao(self, client):
        assert client.post(self.url, self.data, format='json').status_code == 401

    def test_post_cria(self, password_user):
        c, _ = cookie_client(password_user)
        response = c.post(self.url, self.data, format='json')
        assert response.status_code == 201
        assert TestimonialModel.objects.filter(user=password_user).count() == 1

    def test_limite_diario(self, password_user):
        c, _ = cookie_client(password_user)
        for _ in range(3):
            assert c.post(self.url, self.data, format='json').status_code == 201
        assert c.post(self.url, self.data, format='json').status_code == 429

    def test_limite_usa_data_local_e_nao_utc(self, password_user):
        """22h em São Paulo já é o dia seguinte em UTC — o limite deve continuar valendo."""
        # timezone.now() devolve UTC: 01h do dia 11 em UTC = 22h do dia 10 em SP
        night = datetime(2026, 3, 10, 22, 0, tzinfo=ZoneInfo('America/Sao_Paulo')).astimezone(ZoneInfo('UTC'))
        c, _ = cookie_client(password_user)
        with patch('django.utils.timezone.now', return_value=night):
            for _ in range(3):
                assert c.post(self.url, self.data, format='json').status_code == 201
            assert c.post(self.url, self.data, format='json').status_code == 429

    def test_depoimentos_de_ontem_nao_contam(self, password_user):
        c, _ = cookie_client(password_user)
        for _ in range(3):
            c.post(self.url, self.data, format='json')
        TestimonialModel.objects.update(created_at=datetime.now(ZoneInfo('UTC')) - timedelta(days=1))
        assert c.post(self.url, self.data, format='json').status_code == 201


# ---------------------------------------------------------------------------
# Validação de e-mail — APIs externas e SMTP
# ---------------------------------------------------------------------------

class TestEmailValidationHardening:

    def test_zerobounce_usa_params_sem_interpolar_na_url(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {'status': 'valid'}
        with patch('user.email_validation.requests.get', return_value=resp) as get:
            result = email_validation._validate_via_zerobounce('a+b@x.com', 'SECRET-KEY')
        assert result.is_valid
        url = get.call_args[0][0]
        assert 'SECRET-KEY' not in url and 'a+b@x.com' not in url
        assert get.call_args[1]['params'] == {'api_key': 'SECRET-KEY', 'email': 'a+b@x.com'}

    def test_hunter_usa_params(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {'data': {'status': 'invalid'}}
        with patch('user.email_validation.requests.get', return_value=resp) as get:
            result = email_validation._validate_via_hunter('a@x.com', 'SECRET-KEY')
        assert not result.is_valid
        assert 'SECRET-KEY' not in get.call_args[0][0]

    def test_falha_da_api_nao_loga_a_key(self, caplog):
        err = Exception('GET https://api.zerobounce.net/v2/validate?api_key=SECRET-KEY failed')
        with patch('user.email_validation.requests.get', side_effect=err), \
                caplog.at_level(logging.WARNING):
            result = email_validation._validate_via_zerobounce('a@x.com', 'SECRET-KEY')
        assert result.is_valid  # falha graciosa
        assert 'SECRET-KEY' not in caplog.text
        assert 'SECRET-KEY' not in str(result.details)

    @pytest.mark.parametrize('ip,expected', [
        ('8.8.8.8', True), ('10.0.0.5', False), ('127.0.0.1', False),
        ('192.168.1.1', False), ('169.254.169.254', False), ('::1', False), ('0.0.0.0', False),  # nosec B104 — só dado de teste
    ])
    def test_is_public_ip(self, ip, expected):
        assert email_validation._is_public_ip(ip) is expected

    def test_smtp_nao_conecta_em_mx_privado(self):
        mx = MagicMock(preference=10)
        mx.exchange.to_text.return_value = 'mx.interno.'
        addrinfo = [(2, 1, 6, '', ('10.0.0.7', 25))]
        with patch.object(email_validation, '_SMTP_ENABLED', True), \
                patch('dns.resolver.resolve', return_value=[mx]), \
                patch('user.email_validation.socket.getaddrinfo', return_value=addrinfo), \
                patch('user.email_validation.smtplib.SMTP') as smtp:
            result = email_validation.validate_smtp('alguem@dominio-malicioso.com')
        assert result.is_valid
        assert result.details.get('skipped')
        smtp.assert_not_called()

    def test_smtp_conecta_no_ip_publico_resolvido(self):
        mx = MagicMock(preference=10)
        mx.exchange.to_text.return_value = 'mx.publico.'
        addrinfo = [(2, 1, 6, '', ('8.8.4.4', 25))]
        with patch.object(email_validation, '_SMTP_ENABLED', True), \
                patch('dns.resolver.resolve', return_value=[mx]), \
                patch('user.email_validation.socket.getaddrinfo', return_value=addrinfo), \
                patch('user.email_validation.smtplib.SMTP') as smtp:
            smtp.return_value.__enter__.return_value.rcpt.return_value = (250, b'ok')
            result = email_validation.validate_smtp('alguem@dominio.com')
        assert result.is_valid
        smtp.return_value.__enter__.return_value.connect.assert_called_once_with('8.8.4.4', 25)
