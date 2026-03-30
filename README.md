# 🥗 MyNutri AI

Plataforma inteligente para geração de **planos alimentares personalizados** utilizando **Inteligência Artificial**.

O **MyNutri AI** permite que usuários respondam um questionário nutricional e, com base nas respostas fornecidas, a plataforma gera automaticamente uma sugestão de plano alimentar personalizado.

O objetivo do projeto é facilitar o acesso a orientações alimentares iniciais de forma rápida, organizada e baseada em dados.

---

# 🚀 Funcionalidades

* 📋 Questionário nutricional inteligente
* 🤖 Geração automática de dieta com Inteligência Artificial
* 🎯 Planos alimentares personalizados
* 📊 Estrutura de refeições diárias
* 🧠 Análise de objetivos do usuário (emagrecimento, hipertrofia, manutenção)
* 📱 Interface moderna e responsiva
* 🎨 Design clean com cores claras (branco e verde)

---

# 🎯 Objetivo do Projeto

O **MyNutri AI** foi criado para ajudar usuários a organizarem sua alimentação de forma prática utilizando tecnologia e inteligência artificial.

A plataforma coleta informações importantes como:

* idade
* peso
* altura
* nível de atividade física
* objetivo corporal
* restrições alimentares
* preferências alimentares
* frequência de exercícios

Com base nesses dados, o sistema gera um plano alimentar estruturado.

⚠️ **Aviso:**
A plataforma **não substitui a orientação de um nutricionista profissional**.

---

# 🛠️ Tecnologias Utilizadas

## Frontend

* HTML
* CSS
* JavaScript
* React *(planejado)*

## Backend

* Python
* Flask / Django

## Banco de Dados

* PostgreSQL
* Supabase

## Inteligência Artificial

* API de IA para geração de dietas personalizadas

## Ferramentas

* Git
* GitHub
* Trello (organização do projeto)
* Replit / Cursor / Claude Code (assistência de desenvolvimento)

---

# 🚀 Como Rodar o Projeto (Setup Local)

### Pré-requisitos
* Python 3.10+
* Git
* Node.js (opcional, para testes de interface front-end)

### Passo a passo

1. **Clone o repositório:**
   ```bash
   git clone https://github.com/SEU_USUARIO/mynutri-ai-plataform.git
   cd mynutri-ai-plataform
   ```

2. **Crie e ative o ambiente virtual (Backend Python):**
   ```bash
   python -m venv venv
   # No Windows:
   venv\Scripts\activate
   # No Linux/Mac:
   source venv/bin/activate
   ```

3. **Instale as dependências:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configuração de Variáveis de Ambiente:**
   Copie o arquivo de exemplo e crie o seu `.env` oficial.
   ```bash
   cp .env.example .env
   ```
   **Importante:** Abra o `.env` gerado e preencha as chaves necessárias (ex: `SECRET_KEY`, url do banco de dados e a sua chave da **OpenAI** ou **Gemini**). O sistema não funcionará corretamente com a IA sem as chaves válidas configuradas aqui.

5. **Execute as migrações do banco de dados:**
   ```bash
   python manage.py migrate
   ```

6. **Inicie o servidor de desenvolvimento:**
   ```bash
   python manage.py runserver
   ```
   A aplicação estará rodando em `http://127.0.0.1:8000/`.

---

# 📂 Estrutura do Projeto

```
MyNutri-AI
│
├── frontend
│   ├── public
│   ├── src
│   └── styles
│
├── backend
│   ├── app
│   ├── routes
│   ├── services
│   └── models
│
├── database
│
├── docs
│   ├── architecture.md
│   ├── database.md
│   ├── roadmap.md
│   ├── api.md
│   ├── prompts.md
│   ├── ideas.md
│   └── git_conventions.md
│
└── README.md
```

---

# 📋 Questionário Nutricional

A plataforma utiliza um questionário para entender o perfil do usuário.

Exemplos de perguntas:

* Qual sua idade?
* Qual seu peso atual?
* Qual sua altura?
* Qual seu objetivo principal?
* Quantas vezes por semana você treina?
* Você possui restrições alimentares?
* Possui alergias alimentares?
* Quais alimentos você prefere?
* Quantas refeições faz por dia?

Essas informações são utilizadas para gerar um plano alimentar personalizado.

---

# 🧠 Como funciona a geração da dieta

1️⃣ O usuário responde o questionário nutricional
2️⃣ O sistema analisa os dados fornecidos
3️⃣ A IA processa as informações
4️⃣ O sistema gera um plano alimentar estruturado

Exemplo de divisão do plano alimentar:

* Café da manhã
* Lanche da manhã
* Almoço
* Lanche da tarde
* Jantar
* Ceia (opcional)

---

# 📚 Documentação

A documentação detalhada do projeto está disponível na pasta **docs/**.

Ela inclui:

* Arquitetura do sistema
* Modelagem do banco de dados
* Estrutura da API
* Roadmap do projeto
* Prompts utilizados pela IA
* Convenções de Git

---

# 🔒 Segurança e Boas Práticas

Este projeto segue algumas boas práticas de desenvolvimento:

* Proteção da branch `main`
* Uso de **feature branches**
* **Pull Requests** para revisão de código
* Versionamento com Git
* Variáveis sensíveis armazenadas em `.env`

---

# 📈 Futuras Melhorias

* 📊 Cálculo automático de calorias e macronutrientes
* 🥗 Banco de dados com mais de 200 alimentos
* 📄 Exportação do plano alimentar em PDF
* 📱 Aplicativo mobile
* 👩‍⚕️ Área para nutricionistas
* 📊 Dashboard de acompanhamento alimentar
* 🤖 Melhorias no modelo de IA

---

# ⚠️ Aviso Legal

O **MyNutri AI** é uma ferramenta de apoio e **não substitui acompanhamento profissional** de nutricionistas ou médicos.

As recomendações alimentares geradas devem ser utilizadas apenas para fins informativos.

---

# 📄 Licença

© 2026 MyNutri AI.

Este projeto é **proprietário** e seu código fonte **não pode ser copiado, modificado ou redistribuído sem autorização do autor**.

---

# 👨‍💻 Autores

Desenvolvido por:

* **Gabriel Rezende**
* **Carlos Alberto**
* **Arthur Hoffmann**

Projeto voltado para aplicação de tecnologia e inteligência artificial na área de nutrição.
