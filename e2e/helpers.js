/**
 * Helpers compartilhados entre os testes E2E.
 * Usa a API diretamente para setup rápido (sem depender da UI de cadastro).
 */

const API = 'http://127.0.0.1:8000/api/v1';

let _userCounter = Date.now();

/** Gera um email único por execução de teste. */
function uniqueEmail() {
  return `e2e_${_userCounter++}@test.com`;
}

/**
 * Cria um usuário via API e injeta os cookies HttpOnly no browser context.
 * Retorna { email, password, user }.
 */
async function createAndLoginUser(context, { email, password } = {}) {
  email    = email    || uniqueEmail();
  password = password || 'SenhaE2E@123';

  const res = await context.request.post(`${API}/auth/register`, {
    data: { nome: 'Teste E2E', email, senha: password },
  });

  if (!res.ok()) {
    const body = await res.text();
    throw new Error(`Falha ao criar usuário E2E: ${res.status()} — ${body}`);
  }

  const data = await res.json();
  // Os cookies HttpOnly já foram definidos pelo servidor na resposta do register.
  // O APIRequestContext do Playwright propaga os cookies automaticamente para o
  // browser context associado, então páginas abertas neste context já estarão autenticadas.

  return { email, password, user: data.user };
}

/**
 * Injeta o user no localStorage (apenas metadados, sem token).
 * Deve ser chamado após navegação para qualquer página do app.
 */
async function setUserLocalStorage(page, user) {
  await page.evaluate((u) => {
    localStorage.setItem('mynutri_user', JSON.stringify(u));
  }, user);
}

module.exports = { uniqueEmail, createAndLoginUser, setUserLocalStorage, API };
