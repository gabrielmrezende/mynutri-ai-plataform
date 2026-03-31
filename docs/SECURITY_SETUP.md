# 🔒 Setup de Segurança — MyNutri AI

Guia rápido para ativar proteções de segurança no seu repositório.

---

## ⚡ Setup Rápido (5 minutos)

### 1️⃣ Ativar validação de variáveis

```bash
# Instalar script de validação
python scripts/validate_env.py

# Espera:
# ✅ Se passou: Tudo bem configurado
# ❌ Se falhou: Corrija as variáveis conforme mensagens
```

### 2️⃣ Ativar pre-commit hook (Windows)

```bash
# Copiar hook para pasta correta
copy scripts\pre-commit-hook .git\hooks\pre-commit

# Em Windows PowerShell:
Copy-Item scripts\pre-commit-hook .git\hooks\pre-commit
```

**Em Linux/Mac:**
```bash
cp scripts/pre-commit-hook .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

**Verificar se funcionou:**
```bash
# Tentar commitar com um arquivo sensível deve falhar
git add .env
git commit -m "test"  # Deve ser bloqueado
```

### 3️⃣ Usar ferramenta automatizada (Recomendado)

Instalar `pre-commit` framework (mais robusto):

```bash
pip install pre-commit

# Criar arquivo .pre-commit-config.yaml
cat > .pre-commit-config.yaml << 'EOF'
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: check-merge-conflict
      - id: detect-private-key
      - id: detect-aws-credentials
      - id: forbid-new-submodules
      
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
EOF

# Ativar
pre-commit install

# Testar
pre-commit run --all-files
```

---

## 📋 Checklist de Segurança

Após completar o setup:

- [ ] Executar `python scripts/validate_env.py` com sucesso
- [ ] Pre-commit hook instalado e funcionando
- [ ] `.env` não foi commitado (verificar `git log`)
- [ ] Chave API tem limite de uso na OpenAI
- [ ] `DEBUG=False` em arquivos de produção
- [ ] Todos os devs da equipe seguirem este guia

---

## 🚨 Troubleshooting

### "Pre-commit hook não é executado"

**Windows:**
```bash
# Git pode não reconhecer scripts bash no Windows
# Solução: Usar arquivo PowerShell em vez disso
# Ou use WSL/Git Bash
```

**Todos:**
```bash
# Verificar se hook tem permissão de execução
ls -l .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

### "Preciso bypassar o hook (não faça!)"

❌ NUNCA faça:
```bash
git commit --no-verify  # Perigoso!
```

✅ FAÇA:
```bash
# Remova o arquivo sensível e tente novamente
git reset HEAD .env
git add outros-arquivos
git commit -m "mensagem"
```

### "Descobri que commitei uma chave!"

1. **Revogue a chave AGORA**: https://platform.openai.com/api-keys
2. Gere uma nova chave
3. Atualize `.env`
4. Use `git-filter-repo`:
   ```bash
   pip install git-filter-repo
   git filter-repo --path .env --invert-paths
   git push origin --all --force  # ⚠️ FORCE PUSH APENAS NESSE CASO
   ```

---

## 📊 Monitoramento Contínuo

Verificar regularmente:

```bash
# Procurar por padrões suspeitos no código
grep -r "sk-proj-" . --exclude-dir=.git --exclude-dir=venv

# Verificar logs de API usage
# https://platform.openai.com/account/billing/overview

# Verificar se há chaves em histórico
git log --all --oneline -S "sk-proj-" | head -5
```

---

## 🎯 Próximos Passos

1. ✅ **Completar este setup de segurança**
2. 📖 Ler `docs/SECURITY.md` completo
3. 🚀 Implementar rate limiting (veja em SECURITY.md)
4. 📊 Ativar logging estruturado (veja em SECURITY.md)

---

**Tempo total**: ~5 minutos
**Benefício**: Proteção contra vazamento de credenciais
**Dúvidas?** Veja `docs/SECURITY.md`
