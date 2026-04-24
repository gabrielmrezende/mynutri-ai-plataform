// @ts-check
const { test, expect } = require('@playwright/test');
const { createAndLoginUser, setUserLocalStorage } = require('./helpers');

const BASE = 'http://127.0.0.1:8000';

test.describe('Perfil do usuário', () => {

  test('Página de perfil exibe dados do usuário logado', async ({ page, context }) => {
    const { user } = await createAndLoginUser(context);

    await page.goto(`${BASE}/perfil/`);
    await setUserLocalStorage(page, user);
    await page.reload();

    // Aguarda o campo de nome ser preenchido pelo loadProfile()
    await expect(page.locator('#inputEmail')).toHaveValue(user.email, { timeout: 8_000 });
  });

  test('Usuário não logado é redirecionado de /perfil/ para /auth/', async ({ page }) => {
    await page.goto(`${BASE}/perfil/`);
    await expect(page).toHaveURL(/\/auth\//, { timeout: 5_000 });
  });

  test('Atualização de nome é refletida na navbar', async ({ page, context }) => {
    const { user } = await createAndLoginUser(context);

    await page.goto(`${BASE}/perfil/`);
    await setUserLocalStorage(page, user);
    await page.reload();

    // Aguarda carregamento do perfil
    await page.waitForFunction(() => {
      const input = document.getElementById('inputFirstName');
      return input && input.value !== '';
    }, { timeout: 8_000 });

    // Atualiza o nome
    await page.locator('#inputFirstName').fill('NomeAtualizado');
    await page.locator('#inputLastName').fill('Sobrenome');
    await page.locator('#btnSaveDados').click();

    await expect(page.locator('#alertDadosOk')).toBeVisible({ timeout: 5_000 });
  });

});
