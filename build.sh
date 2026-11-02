#!/usr/bin/env bash
# =============================================================================
# build.sh — Script de build para deploy no Render
# Executado pelo Render no buildCommand. NÃO roda migrations: o banco interno
# não é acessível durante o build — o migrate roda no startCommand
# (ver render.yaml).
# =============================================================================

set -o errexit   # para imediatamente em qualquer erro
set -o nounset   # erro ao usar variável não definida
set -o pipefail  # falha se qualquer comando de um pipe falhar

echo "📦 Instalando dependências..."
pip install --upgrade pip
pip install -r requirements.txt

echo "📁 Coletando arquivos estáticos..."
python manage.py collectstatic --no-input

echo "🔎 Verificando configuração de produção..."
python manage.py check --deploy --fail-level ERROR

echo "✅ Build concluído com sucesso! (migrations serão aplicadas no start)"
