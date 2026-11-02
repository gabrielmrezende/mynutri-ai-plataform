# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Comandos essenciais

```bash
# Instalar dependências (produção + testes/lint)
pip install -r requirements-dev.txt   # requirements.txt contém só as de produção

# Rodar o servidor backend (API + frontend servido pelo Django)
python manage.py runserver

# Migrations
python manage.py makemigrations
python manage.py migrate

# Todos os testes
pytest

# Testes de um app específico
pytest nutrition/
pytest user/

# Um teste específico
pytest nutrition/tests/test_services.py::NomeDoTeste

# Cobertura (CI exige >= 85%) e lint
pytest --cov --cov-fail-under=85
ruff check .

# Verificar configuração Django
python manage.py check
python manage.py check --deploy   # checklist de produção (precisa das env vars de produção)
python manage.py makemigrations --check --dry-run

# E2E (Playwright) — sobe o Django com SQLite em arquivo (TEST_DB_PATH)
npm ci && npx playwright install chromium && npx playwright test
```

> Os testes usam `mynutri/test_settings.py`, que **herda de `settings.py`** definindo env vars fake antes do import (SQLite in-memory ou arquivo via `TEST_DB_PATH`, throttle global desabilitado, Celery eager, cache local). Configurado via `pytest.ini` (`testpaths = nutrition user`). Ruff e cobertura são configurados em `pyproject.toml`.

## Arquitetura

### Separação Frontend / Backend

O frontend é HTML/CSS/JS vanilla servido pelo próprio Django via `TemplateView`. As páginas ficam em `frontend/public/` e são mapeadas em `mynutri/urls.py`. Em produção, WhiteNoise serve os assets estáticos.

A API segue o prefixo `/api/v1/` e é dividida em dois grupos de rotas:
- `user/urls_api.py` → autenticação (JWT + Google OAuth), perfil, troca de senha, contato, depoimentos
- `nutrition/urls_api.py` → anamnese, geração assíncrona de dieta, histórico, PDF, substituições, regeneração de refeição

### Autenticação

`CustomUser` (`user/models.py`) estende `AbstractUser` usando **email como username** (o campo `username` é preenchido automaticamente com o email). `EmailTokenObtainPairView` sobrescreve o login padrão do SimpleJWT para aceitar `{ email, password }` em vez de `{ username, password }`. Os tokens retornados usam o campo `token` (não `access`) para consistência com o endpoint de registro.

### Fluxo de geração de dieta (assíncrono)

1. Usuário preenche o questionário → `POST /api/v1/anamnese` salva `Anamnese`
2. Frontend redireciona para `dieta.html?generate=1` → `POST /api/v1/diet/generate`
3. `DietGenerateAPIView` cria um `DietJob` (status=pending) e enfileira a task Celery; retorna `{ job_id }`
4. Frontend faz polling em `GET /api/v1/diet/status/<job_id>` até `status=done`
5. Worker Celery chama `AIService.generate_diet(anamnese)` em `nutrition/services.py`:
   - **Passo 1** (temp=0.55): LLM seleciona alimentos e quantidades (sem calcular macros)
   - **Backend**: `nutrition_db.py` calcula macros deterministicamente; `_adjust_to_calorie_target()` escala porções se desvio > 10%; `_round_portions()` arredonda para medidas práticas (11+ regras por categoria); `_enforce_allergies()` rejeita alérgenos; `_validate_macro_ratios()` valida limites fisiológicos
   - **Substituições**: `generate_meal_substitutions()` gera substituições sem IA
   - **Passos 2+3** em paralelo (temp=0.7): `_generate_notes()` e `_generate_explanation()` via `ThreadPoolExecutor`
6. `DietPlan` e múltiplos `Meal` são criados em bulk; `DietJob.status` atualizado para `done` — tudo na mesma `transaction.atomic()` em `nutrition/tasks.py`

Robustez do job (`nutrition/tasks.py` + `nutrition/views.py`):
- A task é enfileirada via `transaction.on_commit`; se o broker falhar, o job vira `failed` na hora.
- `acks_late=True`, `soft_time_limit` 8 min / `time_limit` 9 min; transição `pending→processing` e conclusão são **updates condicionais** (sem execução duplicada nem sobrescrita de job expirado).
- `expire_stale_jobs()` marca `failed` jobs `pending` > 10 min e `processing` > 15 min (chamado no generate e no polling).
- `TransientAIError` → retry (2x, 15 s); `error_message` guarda só mensagens amigáveis por classe de exceção (`tasks.user_message_for`) — detalhe técnico apenas no log.
- Cota de geração: `DIET_GENERATE_DAILY_LIMIT` (3/24 h) conta só jobs não falhos; o throttle DRF `diet_generate` é anti-abuso (10/dia).

### Regeneração pontual de refeição

- `PATCH /api/v1/diet/<diet_id>/meal/<meal_id>/regenerate` → `MealRegenerateAPIView`
- Rate limit: 3 regenerações por **dia local** por `DietPlan` (contado via `MealRegenerationLog`, **incluindo as desfeitas**)
- A cota é reservada sob `select_for_update` antes da chamada à IA (log com `is_undone=True` = reserva pendente); se a IA falhar, a reserva é apagada. A aplicação relê `raw_response` sob lock.
- Estado anterior salvo em `MealRegenerationLog` para suportar undo
- `POST /api/v1/diet/<diet_id>/meal/<meal_id>/undo` → `MealUndoAPIView` restaura o estado anterior (não devolve cota)
- `GET /api/v1/diet` e `/diet/<id>` incluem `regenerations_remaining_today`

### Modelos de dados

- `CustomUser` → `Profile` (OneToOne, criado automaticamente no registro)
- `CustomUser` → `Testimonial[]` (depoimentos da landing page — `user/models.py`)
- `CustomUser` → `Anamnese[]` (múltiplas por usuário; a mais recente é usada para geração)
- `Anamnese` → `DietJob[]` (SET_NULL se anamnese deletada)
- `DietJob` → `DietPlan` (OneToOne, SET_NULL; rastreia estado pending→processing→done/failed)
- `DietPlan` → `Meal[]` (bulk_create; campo `order` define a sequência)
- `DietPlan` → `MealRegenerationLog[]` (histórico de regenerações com JSON anterior para undo)
- `DietPlan.raw_response` armazena o JSON completo (enriquecido com macros do backend)

### Rate limiting

Configurado no DRF via `DEFAULT_THROTTLE_RATES` em `settings.py` (`NUM_PROXIES` via env, padrão 1):
- `diet_generate`: 10/dia (ScopedRateThrottle, anti-abuso) + cota de negócio `DIET_GENERATE_DAILY_LIMIT`
- `job_status`: 1200/hora (polling do status a cada 3 s)
- `anamnese`: 20/hora
- `contact`: 5/hora (AnonRateThrottle customizado)
- `user`: 300/hora, `anon`: 20/hora (globais)

O throttle usa o cache: em produção usa Redis (`CACHE_URL`) ou, sem ele, `DatabaseCache` no Postgres — nunca LocMemCache, em que cada processo teria seu próprio contador.

Em testes, o throttle é desabilitado (`DEFAULT_THROTTLE_CLASSES: []`); o cache é limpo entre cada teste via fixture `autouse` em `conftest.py`.

### Variáveis de ambiente obrigatórias

`settings.py` valida `SECRET_KEY`, `AI_API_KEY`, `AI_API_URL`, `DATABASE_URL` e `GOOGLE_CLIENT_ID` na inicialização e lança `ValueError` se ausentes. Com `DEBUG=False` e sem `CACHE_URL` (Redis), o cache usa `DatabaseCache` no Postgres (rode `python manage.py createcachetable` no deploy) para o rate limiting ser compartilhado entre processos. Para testes, usar `mynutri/test_settings.py` (não requer `.env`).

### Segurança HTTP

`mynutri/middleware.py` (`SecurityHeadersMiddleware`) aplica CSP **enforcing**, `Permissions-Policy` e `Referrer-Policy` em todas as respostas. A CSP só permite scripts de `'self'` e `https://accounts.google.com`: **nada de `<script>` inline nem handlers inline (`onclick=`)** no frontend. O Sentry tem `before_send` que remove corpo de requisição, cookies e dados de anamnese.

### Deploy

O arquivo `render.yaml` define a infraestrutura no Render (Web Service, Worker Celery e Key Value/Redis). O banco de dados é **exclusivamente o PostgreSQL do Supabase** (projeto `mynutri-ai-plataform`, ref `rmtipuzswcdcfothkxmr`), em dev e em produção: `DATABASE_URL` deve apontar para o Session pooler (porta 5432, IPv4); não há fallback para SQLite. O schema é gerenciado pelas migrations do Django (`python manage.py migrate`), não por migrations do Supabase. O `build.sh` instala dependências, roda `collectstatic` (storage `STORAGES['staticfiles']` = `CompressedManifestStaticFilesStorage`) e `check --deploy`; o `migrate` roda no `startCommand`. Health check em `/health/`. `robots.txt` e `sitemap.xml` são servidos por `mynutri/urls.py`.
