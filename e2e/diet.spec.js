// @ts-check
const { test, expect } = require('@playwright/test');
const { createAndLoginUser, setUserLocalStorage, API } = require('./helpers');

const BASE = 'http://127.0.0.1:8000';

/**
 * Submete o questionário de anamnese diretamente via API.
 * Mais rápido do que preencher 5 etapas do formulário na UI.
 */
async function submitAnamnese(context) {
  const res = await context.request.post(`${API}/anamnese`, {
    data: {
      age: 28, gender: 'M', weight_kg: 75.0, height_cm: 178.0,
      activity_level: 'moderate', goal: 'lose', meals_per_day: 4,
      dietary_restrictions: '', allergies: '', food_preferences: '',
      goal_description: 'Emagrecer com saúde',
    },
  });
  return res.ok();
}

test.describe('Questionário e geração de dieta', () => {

  test('Usuário não logado é redirecionado de /dieta/ para /auth/', async ({ page }) => {
    await page.goto(`${BASE}/dieta/`);
    await expect(page).toHaveURL(/\/auth\//, { timeout: 5_000 });
  });

  test('Página de dieta carrega para usuário logado (sem gerar)', async ({ page, context }) => {
    const { user } = await createAndLoginUser(context);

    await page.goto(`${BASE}/dieta/`);
    await setUserLocalStorage(page, user);
    await page.reload();

    // Deve renderizar sem redirecionar para /auth/
    await expect(page).toHaveURL(`${BASE}/dieta/`, { timeout: 5_000 });
  });

  test('Histórico de dietas carrega para usuário logado', async ({ page, context }) => {
    const { user } = await createAndLoginUser(context);

    await page.goto(`${BASE}/historico/`);
    await setUserLocalStorage(page, user);
    await page.reload();

    await expect(page).toHaveURL(`${BASE}/historico/`, { timeout: 5_000 });
    // Aguarda o estado inicial (loading → empty ou list)
    await page.waitForTimeout(1500);
    const hasState = await page.locator('#stateEmpty, #stateList, #stateError').count();
    expect(hasState).toBeGreaterThan(0);
  });

  test('Questionário salva anamnese e redireciona para /dieta/?generate=1', async ({ page, context }) => {
    const { user } = await createAndLoginUser(context);

    await page.goto(`${BASE}/questionario/`);
    await setUserLocalStorage(page, user);
    await page.reload();

    // Etapa 1 — dados pessoais
    await page.locator('[data-field="nome"]').fill('Teste E2E');
    await page.locator('[data-field="idade"]').fill('28');
    await page.locator('[data-field="peso"]').fill('75');
    await page.locator('[data-field="altura"]').fill('178');
    await page.locator('.btn-next').first().click();

    // Etapa 2 — sexo
    await page.locator('[data-value="M"]').first().click();
    await page.locator('.btn-next').first().click();

    // Etapa 3 — objetivo
    await page.locator('[data-value="lose"]').first().click();
    await page.locator('.btn-next').first().click();

    // Etapa 4 — nível de atividade
    await page.locator('[data-value="moderate"]').first().click();
    await page.locator('.btn-next').first().click();

    // Etapa 5 — refeições por dia
    await page.locator('[data-value="4"]').first().click();

    // Submit
    const submitBtn = page.locator('#btn-submit');
    await submitBtn.click();

    await expect(page).toHaveURL(/\/dieta\/\?generate=1/, { timeout: 10_000 });
  });

});

test.describe('Rate limiting', () => {

  test('/api/v1/auth/login retorna 429 após 5 tentativas com senha errada', async ({ request }) => {
    const email = `throttle_${Date.now()}@test.com`;

    for (let i = 0; i < 5; i++) {
      await request.post(`${API}/auth/login`, {
        data: { email, password: 'senha_errada' },
      });
    }

    const res = await request.post(`${API}/auth/login`, {
      data: { email, password: 'senha_errada' },
    });

    expect(res.status()).toBe(429);
  });

});
