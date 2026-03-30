# Documentação da API - MyNutri AI

## Visão Geral

A API é responsável por conectar o frontend com o backend e executar as operações do sistema.

---

## Autenticação

### Criar conta

POST /api/auth/register

Body:

{
  "nome": "string",
  "email": "string",
  "senha": "string"
}

---

### Login

POST /api/auth/login

Body:

{
  "email": "string",
  "senha": "string"
}

---

## Usuário

### Obter perfil

GET /api/user/profile

---

## Anamnese

### Enviar respostas da anamnese

POST /api/anamnese

Body:

{
  "idade": 25,
  "sexo": "masculino",
  "peso": 70,
  "altura": 175,
  "nivel_atividade": "moderado",
  "objetivo": "ganho de massa",
  "restricoes": "nenhuma"
}

---

## Dieta

### Gerar dieta

POST /api/diet/generate

Descrição:

Envia os dados da anamnese para a IA e retorna um plano alimentar personalizado.

---

### Buscar dieta do usuário

GET /api/diet