// @ts-check
const { defineConfig, devices } = require('@playwright/test');

// Banco SQLite em ARQUIVO: migrate e runserver são processos distintos, então
// :memory: deixaria o servidor sem tabelas. Lido por mynutri/test_settings.py.
const TEST_DB_PATH = process.env.TEST_DB_PATH || 'e2e-db.sqlite3';

module.exports = defineConfig({
  testDir: './e2e',
  fullyParallel: false,     // testes de auth compartilham estado do servidor
  retries: process.env.CI ? 2 : 0,
  workers: 1,               // 1 worker para evitar conflitos no banco de dev
  reporter: [['html', { open: 'never' }], ['list']],

  use: {
    baseURL: 'http://127.0.0.1:8000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // Cookies HttpOnly são gerenciados automaticamente pelo browser context
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Inicia o Django antes de rodar os testes (só em dev local).
  // Em CI o workflow sobe o servidor e espera o /health/ responder.
  webServer: process.env.CI ? undefined : {
    command: 'python manage.py migrate --no-input && python manage.py runserver 127.0.0.1:8000 --noreload',
    url: 'http://127.0.0.1:8000/health/',
    reuseExistingServer: true,
    timeout: 60000,
    env: {
      DJANGO_SETTINGS_MODULE: 'mynutri.test_settings',
      TEST_DB_PATH,
    },
  },
});
