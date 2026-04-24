// @ts-check
const { test, expect } = require('@playwright/test');
const { uniqueEmail } = require('./helpers');

const BASE = 'http://127.0.0.1:8000';

test.describe('Autenticação', () => {

  test('Cadastro com dados válidos redireciona para /dieta/', async ({ page }) => {
    const email = uniqueEmail();

    await page.goto(`${BASE}/auth/`);
    await page.getByText('Criar Conta').click();

    await page.locator('#register-form input[type="text"]').fill('Usuário E2E');
    await page.locator('#register-form input[type="email"]').fill(email);
    await page.locator('#register-form input[type="password"]').fill('SenhaSegura@123');

    await page.locator('#register-form button[type="submit"]').click();

    await expect(page).toHaveURL(/\/dieta\//, { timeout: 10_000 });
  });

  test('Cookie HttpOnly é definido após cadastro', async ({ page, context }) => {
    const email = uniqueEmail();

    await page.goto(`${BASE}/auth/`);
    await page.getByText('Criar Conta').click();

    await page.locator('#register-form input[type="text"]').fill('Cookie Test');
    await page.locator('#register-form input[type="email"]').fill(email);
    await page.locator('#register-form input[type="password"]').fill('SenhaSegura@123');
    await page.locator('#register-form button[type="submit"]').click();

    await page.waitForURL(/\/dieta\//, { timeout: 10_000 });

    const cookies = await context.cookies();
    const accessCookie = cookies.find(c => c.name === 'mynutri_access');
    expect(accessCookie).toBeTruthy();
    expect(accessCookie?.httpOnly).toBe(true);
  });

  test('Login com credenciais válidas redireciona para /dieta/', async ({ page, context }) => {
    // Cria usuário via API
    const email    = uniqueEmail();
    const password = 'SenhaSegura@123';

    await context.request.post('http://127.0.0.1:8000/api/v1/auth/register', {
      data: { nome: 'Login Test', email, senha: password },
    });

    // Aguarda um momento para o servidor processar
    await page.waitForTimeout(200);

    // Login via UI
    await page.goto(`${BASE}/auth/`);
    await page.locator('#login-form input[type="email"]').fill(email);
    await page.locator('#login-form input[type="password"]').fill(password);
    await page.locator('#login-form button[type="submit"]').click();

    await expect(page).toHaveURL(/\/dieta\//, { timeout: 10_000 });
  });

  test('Login com senha incorreta exibe mensagem de erro', async ({ page }) => {
    await page.goto(`${BASE}/auth/`);
    await page.locator('#login-form input[type="email"]').fill('naoexiste@exemplo.com');
    await page.locator('#login-form input[type="password"]').fill('senha_errada');
    await page.locator('#login-form button[type="submit"]').click();

    await expect(page.locator('#auth-error')).toBeVisible({ timeout: 5_000 });
    await expect(page.locator('#auth-error')).not.toBeEmpty();
  });

  test('Cadastro com email já cadastrado exibe erro de duplicidade', async ({ page, context }) => {
    const email = uniqueEmail();

    // Cria usuário via API
    await context.request.post('http://127.0.0.1:8000/api/v1/auth/register', {
      data: { nome: 'Duplicado', email, senha: 'SenhaSegura@123' },
    });

    // Tenta cadastrar de novo via UI
    await page.goto(`${BASE}/auth/`);
    await page.getByText('Criar Conta').click();
    await page.locator('#register-form input[type="text"]').fill('Duplicado 2');
    await page.locator('#register-form input[type="email"]').fill(email);
    await page.locator('#register-form input[type="password"]').fill('SenhaSegura@123');
    await page.locator('#register-form button[type="submit"]').click();

    await expect(page.locator('#auth-error')).toBeVisible({ timeout: 5_000 });
  });

  test('Logout limpa cookie e redireciona para home', async ({ page, context }) => {
    const email = uniqueEmail();

    // Registra e entra na dieta
    await context.request.post('http://127.0.0.1:8000/api/v1/auth/register', {
      data: { nome: 'Logout Test', email, senha: 'SenhaSegura@123' },
    });

    await page.goto(`${BASE}/auth/`);
    await page.locator('#login-form input[type="email"]').fill(email);
    await page.locator('#login-form input[type="password"]').fill('SenhaSegura@123');
    await page.locator('#login-form button[type="submit"]').click();
    await page.waitForURL(/\/dieta\//, { timeout: 10_000 });

    // Faz logout
    await page.locator('#userMenuBtn').click();
    await page.locator('#logoutBtn').click();

    await expect(page).toHaveURL(`${BASE}/`, { timeout: 5_000 });

    const cookies = await context.cookies();
    const accessCookie = cookies.find(c => c.name === 'mynutri_access');
    expect(accessCookie).toBeFalsy();
  });

});
