# Arquitetura do Sistema — MyNutri AI

## Visão Geral

O MyNutri AI é uma plataforma web SaaS que gera planos alimentares personalizados via IA.
A arquitetura segue o padrão de **3 camadas** com separação completa entre Frontend e Backend (API REST).

---

## Camadas

### 1. Frontend (Estático)

Responsável exclusivamente pela interface do usuário. Não possui lógica de negócio.

**Páginas:**
| Arquivo | Rota | Descrição |
|---------|------|-----------|
| `index.html` | `/` | Landing Page com CTA |
| `auth.html` | `/auth` | Login e Cadastro (tabs) |
| `questionario.html` | `/questionario` | Questionário em 5 steps |
| `dieta.html` | `/dieta` | Exibição do plano alimentar |
| `perfil.html` | `/perfil` | Perfil do usuário |
| `contato.html` | `/contato` | Página de contato |
| `privacidade.html` | `/privacidade` | Política de privacidade |
| `termos.html` | `/termos` | Termos de uso |

**Tecnologias:** HTML5 + CSS3 + JavaScript vanilla (fetch API)
**Serve em:** qualquer servidor HTTP estático (ex: `python -m http.server 5500`)

---

### 2. Backend (API REST)

Responsável por toda a lógica de negócio, autenticação e integração com a IA.

**Framework:** Django 6.x + Django REST Framework
**Autenticação:** SimpleJWT (Bearer Token)
**Base URL:** `http://127.0.0.1:8000/api/v1/`

**Apps Django:**

| App | Responsabilidade |
|-----|-----------------|
| `user` | CustomUser, Profile, autenticação JWT, serializers |
| `nutrition` | Anamnese, DietPlan, Meal, integração com IA |
| `mynutri` | Configurações globais, URL root |

**Rotas expostas:**
```
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/token/refresh
GET    /api/v1/user/profile
PATCH  /api/v1/user/profile
POST   /api/v1/anamnese
POST   /api/v1/diet/generate
GET    /api/v1/diet
GET    /health/
```

---

### 3. Banco de Dados

**Desenvolvimento:** SQLite (`db.sqlite3`)
**Produção:** PostgreSQL (configurar via `DATABASE_URL` no `.env`)

**Tabelas:**
| Modelo | App | Descrição |
|--------|-----|-----------|
| `CustomUser` | `user` | Extends `AbstractUser` — usa email como login |
| `Profile` | `user` | Dados nutricionais vinculados ao usuário |
| `Anamnese` | `nutrition` | Respostas do questionário nutricional |
| `DietPlan` | `nutrition` | Plano alimentar gerado pela IA (JSON + campos extraídos) |
| `Meal` | `nutrition` | Refeições individuais de um DietPlan |

---

## Fluxo Principal do Usuário

```
index.html
    └── Clica "Começar"
           └── auth.html (Cadastro/Login)
                  └── [Token JWT salvo no localStorage]
                         └── questionario.html (5 steps)
                                └── POST /api/v1/anamnese
                                       └── Redireciona para dieta.html?generate=1
                                              └── POST /api/v1/diet/generate
                                                     └── AIService → API IA → DietPlan salvo
                                                            └── Exibe refeições + calorias
```

---

## Integração com IA

- **Arquivo:** `nutrition/services.py` (`AIService`)
- **Arquivo:** `nutrition/prompts.py` (prompt dinâmico)
- **Protocolo:** HTTP POST para qualquer API OpenAI-compatible
- **Timeout:** 120 segundos
- **Rate limit:** 3 gerações por dia por usuário (via DRF `ScopedRateThrottle`)
- **Formato de resposta:** JSON estruturado com array `refeicoes[]`

---

## Decisões de Design

| Decisão | Justificativa |
|---------|--------------|
| Frontend separado do Django | Independência de deploy; frontend pode ir para CDN |
| JWT via SimpleJWT | Stateless, seguro, suporta refresh tokens |
| `CustomUser` com email como username | Evita campos duplicados e melhora UX |
| Anamnese separada do Profile | Permite múltiplas sessões de resposta; histórico preservado |
| `raw_response` JSONField | Preserva resposta completa da IA para reprocessamento futuro |
| SQLite em dev | Zero configuração; migration para PostgreSQL é transparente com Django |