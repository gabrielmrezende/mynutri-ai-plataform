#!/usr/bin/env bash
# =============================================================================
# build.sh — Script de build para deploy no Render
# Executado automaticamente pelo Render antes de iniciar a aplicação.
# =============================================================================

set -o errexit   # para imediatamente em qualquer erro

echo "📦 Instalando dependências..."
pip install -r requirements.txt

echo "📁 Coletando arquivos estáticos..."
python manage.py collectstatic --no-input

echo "🗄️  Aplicando migrações do banco de dados..."
set +e
python manage.py migrate --no-input
MIGRATE_EXIT=$?
set -e
if [ $MIGRATE_EXIT -ne 0 ]; then
  echo "⚠️  Migração falhou no build (banco interno não acessível). Será executada no startup."
fi

echo "✅ Build concluído com sucesso!"
