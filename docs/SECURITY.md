# 🔒 Guia de Segurança — MyNutri AI

Documento com boas práticas para proteger a API OpenAI e dados sensíveis.

---

## 📋 Índice
1. [Variáveis de Ambiente](#variáveis-de-ambiente)
2. [Chaves de API](#chaves-de-api)
3. [Git & Versionamento](#git--versionamento)
4. [Ambiente Local vs Produção](#ambiente-local-vs-produção)
5. [Monitoramento & Auditoria](#monitoramento--auditoria)
6. [Checklist de Segurança](#checklist-de-segurança)

---

## 🔑 Variáveis de Ambiente

### ✅ O que você está fazendo certo:

1. ✅ `.env` no `.gitignore` — chaves não são commitadas
2. ✅ `.env.example` documentado — facilita setup de novos devs
3. ✅ Uso de `python-dotenv` — carrega variáveis seguramente

### 🚀 Melhorias a fazer:

**1. Validação de variáveis obrigatórias**

Adicione este código ao início de `mynutri/settings.py`:

```python
import os
from dotenv import load_dotenv

load_dotenv()

# Validar variáveis obrigatórias
REQUIRED_ENV_VARS = ['SECRET_KEY', 'AI_API_KEY', 'AI_API_URL']

for var in REQUIRED_ENV_VARS:
    if not os.getenv(var):
        raise ValueError(f'❌ Variável de ambiente {var} não configurada!')

print('✅ Todas as variáveis obrigatórias foram carregadas')
```

**2. Separar ambientes**

```bash
# Desenvolvimento
.env.development

# Staging/Testes
.env.staging

# Produção (NUNCA no repo)
.env.production (adicione ao .gitignore)
```

**3. Configurar DEBUG dinamicamente**

```python
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

if DEBUG is True:
    print('⚠️  DEBUG ativado — NUNCA use em produção!')
```

---

## 🔐 Chaves de API

### ✅ Gerencie suas chaves de forma segura:

**1. Crie uma chave dedicada para MyNutri**

- Acesse: https://platform.openai.com/api-keys
- Clique em "Create new secret key"
- **Copie uma única vez** (não será mostrada novamente)
- **Salve em seu `.env` local apenas**

**2. Defina limites de uso (IMPORTANTE!)**

- Acesse: https://platform.openai.com/account/billing/limits
- Defina um **hard limit** mensal (ex: $50)
- Receba alertes em `$40` (warning) e `$45` (max usage)
- Isso previne surpresas com custos altos

**3. Configure expiração de chaves**

```
⏰ Recomendação: Rotacione chaves a cada 3 meses
```

Se uma chave for comprometida:
1. Vá para https://platform.openai.com/api-keys
2. Clique no ícone de lixeira para deletar a chave comprometida
3. Crie uma nova chave
4. Atualize seu `.env`

**4. Use chaves diferentes por ambiente**

```
Desenvolvimento: sk-proj-dev-xxxxx
Staging:        sk-proj-staging-xxxxx
Produção:       sk-proj-prod-xxxxx (com limite menor)
```

---

## 📦 Git & Versionamento

### Verificar se há secrets no histórico:

```bash
# Procurar por padrões de API key
git log -p --all -S "sk-proj-" | head -20

# Procurar por SECRET_KEY exposta
git log -p --all -S "SECRET_KEY=" | head -20
```

Se encontrar algo:

```bash
# ❌ NUNCA use: git rebase --hard (cria mais problemas)
# ✅ Use: git-filter-repo (ferramenta oficial)

pip install git-filter-repo

# Remover arquivo sensível do histórico
git filter-repo --path .env --invert-paths
```

### Configurar git pre-commit hooks:

Crie `.git/hooks/pre-commit` (executável):

```bash
#!/bin/bash

# Verificar se há .env não-filtrado
if git diff --cached --name-only | grep -E "\.env|secrets"; then
    echo "❌ ERRO: Você está tentando commitar arquivo sensível!"
    echo "    Adicione '.env' ao .gitignore"
    exit 1
fi

# Verificar se há patterns de API key
if git diff --cached | grep -i "sk-proj-\|api[_-]?key"; then
    echo "❌ ERRO: Detectado possível API key no commit!"
    exit 1
fi

exit 0
```

Tornar executável:
```bash
chmod +x .git/hooks/pre-commit
```

---

## 🌍 Ambiente Local vs Produção

### Desenvolvimento Local

```bash
# .env.development
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
AI_API_KEY=sk-proj-seu-dev-key
DATABASE_URL=sqlite:///db.sqlite3
```

### Produção (Exemplo com Heroku/Railway)

**NUNCA commite `.env.production`!**

Use variáveis de ambiente da plataforma:

**Heroku:**
```bash
heroku config:set AI_API_KEY=sk-proj-xxxxx
heroku config:set SECRET_KEY=xxxxx
heroku config:set DEBUG=False
```

**Railway.app:**
```
Painel → Variables → Adicionar chaves
```

**AWS/Azure/GCP:**
- AWS Secrets Manager
- Azure Key Vault
- Google Cloud Secret Manager

---

## 📊 Monitoramento & Auditoria

### 1. Monitorar uso de API OpenAI

Acesse: https://platform.openai.com/account/billing/overview

Estratégia recomendada:

```python
# nutrition/services.py - adicione logging

import logging
logger = logging.getLogger(__name__)

def generate_diet(self, anamnese: Anamnese) -> DietPlan:
    logger.info(f'[AI-CALL] User={anamnese.user_id} | Model={self.model}')
    
    try:
        response = self._call_api(prompt)
        logger.info(f'[AI-SUCCESS] Cost est. ~0.01 USD')
        return self._parse_response(response)
    except Exception as e:
        logger.error(f'[AI-ERROR] {str(e)}')
        raise
```

### 2. Rate limiting

Implementar limite de chamadas por usuário:

```python
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.core.cache import cache

def generate_diet_api(request):
    user_id = request.user.id
    cache_key = f'diet_gen_{user_id}'
    
    if cache.get(cache_key):
        return Response(
            {'error': 'Aguarde 1 hora antes de gerar outra dieta'},
            status=429
        )
    
    # Gerar dieta...
    cache.set(cache_key, True, timeout=3600)  # 1 hora
```

### 3. Logs estruturados

```bash
# Habilitar logging no Django
pip install python-json-logger
```

```python
# mynutri/settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(timestamp)s %(level)s %(name)s %(message)s'
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/mynutri.log',
            'maxBytes': 1024 * 1024,  # 1MB
            'backupCount': 5,
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['file'],
        'level': 'INFO',
    },
}
```

---

## ✅ Checklist de Segurança

### Antes de cada deploy:

- [ ] `.env` está no `.gitignore`
- [ ] `.env` não foi commitado no histórico
- [ ] `DEBUG=False` em produção
- [ ] Chave de API é diferente entre dev/prod
- [ ] Limite de uso definido na OpenAI
- [ ] Logs estão configurados
- [ ] Rate limiting implementado
- [ ] HTTPS habilitado
- [ ] CORS configurado corretamente
- [ ] Senhas de usuários são hashed (Django faz isso)

### Setup de novo desenvolvedor:

```bash
# 1. Clone o repo
git clone seu-repo.git
cd mynutri-ai-plataform

# 2. Configure variáveis
cp .env.example .env
# Edit .env com suas chaves

# 3. Valide
python manage.py check --deploy

# 4. Rode testes
python manage.py test
```

---

## 🚨 Em caso de vazamento de chave:

1. **IMEDIATAMENTE**: Revogue a chave em https://platform.openai.com/api-keys
2. Gere uma nova chave
3. Atualize seu `.env` local
4. Revise logs de uso: https://platform.openai.com/account/billing/limits
5. Se foi commitada: use `git-filter-repo` para remover do histórico

---

## 📚 Referências

- [OpenAI API Security](https://platform.openai.com/docs/guides/safety-best-practices)
- [Django Security](https://docs.djangoproject.com/en/6.0/topics/security/)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [12 Factor App](https://12factor.net/)

---

**Última atualização**: Março 2026
**Responsável**: Gabriel Rezende
