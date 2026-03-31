# Setup e Execução do MyNutri AI

## 🔧 Pré-requisitos

- Python 3.10+
- Git
- Um editor de código (VSCode, PyCharm, etc)

## 📦 Instalação

### 1. Clonar o repositório

```bash
cd ~/OneDrive/Área\ de\ Trabalho/
git clone <seu-repo>
cd mynutri-ai-plataform
```

### 2. Criar virtual environment

```bash
python -m venv venv
source venv/Scripts/activate  # Windows: venv\Scripts\activate
```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

### 4. Configurar variáveis de ambiente (.env)

Já existe um `.env` com as configurações básicas. Você DEVE adicionar a chave de IA:

```env
AI_API_KEY=sua_chave_openai_ou_gemini
AI_API_URL=https://api.openai.com/v1/chat/completions
```

Ou use Gemini:
```env
AI_API_KEY=sua_chave_google_gemini
AI_API_URL=https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent
```

### 5. Executar migrações do banco de dados

```bash
python manage.py migrate
```

### 6. (Opcional) Criar superuser para admin

```bash
python manage.py createsuperuser
```

## 🚀 Executar a Aplicação

### Terminal 1: Servidor Django (Backend)

```bash
python manage.py runserver
```

O servidor estará em: **http://127.0.0.1:8000**

### Terminal 2: Servir o Frontend

**Opção A - Live Server do VSCode:**
1. Abra `frontend/public/index.html`
2. Clique em "Go Live" (canto inferior direito)
3. O frontend abrirá em `http://localhost:5500` ou similar

**Opção B - Python http.server:**
```bash
cd frontend/public
python -m http.server 5500
```

**Opção C - Usar diretamente a porta 8000:**

No arquivo `frontend/public/dieta.html`, `auth.html` e `questionario.html`, a URL da API já está configurada como `http://127.0.0.1:8000/api`. Você pode abrir os arquivos diretamente no navegador via `file://` ou usar um servidor HTTP.

## 🧪 Testando o Fluxo Completo

1. **Abrir Landing Page:** http://localhost:5500/index.html
2. **Clicar em "Começar"** → vai para questionário (ou faça login antes)
3. **Questionário:**
   - Se **não logado**: Preenche formulário → Clica "Gerar minha dieta" → Redireciona para login
   - Se **logado**: Preenche formulário → Clica "Gerar minha dieta" → Envia à API → Redireciona para dieta.html
4. **Login/Cadastro:**
   - E-mail e senha (mínimo 8 caracteres)
   - Após login com sucesso, redireciona automaticamente para a dieta
5. **Página de Dieta:** Exibe o plano alimentar gerado

## 🐛 Troubleshooting

### Erro: "Erro de conexão. Verifique se o servidor está rodando."

**Causas possíveis:**
1. ❌ Servidor Django não está rodando → Execute `python manage.py runserver`
2. ❌ CORS bloqueando → Cheque `mynutri/settings.py` (já foi corrigido, mas verifique DEBUG=True)
3. ❌ Porta diferente → Atualize `API_BASE` nos arquivos HTML se precisar

**Solução:**
- Abra o console do navegador (F12 → Aba "Network")
- Tente fazer uma requisição (login, questionário, etc)
- Veja qual erro aparece nas requisições

### Erro: "E-mail ou senha inválidos"

- Certifique-se de que criou a conta com aquele e-mail
- Senha deve ter no mínimo 8 caracteres

### Erro: "Nenhuma anamnese encontrada"

- Você precisa preencher o questionário antes de gerar a dieta
- A anamnese é a resposta do questionário nutricional

### Erro de IA: "Falha ao gerar o plano alimentar"

- Verifique se configurou `AI_API_KEY` e `AI_API_URL` no `.env`
- Verifique se a chave da API é válida
- Veja os logs do servidor Django para mais detalhes

## 📝 Logs e Debugging

### Ver logs do Django

Os logs aparecem no terminal onde `python manage.py runserver` está rodando.

### Ver logs do navegador

Abra o DevTools:
- Windows/Linux: `F12` ou `Ctrl + Shift + I`
- Mac: `Cmd + Option + I`

Vá para **Console** e procure por erros ou mensagens de debug.

## 📚 Documentação

- **API endpoints**: Veja `/docs/API.md`
- **Arquitetura**: Veja `/docs/ARCHITECTURE.md`
- **Database schema**: Veja `/docs/DATABASE.md`
- **Prompts de IA**: Veja `/docs/PROMPTS.md`

## ✅ Checklist Inicial

- [ ] Dependências instaladas (`pip install -r requirements.txt`)
- [ ] `.env` configurado com `AI_API_KEY` e `AI_API_URL`
- [ ] Migrações rodadas (`python manage.py migrate`)
- [ ] Servidor Django rodando (`python manage.py runserver`)
- [ ] Frontend sendo servido (Live Server ou `python -m http.server`)
- [ ] Navegador acessando o frontend
- [ ] Fluxo completo testado (questionário → login → dieta)

## 🚨 Próximos Passos

1. **Integrar IA**: Configure a chave da API de IA no `.env`
2. **Testar geração de dieta**: Responda o questionário e verifique se a dieta é gerada
3. **Melhorar UI**: Adicionar mais estilos e feedback visual
4. **Deploy**: Quando pronto, fazer deploy para produção

---

**Dúvidas?** Verifique a aba **Network** do DevTools ou os logs do servidor Django para mais detalhes.
