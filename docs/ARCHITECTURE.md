# Arquitetura do Sistema - MyNutri AI

## Visão Geral

O MyNutri AI é uma plataforma web que utiliza Inteligência Artificial para gerar planos alimentares personalizados com base em uma anamnese nutricional realizada pelo usuário.

A arquitetura do sistema é dividida em três camadas principais:

- Frontend
- Backend
- Banco de Dados

---

## Frontend

Responsável pela interface do usuário.

Funções principais:

- Cadastro e login de usuários
- Interface para responder a anamnese
- Exibição da dieta gerada
- Dashboard do usuário
- Histórico de dietas

Tecnologias possíveis:

- HTML
- CSS
- JavaScript
- React (possível evolução)

---

## Backend

Responsável pela lógica da aplicação.

Funções principais:

- Autenticação de usuários
- Processamento da anamnese
- Comunicação com o modelo de IA
- Geração do plano alimentar
- Gerenciamento de usuários e dietas

Tecnologias possíveis:

- Python
- Flask ou Django

---

## Banco de Dados

Responsável por armazenar os dados da aplicação.

Dados armazenados:

- Usuários
- Respostas da anamnese
- Planos alimentares gerados
- Histórico de dietas

Tecnologias possíveis:

- PostgreSQL
- MySQL
- SQLite (para desenvolvimento)

---

## Fluxo do Usuário

1. Usuário cria uma conta
2. Usuário faz login
3. Usuário responde o questionário de anamnese
4. Backend envia dados para o sistema de IA
5. A IA gera um plano alimentar personalizado
6. O plano é salvo no banco de dados
7. O usuário visualiza sua dieta na plataforma