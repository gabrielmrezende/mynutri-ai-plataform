// @ts-check
const { test, expect } = require('@playwright/test');
const { BASE, uniqueEmail, registerUser, acceptTermsIfPresent } = require('./helpers');

test.describe('Autenticação', () => {

  test('Cadastro com dados válidos redireciona para /dieta/', async ({ page }) => {
    const email = uniqueEmail();

    await page.goto(`${BASE}/auth/`);
    await page.getByText('Criar Conta').click();

    await page.locator('#register-form input[type="text"]').fill('Usuário E2E');
    await page.locator('#register-form input[type="email"]').fill(email);
    await page.locator('#register-form input[type="password"]').fill('SenhaSegura@123');

    await acceptTermsIfPresent(page);
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
    await acceptTermsIfPresent(page);
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

    await registerUser(context.request, { nome: 'Login Test', email, password });

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
    await registerUser(context.request, { nome: 'Duplicado', email, password: 'SenhaSegura@123' });

    // Tenta cadastrar de novo via UI
    await page.goto(`${BASE}/auth/`);
    await page.getByText('Criar Conta').click();
    await page.locator('#register-form input[type="text"]').fill('Duplicado 2');
    await page.locator('#register-form input[type="email"]').fill(email);
    await page.locator('#register-form input[type="password"]').fill('SenhaSegura@123');
    await acceptTermsIfPresent(page);
    await page.locator('#register-form button[type="submit"]').click();

    await expect(page.locator('#auth-error')).toBeVisible({ timeout: 5_000 });
  });

  test('Logout limpa cookie e redireciona para home', async ({ page, context }) => {
    const email = uniqueEmail();

    // Registra e entra na dieta
    await registerUser(context.request, { nome: 'Logout Test', email, password: 'SenhaSegura@123' });

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

  test('Registro via API não devolve tokens no JSON (somente cookies HttpOnly)', async ({ context }) => {
    const res = await registerUser(context.request, {
      nome: 'Sem Token', email: uniqueEmail(), password: 'SenhaSegura@123',
    });
    expect(res.status()).toBe(201);
    const body = await res.json();
    expect(body).not.toHaveProperty('token');
    expect(body).not.toHaveProperty('refresh');
    expect(body).not.toHaveProperty('access');
    expect(body).toHaveProperty('user');

    const cookies = await context.cookies();
    expect(cookies.find(c => c.name === 'mynutri_access')?.httpOnly).toBe(true);
  });

  test('Registro sem aceite dos termos é rejeitado', async ({ request }) => {
    const res = await request.post('http://127.0.0.1:8000/api/v1/auth/register', {
      data: { nome: 'Sem termos', email: uniqueEmail(), senha: 'SenhaSegura@123' },
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    expect(res.status()).toBe(400);
  });

});
