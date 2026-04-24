// @ts-check
const { defineConfig, devices } = require('@playwright/test');

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

  // Inicia o Django antes de rodar os testes (só em dev local)
  // Em CI o servidor já deve estar rodando ou use um processo separado
  webServer: process.env.CI ? undefined : {
    command: 'python manage.py runserver --settings=mynutri.test_settings 2>&1',
    url: 'http://127.0.0.1:8000',
    reuseExistingServer: true,
    timeout: 30000,
  },
});
