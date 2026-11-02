"""
Serviço de validação de e-mail em múltiplas camadas — MyNutri AI
================================================================

Camadas disponíveis (em ordem de custo/confiabilidade):

  1. Formato   — EmailValidator nativo do Django (gratuito, instantâneo)
  2. DNS / MX  — dnspython verifica se o domínio aceita e-mail (gratuito, <1 s)
  3. SMTP      — handshake SMTP sem enviar mensagem (gratuito, ~2–5 s, bloqueável)
  4. API       — ZeroBounce / Hunter.io / NeverBounce (pago, ~1–3 s, mais confiável)

Uso no serializer:
    from user.email_validation import validate_email_full

    resultado = validate_email_full("usuario@exemplo.com")
    if not resultado.is_valid:
        raise serializers.ValidationError(resultado.message)

Estratégia para produção:
    Ative EMAIL_VALIDATION_USE_API=True e configure EMAIL_VALIDATION_API_KEY
    + EMAIL_VALIDATION_PROVIDER no .env. A camada DNS sempre roda como fallback.
"""

import ipaddress
import logging
import smtplib
import socket
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import requests
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração via variáveis de ambiente
# ---------------------------------------------------------------------------
_DNS_TIMEOUT: float = float(os.getenv('EMAIL_DNS_TIMEOUT', '5'))          # segundos
_SMTP_TIMEOUT: float = float(os.getenv('EMAIL_SMTP_TIMEOUT', '10'))        # segundos
_SMTP_ENABLED: bool = os.getenv('EMAIL_SMTP_ENABLED', 'False').lower() in ('true', '1')
_API_ENABLED: bool = os.getenv('EMAIL_VALIDATION_USE_API', 'False').lower() in ('true', '1')
_API_PROVIDER: str = os.getenv('EMAIL_VALIDATION_PROVIDER', 'zerobounce').lower()
_API_KEY: str = os.getenv('EMAIL_VALIDATION_API_KEY', '')
_CACHE_TTL: int = int(os.getenv('EMAIL_VALIDATION_CACHE_TTL', str(60 * 60 * 24)))  # 24 h


# ---------------------------------------------------------------------------
# Resultado de validação
# ---------------------------------------------------------------------------
@dataclass
class EmailValidationResult:
    is_valid: bool
    message: str = ''
    layer: str = ''                     # 'format' | 'dns' | 'smtp' | 'api'
    details: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.is_valid


# ---------------------------------------------------------------------------
# Camada 1 — Formato
# ---------------------------------------------------------------------------
def validate_format(email: str) -> EmailValidationResult:
    """Verifica se o e-mail tem formato válido usando o validador do Django."""
    try:
        validate_email(email)
        return EmailValidationResult(is_valid=True, layer='format')
    except ValidationError:
        return EmailValidationResult(
            is_valid=False,
            message='E-mail inválido. Verifique o formato (ex: usuario@dominio.com).',
            layer='format',
        )


# ---------------------------------------------------------------------------
# Camada 2 — DNS / MX
# ---------------------------------------------------------------------------
def validate_dns(email: str) -> EmailValidationResult:
    """
    Verifica se o domínio possui registros MX válidos.
    Requer: dnspython  (pip install dnspython)
    """
    try:
        import dns.resolver  # type: ignore
    except ImportError:
        logger.warning(
            'dnspython não instalado — validação DNS ignorada. '
            'Execute: pip install dnspython'
        )
        return EmailValidationResult(
            is_valid=True,
            message='',
            layer='dns',
            details={'skipped': True, 'reason': 'dnspython not installed'},
        )

    domain = email.split('@')[-1].lower()

    try:
        answers = dns.resolver.resolve(domain, 'MX', lifetime=_DNS_TIMEOUT)
        mx_records = [str(r.exchange).rstrip('.') for r in answers]
        logger.debug('MX records para %s: %s', domain, mx_records)
        return EmailValidationResult(
            is_valid=True,
            layer='dns',
            details={'mx_records': mx_records},
        )
    except dns.resolver.NXDOMAIN:
        return EmailValidationResult(
            is_valid=False,
            message='Domínio de e-mail não existe. Verifique se digitou corretamente.',
            layer='dns',
            details={'domain': domain, 'error': 'NXDOMAIN'},
        )
    except dns.resolver.NoAnswer:
        return EmailValidationResult(
            is_valid=False,
            message='O domínio informado não aceita e-mails (sem registros MX).',
            layer='dns',
            details={'domain': domain, 'error': 'NoAnswer'},
        )
    except dns.exception.Timeout:
        logger.warning('Timeout na validação DNS do domínio %s', domain)
        # Falha graciosa: não bloqueia o cadastro por timeout de DNS
        return EmailValidationResult(
            is_valid=True,
            layer='dns',
            details={'domain': domain, 'error': 'timeout', 'graceful': True},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('Erro inesperado na validação DNS (%s): %s', domain, exc)
        return EmailValidationResult(
            is_valid=True,
            layer='dns',
            details={'domain': domain, 'error': str(exc), 'graceful': True},
        )


# ---------------------------------------------------------------------------
# Camada 3 — SMTP (opcional)
# ---------------------------------------------------------------------------
def validate_smtp(email: str) -> EmailValidationResult:
    """
    Tenta verificar se a caixa de e-mail existe via handshake SMTP (sem enviar).

    Limitações:
      - Muitos provedores (Gmail, Outlook) aceitam qualquer endereço para evitar
        enumeração — o resultado pode ser falso positivo.
      - Alguns provedores bloqueiam conexões SMTP de IPs não confiáveis.
      - Pode adicionar 2–10 s à requisição.

    Use com cuidado em produção; prefira a validação via API externa.
    """
    if not _SMTP_ENABLED:
        return EmailValidationResult(
            is_valid=True,
            layer='smtp',
            details={'skipped': True, 'reason': 'SMTP disabled'},
        )

    domain = email.split('@')[-1].lower()
    try:
        import dns.resolver  # type: ignore
        mx_records = dns.resolver.resolve(domain, 'MX', lifetime=_DNS_TIMEOUT)
        mx_host = sorted(mx_records, key=lambda r: r.preference)[0].exchange.to_text().rstrip('.')
    except Exception as exc:  # noqa: BLE001
        logger.warning('SMTP: falha ao obter MX para validação: %s', type(exc).__name__)
        return EmailValidationResult(
            is_valid=True,
            layer='smtp',
            details={'graceful': True, 'reason': type(exc).__name__},
        )

    # Resolve o MX e recusa endereços internos: um domínio controlado pelo
    # usuário poderia apontar o MX para a rede privada do servidor (SSRF).
    mx_ip = _resolve_public_ip(mx_host)
    if mx_ip is None:
        logger.warning('SMTP: MX do domínio %s resolve para IP não público — check ignorado', domain)
        return EmailValidationResult(
            is_valid=True,
            layer='smtp',
            details={'skipped': True, 'reason': 'MX resolves to non-public address'},
        )

    try:
        with smtplib.SMTP(timeout=_SMTP_TIMEOUT) as smtp:
            # Conecta no IP já validado (evita nova resolução DNS — rebinding)
            smtp.connect(mx_ip, 25)
            smtp.helo(socket.getfqdn())
            smtp.mail('noreply@mynutri.ai')
            code, _ = smtp.rcpt(email)
            if code == 250:
                return EmailValidationResult(is_valid=True, layer='smtp')
            return EmailValidationResult(
                is_valid=False,
                message='E-mail não pôde ser verificado. Confirme o endereço e tente novamente.',
                layer='smtp',
                details={'smtp_code': code},
            )
    except (smtplib.SMTPException, OSError, socket.error) as exc:
        logger.warning('SMTP check falhou para o domínio %s: %s', domain, type(exc).__name__)
        # Falha graciosa — não bloqueia o cadastro
        return EmailValidationResult(
            is_valid=True,
            layer='smtp',
            details={'graceful': True, 'reason': type(exc).__name__},
        )


def _is_public_ip(ip: str) -> bool:
    """True apenas para IPs roteáveis na internet (nada de privado/loopback/link-local)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_multicast or addr.is_reserved or addr.is_unspecified
    )


def _resolve_public_ip(host: str) -> Optional[str]:
    """
    Resolve o host e retorna o primeiro IP, desde que TODOS os endereços
    resolvidos sejam públicos. Retorna None se algum for interno ou se falhar.
    """
    try:
        infos = socket.getaddrinfo(host, 25, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError):
        return None
    ips = [info[4][0] for info in infos]
    if not ips or not all(_is_public_ip(ip) for ip in ips):
        return None
    return ips[0]


# ---------------------------------------------------------------------------
# Camada 4 — API Externa
# ---------------------------------------------------------------------------
def _validate_via_zerobounce(email: str, api_key: str) -> EmailValidationResult:
    """Integração com ZeroBounce API v2."""
    try:
        # params= faz o URL-encoding correto (sem interpolar email/api_key na URL)
        response = requests.get(
            'https://api.zerobounce.net/v2/validate',
            params={'api_key': api_key, 'email': email},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        status = data.get('status', '').lower()
        sub_status = data.get('sub_status', '')

        if status == 'valid':
            return EmailValidationResult(
                is_valid=True,
                layer='api',
                details={'provider': 'zerobounce', 'status': status},
            )
        if status in ('invalid', 'do_not_mail', 'abuse', 'spamtrap'):
            return EmailValidationResult(
                is_valid=False,
                message=_zerobounce_message(status, sub_status),
                layer='api',
                details={'provider': 'zerobounce', 'status': status, 'sub_status': sub_status},
            )
        # 'unknown', 'catch-all' → falha graciosa
        return EmailValidationResult(
            is_valid=True,
            layer='api',
            details={'provider': 'zerobounce', 'status': status, 'graceful': True},
        )
    except Exception as exc:  # noqa: BLE001
        # Só o tipo da exceção: a mensagem do requests inclui a URL com a api_key
        logger.warning('ZeroBounce API falhou: %s', type(exc).__name__)
        return EmailValidationResult(
            is_valid=True,
            layer='api',
            details={'graceful': True, 'reason': type(exc).__name__},
        )


def _zerobounce_message(status: str, sub_status: str) -> str:
    messages = {
        'invalid': 'E-mail inválido ou inexistente. Verifique o endereço.',
        'do_not_mail': 'Este endereço de e-mail não pode ser utilizado para cadastro.',
        'abuse': 'Este endereço de e-mail não pode ser utilizado para cadastro.',
        'spamtrap': 'Este endereço de e-mail não pode ser utilizado para cadastro.',
    }
    return messages.get(status, 'E-mail não pôde ser verificado.')


def _validate_via_hunter(email: str, api_key: str) -> EmailValidationResult:
    """Integração com Hunter.io Email Verifier API."""
    try:
        # params= faz o URL-encoding correto (sem interpolar email/api_key na URL)
        response = requests.get(
            'https://api.hunter.io/v2/email-verifier',
            params={'email': email, 'api_key': api_key},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        result = data.get('data', {})
        status = result.get('status', '').lower()

        if status == 'valid':
            return EmailValidationResult(
                is_valid=True,
                layer='api',
                details={'provider': 'hunter', 'status': status},
            )
        if status == 'invalid':
            return EmailValidationResult(
                is_valid=False,
                message='E-mail inválido ou inexistente. Verifique o endereço.',
                layer='api',
                details={'provider': 'hunter', 'status': status},
            )
        # 'risky', 'unknown' → falha graciosa
        return EmailValidationResult(
            is_valid=True,
            layer='api',
            details={'provider': 'hunter', 'status': status, 'graceful': True},
        )
    except Exception as exc:  # noqa: BLE001
        # Só o tipo da exceção: a mensagem do requests inclui a URL com a api_key
        logger.warning('Hunter.io API falhou: %s', type(exc).__name__)
        return EmailValidationResult(
            is_valid=True,
            layer='api',
            details={'graceful': True, 'reason': type(exc).__name__},
        )


def validate_external_api(email: str) -> EmailValidationResult:
    """
    Delega para o provedor configurado em EMAIL_VALIDATION_PROVIDER.
    Suportados: 'zerobounce', 'hunter'
    """
    if not _API_ENABLED:
        return EmailValidationResult(
            is_valid=True,
            layer='api',
            details={'skipped': True, 'reason': 'API validation disabled'},
        )

    if not _API_KEY:
        logger.warning(
            'EMAIL_VALIDATION_USE_API=True mas EMAIL_VALIDATION_API_KEY não configurada. '
            'Pulando validação via API.'
        )
        return EmailValidationResult(
            is_valid=True,
            layer='api',
            details={'skipped': True, 'reason': 'API key not configured'},
        )

    if _API_PROVIDER == 'zerobounce':
        return _validate_via_zerobounce(email, _API_KEY)
    if _API_PROVIDER == 'hunter':
        return _validate_via_hunter(email, _API_KEY)

    logger.warning('Provedor de validação de e-mail desconhecido: %s', _API_PROVIDER)
    return EmailValidationResult(
        is_valid=True,
        layer='api',
        details={'skipped': True, 'reason': f'unknown provider: {_API_PROVIDER}'},
    )


# ---------------------------------------------------------------------------
# Orquestrador principal — com cache
# ---------------------------------------------------------------------------
def validate_email_full(email: str) -> EmailValidationResult:
    """
    Executa todas as camadas de validação em sequência.
    Falha em qualquer camada obrigatória interrompe a verificação.
    Falhas graciosas (timeout, API indisponível) nunca bloqueiam o cadastro.

    Camadas executadas:
      1. Formato  (sempre)
      2. DNS/MX   (sempre, graciosa em timeout)
      3. API ext  (se EMAIL_VALIDATION_USE_API=True, graciosa em falha)
      4. SMTP     (se EMAIL_SMTP_ENABLED=True, graciosa em falha)

    Resultados são cacheados por EMAIL_VALIDATION_CACHE_TTL segundos (padrão 24 h).
    """
    email = email.strip().lower()
    cache_key = f'email_validation:{email}'

    cached = cache.get(cache_key)
    if cached is not None:
        logger.debug('Cache hit para validação de e-mail (domínio %s)', email.rsplit('@', 1)[-1])
        return cached

    # — Camada 1: Formato
    result = validate_format(email)
    if not result.is_valid:
        # Formato inválido não é cacheado (usuário pode corrigir o typo)
        return result

    # — Camada 2: DNS
    result = validate_dns(email)
    if not result.is_valid:
        cache.set(cache_key, result, _CACHE_TTL)
        return result

    # — Camada 3: API externa (mais rápida e confiável que SMTP)
    result = validate_external_api(email)
    if not result.is_valid:
        cache.set(cache_key, result, _CACHE_TTL)
        return result

    # — Camada 4: SMTP (opcional, mais lento)
    result = validate_smtp(email)
    if not result.is_valid:
        cache.set(cache_key, result, _CACHE_TTL)
        return result

    # Tudo ok
    final = EmailValidationResult(is_valid=True, layer='all', message='')
    cache.set(cache_key, final, _CACHE_TTL)
    return final
