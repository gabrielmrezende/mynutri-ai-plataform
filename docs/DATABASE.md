# Modelagem do Banco de Dados - MyNutri AI

## Visão Geral

O banco de dados é responsável por armazenar todas as informações da aplicação, incluindo dados dos usuários, respostas da anamnese e planos alimentares gerados.

### Diagrama de Entidade-Relacionamento (ERD)

```mermaid
erDiagram
    users ||--o{ anamnese : "responde"
    users ||--o{ diet_plans : "possui"
    anamnese ||--o| diet_plans : "gera"
    diet_plans ||--o{ meals : "contém"

    users {
        int id PK
        string nome
        string email
        string senha_hash
        datetime data_criacao
    }
    
    anamnese {
        int id PK
        int user_id FK
        int idade
        string sexo
        float peso
        float altura
        string nivel_atividade
        string objetivo
        string restricoes_alimentares
        string preferencias_alimentares
        datetime data_resposta
    }
    
    diet_plans {
        int id PK
        int user_id FK
        int anamnese_id FK
        json dieta_gerada
        int calorias_totais
        datetime data_criacao
    }
    
    meals {
        int id PK
        int diet_plan_id FK
        string nome_refeicao
        string descricao_refeicao
        int calorias
    }
```

---

## Tabela: users

Armazena informações básicas dos usuários.

Campos:

- id
- nome
- email
- senha_hash
- data_criacao

---

## Tabela: anamnese

Armazena as respostas do questionário nutricional.

Campos:

- id
- user_id
- idade
- sexo
- peso
- altura
- nivel_atividade
- objetivo
- restricoes_alimentares
- preferencias_alimentares
- data_resposta

Relacionamento:

anamnese.user_id → users.id

---

## Tabela: diet_plans

Armazena os planos alimentares gerados pela IA.

Campos:

- id
- user_id
- anamnese_id
- dieta_gerada
- calorias_totais
- data_criacao

Relacionamentos:

diet_plans.user_id → users.id  
diet_plans.anamnese_id → anamnese.id

---

## Tabela: meals

Armazena refeições individuais de um plano alimentar.

Campos:

- id
- diet_plan_id
- nome_refeicao
- descricao_refeicao
- calorias

Relacionamento:

meals.diet_plan_id → diet_plans.id