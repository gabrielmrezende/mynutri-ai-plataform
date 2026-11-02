/**
 * Helpers compartilhados entre os testes E2E.
 * Usa a API diretamente para setup rápido (sem depender da UI de cadastro).
 *
 * Contratos da API seguidos aqui:
 *   - Requisições não seguras exigem o header X-Requested-With (anti-CSRF);
 *   - Registro exige accepted_terms: true;
 *   - Login/registro NÃO devolvem tokens no JSON — só cookies HttpOnly + user.
 */

const BASE = 'http://127.0.0.1:8000';
const API = `${BASE}/api/v1`;

/** Header exigido pelo backend em POST/PUT/PATCH/DELETE autenticados por cookie. */
const XHR_HEADERS = { 'X-Requested-With': 'XMLHttpRequest' };

let _userCounter = Date.now();

/**
 * Gera um email único por execução de teste. O domínio precisa ter registro MX:
 * o cadastro valida DNS/MX (test.com e example.com não têm).
 */
function uniqueEmail() {
  return `e2e_${_userCounter++}@gmail.com`;
}

/** POST na API com o header anti-CSRF. `request` pode ser context.request ou o fixture request. */
async function apiPost(request, path, data) {
  return request.post(`${API}${path}`, { data, headers: XHR_HEADERS });
}

/** Registra um usuário via API (cookies HttpOnly ficam no context). */
async function registerUser(request, { nome = 'Teste E2E', email, password } = {}) {
  return apiPost(request, '/auth/register', {
    nome,
    email,
    senha: password,
    accepted_terms: true,
  });
}

/**
 * Cria um usuário via API e injeta os cookies HttpOnly no browser context.
 * Retorna { email, password, user }.
 */
async function createAndLoginUser(context, { email, password } = {}) {
  email    = email    || uniqueEmail();
  password = password || 'SenhaE2E@123';

  const res = await registerUser(context.request, { email, password });

  if (!res.ok()) {
    const body = await res.text();
    throw new Error(`Falha ao criar usuário E2E: ${res.status()} — ${body}`);
  }

  const data = await res.json();
  // Os cookies HttpOnly já foram definidos pelo servidor na resposta do register.
  // O APIRequestContext do Playwright compartilha o cookie jar com o browser
  // context, então páginas abertas neste context já estarão autenticadas.
  // O JSON não traz tokens — só os dados do usuário.

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

/** Marca o aceite de termos no formulário de cadastro, se existir na UI. */
async function acceptTermsIfPresent(page) {
  const terms = page.locator('#register-form input[type="checkbox"]');
  if (await terms.count()) {
    await terms.first().check();
  }
}

module.exports = {
  BASE,
  API,
  XHR_HEADERS,
  uniqueEmail,
  apiPost,
  registerUser,
  createAndLoginUser,
  setUserLocalStorage,
  acceptTermsIfPresent,
};
