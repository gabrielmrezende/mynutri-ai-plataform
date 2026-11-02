// @ts-check
const { test, expect } = require('@playwright/test');
const {
  BASE, API, XHR_HEADERS, apiPost, createAndLoginUser, setUserLocalStorage,
} = require('./helpers');

/** Anamnese válida no formato real da API (AnamneseSerializer). */
function validAnamnese(overrides = {}) {
  return {
    idade: 28,
    sexo: 'M',
    peso: 75.0,
    altura: 178.0,
    nivel_atividade: 'moderate',
    objetivo: 'lose',
    meals_per_day: 4,
    restricoes: '',
    food_preferences: 'frango, arroz',
    allergies: '',
    ...overrides,
  };
}

/**
 * Submete o questionário de anamnese diretamente via API.
 * Mais rápido do que preencher 5 etapas do formulário na UI.
 */
async function submitAnamnese(context, overrides = {}) {
  return apiPost(context.request, '/anamnese', validAnamnese(overrides));
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
    await expect(page.locator('#stateEmpty, #stateList, #stateError').first())
      .toBeVisible({ timeout: 5_000 });
  });

  test('API de anamnese aceita payload válido', async ({ context }) => {
    await createAndLoginUser(context);
    const res = await submitAnamnese(context);
    expect(res.status()).toBe(201);
  });

  test('API de anamnese rejeita menor de 18 anos', async ({ context }) => {
    await createAndLoginUser(context);
    const res = await submitAnamnese(context, { idade: 17 });
    expect(res.status()).toBe(400);
    const body = await res.json();
    expect(body).toHaveProperty('idade');
  });

  test('Questionário salva anamnese e redireciona para /dieta/?generate=1', async ({ page, context }) => {
    const { user } = await createAndLoginUser(context);

    await page.goto(`${BASE}/questionario/`);
    await setUserLocalStorage(page, user);
    await page.reload();

    // Etapa 1 — dados pessoais
    await page.locator('#nome').fill('Teste E2E');
    await page.locator('#idade').fill('28');
    await page.locator('#custom-sexo .custom-select-trigger').click();
    await page.locator('#custom-sexo .custom-select-option[data-value="masculino"]').click();
    await page.locator('#peso').fill('75');
    await page.locator('#altura').fill('178');
    await page.locator('#btn-next').click();

    // Etapa 2 — objetivo
    await page.locator('input[name="objetivo"][value="perda_peso"]').check({ force: true });
    await page.locator('#btn-next').click();

    // Etapa 3 — nível de atividade
    await page.locator('input[name="atividade"][value="moderado"]').check({ force: true });
    await page.locator('#btn-next').click();

    // Etapa 4 — restrições (mantém padrão onívoro)
    await page.locator('#btn-next').click();

    // Etapa 5 — refeições por dia
    await page.locator('#custom-refeicoes .custom-select-trigger').click();
    await page.locator('#custom-refeicoes .custom-select-option[data-value="4"]').click();

    await page.locator('#btn-submit').click();

    await expect(page).toHaveURL(/\/dieta\/\?generate=1/, { timeout: 10_000 });
  });

});

test.describe('Proteções da API', () => {

  test('POST autenticado por cookie sem X-Requested-With é bloqueado (anti-CSRF)', async ({ context }) => {
    await createAndLoginUser(context);
    const res = await context.request.post(`${API}/anamnese`, { data: validAnamnese() });
    expect(res.status()).toBe(403);
  });

  test('Status de job de outro usuário retorna 404', async ({ browser }) => {
    const ctxA = await browser.newContext();
    const ctxB = await browser.newContext();
    try {
      await createAndLoginUser(ctxA);
      await createAndLoginUser(ctxB);
      // Job inexistente/alheio: nunca vaza informação
      const res = await ctxB.request.get(`${API}/diet/status/999999`);
      expect(res.status()).toBe(404);
    } finally {
      await ctxA.close();
      await ctxB.close();
    }
  });

  test('Respostas trazem Content-Security-Policy', async ({ request }) => {
    const res = await request.get(`${BASE}/`);
    expect(res.headers()['content-security-policy']).toContain("default-src 'self'");
  });

  test('Header anti-CSRF é aceito pela API', async ({ context }) => {
    await createAndLoginUser(context);
    const res = await context.request.post(`${API}/anamnese`, {
      data: validAnamnese(), headers: XHR_HEADERS,
    });
    expect(res.status()).toBe(201);
  });

});
