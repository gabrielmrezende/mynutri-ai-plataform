# Documentação da API — MyNutri AI

**Base URL:** `http://127.0.0.1:8000/api/v1`

Todos os endpoints protegidos exigem o header:
```
Authorization: Bearer <access_token>
```

---

## Autenticação

### Criar conta

`POST /api/v1/auth/register`

**Permissão:** Pública (sem token)

**Body (JSON):**
```json
{
  "nome": "Gabriel Rezende",
  "email": "gabriel@exemplo.com",
  "senha": "minhasenha123"
}
```

> `senha` deve ter no mínimo 8 caracteres.

**Resposta 201 Created:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": 1,
    "email": "gabriel@exemplo.com",
    "nome": "Gabriel"
  }
}
```

**Resposta 400 Bad Request:**
```json
{ "email": ["Este email já está em uso."] }
```

---

### Login

`POST /api/v1/auth/login`

**Permissão:** Pública (sem token)

**Body (JSON):**
```json
{
  "email": "gabriel@exemplo.com",
  "password": "minhasenha123"
}
```

> Atenção: o campo é `password`, não `senha`.

**Resposta 200 OK:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Resposta 401 Unauthorized:**
```json
{ "detail": "No active account found with the given credentials" }
```

---

### Renovar Token

`POST /api/v1/auth/token/refresh`

**Permissão:** Pública (sem token)

**Body (JSON):**
```json
{ "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```

**Resposta 200 OK:**
```json
{ "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```

---

## Usuário

### Obter perfil

`GET /api/v1/user/profile`

**Permissão:** JWT obrigatório

**Resposta 200 OK:**
```json
{
  "id": 1,
  "nome": "Gabriel Rezende",
  "email": "gabriel@exemplo.com",
  "phone": "",
  "date_of_birth": null,
  "date_joined": "2026-03-30T15:00:00Z"
}
```

---

### Atualizar perfil

`PATCH /api/v1/user/profile`

**Permissão:** JWT obrigatório

**Body (JSON — campos opcionais):**
```json
{
  "first_name": "Gabriel",
  "last_name": "Rezende",
  "phone": "(11) 99999-9999",
  "date_of_birth": "2000-05-15"
}
```

**Resposta 200 OK:** Retorna o perfil atualizado (mesmo formato do GET).

---

## Anamnese

### Enviar questionário nutricional

`POST /api/v1/anamnese`

**Permissão:** JWT obrigatório

**Body (JSON):**
```json
{
  "idade": 25,
  "sexo": "M",
  "peso": 70.5,
  "altura": 175.0,
  "nivel_atividade": "moderate",
  "objetivo": "lose",
  "meals_per_day": 5,
  "restricoes": "vegetariano, gluten",
  "food_preferences": "Frango, Arroz Integral, Brócolis",
  "allergies": "amendoim"
}
```

**Valores aceitos:**

| Campo | Valores válidos |
|-------|----------------|
| `sexo` | `"M"`, `"F"`, `"O"` |
| `nivel_atividade` | `"sedentary"`, `"light"`, `"moderate"`, `"intense"`, `"athlete"` |
| `objetivo` | `"lose"`, `"maintain"`, `"gain"` |

> Os campos `restricoes`, `food_preferences` e `allergies` são opcionais (string, máx. 500 chars).

**Resposta 201 Created:**
```json
{
  "id": 3,
  "idade": 25,
  "sexo": "M",
  "peso": "70.50",
  "altura": "175.00",
  "nivel_atividade": "moderate",
  "objetivo": "lose",
  "restricoes": "vegetariano, gluten",
  "food_preferences": "Frango, Arroz Integral, Brócolis",
  "allergies": "amendoim",
  "meals_per_day": 5,
  "answered_at": "2026-03-31T23:00:00Z"
}
```

**Resposta 400 Bad Request:**
```json
{ "nivel_atividade": ["\"moderado\" is not a valid choice."] }
```

---

## Dieta

### Gerar dieta via IA

`POST /api/v1/diet/generate`

**Permissão:** JWT obrigatório  
**Rate limit:** 3 requisições por dia por usuário

**Body:** Nenhum (usa a última Anamnese registrada do usuário)

**Resposta 201 Created:**
```json
{
  "id": 7,
  "calorias_totais": 2100,
  "goal_description": "Emagrecimento",
  "refeicoes": [
    {
      "nome_refeicao": "Café da manhã",
      "descricao_refeicao": "3 ovos mexidos + 2 fatias de pão integral + café sem açúcar",
      "calorias_estimadas": 380,
      "order": 0
    },
    {
      "nome_refeicao": "Almoço",
      "descricao_refeicao": "150g frango grelhado + 150g arroz integral + salada de folhas",
      "calorias_estimadas": 550,
      "order": 1
    }
  ],
  "created_at": "2026-03-31T23:05:00Z"
}
```

**Resposta 400 Bad Request (sem anamnese):**
```json
{ "error": "Nenhuma anamnese encontrada. Responda o questionário primeiro." }
```

**Resposta 429 Too Many Requests (rate limit):**
```json
{ "detail": "Request was throttled. Expected available in 86400 seconds." }
```

**Resposta 500 Internal Server Error:**
```json
{ "error": "Falha ao gerar o plano alimentar via IA, tente novamente mais tarde." }
```

---

### Buscar última dieta

`GET /api/v1/diet`

**Permissão:** JWT obrigatório

**Resposta 200 OK:** Mesmo formato do `POST /api/v1/diet/generate`.

**Resposta 404 Not Found:**
```json
{ "error": "Você ainda não possui um plano alimentar gerado." }
```

---

## Health Check

### Status do servidor

`GET /health/`

**Permissão:** Pública (sem token)

**Resposta 200 OK:**
```json
{ "status": "ok" }
```

**Resposta 503 Service Unavailable:**
```json
{ "status": "error" }
```