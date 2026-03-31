#!/usr/bin/env python
"""
Script para validar variáveis de ambiente antes de rodar a aplicação.
Uso: python scripts/validate_env.py
"""

import os
import sys
from pathlib import Path

def validate_env():
    """Valida se todas as variáveis obrigatórias estão configuradas."""

    # Carregar .env
    env_path = Path('.env')
    if not env_path.exists():
        print('❌ Arquivo .env não encontrado!')
        print('   Execute: cp .env.example .env')
        return False

    # Variáveis obrigatórias
    required_vars = {
        'SECRET_KEY': 'Django secret key',
        'AI_API_KEY': 'OpenAI API Key (começa com sk-proj-)',
        'AI_API_URL': 'OpenAI API URL',
    }

    # Variáveis opcionais
    optional_vars = {
        'DEBUG': 'Debug mode',
        'ALLOWED_HOSTS': 'Hosts permitidos',
    }

    print('\n🔒 Validando variáveis de ambiente...\n')

    errors = []

    # Verificar variáveis obrigatórias
    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            errors.append(f'  ❌ {var:<20} — {description}')
        else:
            # Mascarar valor
            masked = value[:4] + '*' * (len(value) - 8) + value[-4:] if len(value) > 8 else '****'
            print(f'  ✅ {var:<20} — {description}')
            print(f'     Valor: {masked}\n')

    # Avisos para opcionais
    for var, description in optional_vars.items():
        value = os.getenv(var)
        if not value:
            print(f'  ⚠️  {var:<20} — {description} (não configurado)')
        else:
            print(f'  ✅ {var:<20} — {description}')

    # Validações específicas
    print('\n📋 Validações específicas:\n')

    # 1. DEBUG em produção
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    if debug:
        print('  ⚠️  DEBUG=True (use apenas em desenvolvimento!)')
    else:
        print('  ✅ DEBUG=False (modo produção ativo)')

    # 2. SECRET_KEY muito curto
    secret_key = os.getenv('SECRET_KEY', '')
    if len(secret_key) < 50:
        errors.append(f'  ❌ SECRET_KEY muito curto (mínimo 50 caracteres)')
    else:
        print('  ✅ SECRET_KEY tem tamanho adequado')

    # 3. Formato de API_KEY
    api_key = os.getenv('AI_API_KEY', '')
    if api_key and not api_key.startswith('sk-proj-'):
        print('  ⚠️  AI_API_KEY não segue o padrão OpenAI (sk-proj-...)')
    elif api_key:
        print('  ✅ AI_API_KEY segue padrão OpenAI')

    # 4. Verificar se há secrets no git
    print('\n🔍 Verificando histórico Git...\n')
    os.system('git log --all -p | grep -i "sk-proj-" | head -1 > /dev/null')
    exit_code = os.system('git log --all | grep -i "sk-proj-" > /dev/null 2>&1')

    if exit_code == 0:
        errors.append('  ❌ Detectada possível API key no histórico do Git!')
    else:
        print('  ✅ Nenhuma API key detectada no histórico')

    # Resultado final
    print('\n' + '='*60)
    if errors:
        print('❌ ERROS ENCONTRADOS:\n')
        for error in errors:
            print(error)
        print('\n' + '='*60)
        return False
    else:
        print('✅ Todas as validações passaram com sucesso!')
        print('='*60)
        return True

if __name__ == '__main__':
    success = validate_env()
    sys.exit(0 if success else 1)
