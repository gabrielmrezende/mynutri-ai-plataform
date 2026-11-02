/** Configuração compartilhada entre os scripts k6. */

export const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';
export const API      = `${BASE_URL}/api/v1`;

/** Header anti-CSRF exigido em POST/PUT/PATCH/DELETE autenticados por cookie. */
export const XHR_HEADERS = {
  'Content-Type': 'application/json',
  'X-Requested-With': 'XMLHttpRequest',
};

/**
 * Extrai o access token do cookie HttpOnly da resposta. A API não devolve mais
 * tokens no JSON; o mesmo JWT do cookie funciona como Bearer (e requisições
 * Bearer não exigem X-Requested-With).
 */
export function accessTokenFrom(res) {
  const cookie = res.cookies && res.cookies['mynutri_access'];
  return cookie && cookie.length ? cookie[0].value : null;
}

/** Cria um usuário e retorna { token, userId, email }. */
export function registerUser(http, email, password = 'LoadTest@123') {
  const res = http.post(
    `${API}/auth/register`,
    JSON.stringify({ nome: 'Load Test', email, senha: password, accepted_terms: true }),
    { headers: XHR_HEADERS },
  );
  if (res.status !== 201) {
    return null;
  }
  const body = JSON.parse(res.body);
  return { token: accessTokenFrom(res), userId: body.user?.id, email };
}

/** Faz login e retorna o token (lido do cookie). */
export function loginUser(http, email, password = 'LoadTest@123') {
  const res = http.post(
    `${API}/auth/login`,
    JSON.stringify({ email, password }),
    { headers: XHR_HEADERS },
  );
  if (res.status !== 200) return null;
  return accessTokenFrom(res);
}

/** Headers com Bearer token. */
export function authHeaders(token) {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  };
}

/**
 * Payload de anamnese padrão para testes (campos reais do AnamneseSerializer).
 * Atenção: POST /anamnese tem throttle próprio (20/hora por usuário em produção).
 */
export const ANAMNESE_PAYLOAD = JSON.stringify({
  idade: 28, sexo: 'M', peso: 75.0, altura: 178.0,
  nivel_atividade: 'moderate', objetivo: 'lose', meals_per_day: 4,
  restricoes: '', allergies: '', food_preferences: '',
});
