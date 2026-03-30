# Documentação da API - MyNutri AI

## Visão Geral

A API é responsável por conectar o frontend com o backend e executar as operações do sistema.

---

## Autenticação

### Criar conta

`POST /api/auth/register`

**Body (JSON):**
```json
{
  "nome": "string",
  "email": "string",
  "senha": "string"
}
```

**Respostas:**
- `201 Created`: Usuário criado com sucesso e retorna o token de acesso.
- `400 Bad Request`: Falha na validação (ex: e-mail já existe). 
  ```json
  { "error": "Este email já está em uso." }
  ```

---

### Login

`POST /api/auth/login`

**Body (JSON):**
```json
{
  "email": "string",
  "senha": "string"
}
```

**Respostas:**
- `200 OK`: Login bem sucedido, retorna o token de autenticação JWT/Session.
  ```json
  { "token": "eyJh..." }
  ```
- `401 Unauthorized`: E-mail ou senha incorretos.
  ```json
  { "error": "Credenciais inválidas." }
  ```

---

## Usuário

### Obter perfil

`GET /api/user/profile`

**Headers (Auth):** `Authorization: Bearer <token>`

**Respostas:**
- `200 OK`: Retorna os dados do usuário atual.
- `401 Unauthorized`: Token não enviado ou expirado.
- `404 Not Found`: Usuário não encontrado no banco.

---

## Anamnese

### Enviar respostas da anamnese

`POST /api/anamnese`

**Headers (Auth):** `Authorization: Bearer <token>`

**Body (JSON):**
```json
{
  "idade": 25,
  "sexo": "masculino",
  "peso": 70,
  "altura": 175,
  "nivel_atividade": "moderado",
  "objetivo": "ganho de massa",
  "restricoes": "nenhuma"
}
```

**Respostas:**
- `201 Created`: Anamnese salva com sucesso.
- `400 Bad Request`: Faltando campos obrigatórios no formulário.

---

## Dieta

### Gerar dieta

`POST /api/diet/generate`

**Headers (Auth):** `Authorization: Bearer <token>`

**Descrição:**
Gatilho que aciona a IA, envia os dados da última anamnese do usuário e processa a geração.

**Respostas:**
- `201 Created`: Dieta gerada com sucesso. Retorna o ID ou objeto do novo plano alimentar.
- `500 Server Error`: Falha de comunicação com a API da Inteligência Artificial.
  ```json
  { "error": "Falha ao gerar o plano alimentar via IA, tente novamente mais tarde." }
  ```

---

### Buscar dieta do usuário

`GET /api/diet`

**Headers (Auth):** `Authorization: Bearer <token>`

**Respostas:**
- `200 OK`: Retorna o plano alimentar ativo estruturado.
- `404 Not Found`: Usuário logado ainda não possui uma dieta gerada.