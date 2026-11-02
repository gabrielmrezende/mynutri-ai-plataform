"""
Cliente HTTP da API de IA (compatível com OpenAI chat/completions).

- HTTP 4xx (exceto 429): PermanentAIError, sem retry
- HTTP 429/5xx, erro de rede, resposta não-JSON: retry com Retry-After ou
  backoff exponencial + jitter; esgotado → TransientAIError
- Nunca loga conteúdo do LLM nem a resposta completa — apenas tamanhos,
  códigos e consumo de tokens.
"""

import json
import logging
import os
import random
import time
import urllib.error
import urllib.request

from django.conf import settings

from .errors import PermanentAIError, TransientAIError

logger = logging.getLogger('nutrition.services')

# Retry da API de IA
RETRY_AFTER_MAX_S = 30      # teto para o header Retry-After
RETRY_JITTER_MAX_S = 1.0    # jitter aleatório somado ao backoff


def _setting(name: str, default: str = '') -> str:
    """Lê configuração de settings (preferencial) com fallback para variável de ambiente."""
    return getattr(settings, name, None) or os.getenv(name, default)


class AIClient:
    """
    Base do AIService com a comunicação HTTP.

    Configuração (settings do Django, com fallback para variável de ambiente):
        AI_API_KEY  → chave de autenticação
        AI_API_URL  → endpoint (ex: https://api.openai.com/v1/chat/completions)
        AI_MODEL    → modelo (padrão: gpt-4o-mini)
    """

    def __init__(self):
        self.api_key = _setting('AI_API_KEY')
        self.api_url = _setting('AI_API_URL')
        self.model   = _setting('AI_MODEL', 'gpt-4o-mini')

    # ──────────────────────────────────────────────────────────────────────────
    #  HTTP
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _retry_wait(attempt: int, retry_after=None) -> float:
        """
        Tempo de espera antes da próxima tentativa: Retry-After (segundos, com
        teto) quando informado pela API; senão backoff exponencial. Sempre
        soma jitter aleatório para não sincronizar workers concorrentes.
        """
        base = None
        if retry_after is not None:
            try:
                base = min(float(retry_after), RETRY_AFTER_MAX_S)
            except (TypeError, ValueError):
                base = None  # Retry-After em formato de data — usa backoff
            if base is not None and base < 0:
                base = None
        if base is None:
            base = float(2 ** attempt)
        return base + random.uniform(0, RETRY_JITTER_MAX_S)

    def _log_usage(self, api_response: dict) -> None:
        """Registra o consumo de tokens informado pela API (sem conteúdo)."""
        usage = api_response.get('usage') if isinstance(api_response, dict) else None
        if isinstance(usage, dict):
            logger.info(
                '[AI_USAGE] modelo=%s tokens: prompt=%s completion=%s total=%s',
                self.model, usage.get('prompt_tokens'), usage.get('completion_tokens'),
                usage.get('total_tokens'),
            )

    def _call_api(
        self,
        user_prompt: str,
        system_prompt: str,
        temperature: float = 0.3,
        json_mode: bool = True,
        max_retries: int = 3,
        max_tokens: int | None = None,
    ) -> dict:
        """
        Realiza chamada à API de IA com retry em erros transitórios.

        - HTTP 4xx (exceto 429): PermanentAIError, sem retry
        - HTTP 429/5xx, erro de rede, resposta não-JSON: retry com Retry-After
          ou backoff exponencial + jitter; esgotado → TransientAIError
        Mensagens das exceções não contêm URL, chave nem corpo da resposta.
        """
        if not self.api_key or not self.api_url:
            logger.error('[AI_CONFIG] AI_API_KEY/AI_API_URL não configurados.')
            raise PermanentAIError('O serviço de IA não está configurado. Contate o suporte.')

        body: dict = {
            'model':       self.model,
            'messages':    [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user',   'content': user_prompt},
            ],
            'temperature': temperature,
        }
        if max_tokens is not None:
            body['max_tokens'] = max_tokens
        if json_mode:
            body['response_format'] = {'type': 'json_object'}

        payload = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(
            self.api_url,
            data=payload,
            headers={
                'Content-Type':  'application/json',
                'Authorization': f'Bearer {self.api_key}',
            },
            method='POST',
        )

        for attempt in range(max_retries):
            retry_after = None
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    raw = response.read()
                try:
                    data = json.loads(raw.decode('utf-8'))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    reason = 'resposta não-JSON'
                else:
                    self._log_usage(data)
                    return data
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    reason = f'HTTP {e.code}'
                    retry_after = e.headers.get('Retry-After') if e.headers else None
                else:
                    logger.error('[AI_HTTP] API de IA recusou a requisição: HTTP %s (sem retry).', e.code)
                    raise PermanentAIError(
                        'O serviço de IA recusou a requisição. Tente novamente mais tarde '
                        'ou contate o suporte.'
                    ) from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                reason = type(e).__name__

            if attempt < max_retries - 1:
                wait = self._retry_wait(attempt, retry_after)
                logger.warning(
                    '[AI_RETRY] Falha transitória (%s) na tentativa %d/%d — aguardando %.1fs',
                    reason, attempt + 1, max_retries, wait,
                )
                time.sleep(wait)
            else:
                logger.error('[AI_RETRY] Falha transitória (%s) — tentativas esgotadas (%d).', reason, max_retries)

        raise TransientAIError(
            'O serviço de IA está temporariamente indisponível. Tente novamente em alguns minutos.'
        )

    def _parse_response(self, api_response: dict) -> dict:
        """
        Extrai e parseia o JSON gerado pela IA. Nunca loga o conteúdo
        (pode conter dados do usuário) — apenas tamanho e tipo do erro.
        """
        try:
            content = api_response['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError) as e:
            logger.error('[AI_FORMAT] Formato inesperado da API de IA (%s).', type(e).__name__)
            raise TransientAIError('A IA retornou um formato inesperado. Tente novamente.')

        if not isinstance(content, str):
            logger.error('[AI_FORMAT] Conteúdo da IA não é texto (%s).', type(content).__name__)
            raise TransientAIError('A IA retornou um formato inesperado. Tente novamente.')

        stripped = content.strip()
        # Remove markdown code fences caso a API não suporte json_mode
        if stripped.startswith('```'):
            lines = stripped.split('\n')
            inner = lines[1:]
            if inner and inner[-1].strip() == '```':
                inner = inner[:-1]
            stripped = '\n'.join(inner)

        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as e:
            logger.error(
                '[AI_FORMAT] JSON inválido da IA (%s, posição %d, %d caracteres).',
                e.msg, e.pos, len(content),
            )
            raise TransientAIError('A IA retornou um formato inesperado. Tente novamente.')
        if not isinstance(parsed, dict):
            logger.error('[AI_FORMAT] JSON da IA não é objeto (%s).', type(parsed).__name__)
            raise TransientAIError('A IA retornou um formato inesperado. Tente novamente.')
        return parsed
