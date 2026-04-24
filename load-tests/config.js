/** Configuração compartilhada entre os scripts k6. */

export const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';
export const API      = `${BASE_URL}/api/v1`;

/** Cria um usuário e retorna { token, userId, email }. */
export function registerUser(http, email, password = 'LoadTest@123') {
  const res = http.post(
    `${API}/auth/register`,
    JSON.stringify({ nome: 'Load Test', email, senha: password }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  if (res.status !== 201) {
    return null;
  }
  const body = JSON.parse(res.body);
  return { token: body.token, userId: body.user?.id, email };
}

/** Faz login e retorna o token. */
export function loginUser(http, email, password = 'LoadTest@123') {
  const res = http.post(
    `${API}/auth/login`,
    JSON.stringify({ email, password }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  if (res.status !== 200) return null;
  return JSON.parse(res.body).token;
}

/** Headers com Bearer token. */
export function authHeaders(token) {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  };
}

/** Payload de anamnese padrão para testes. */
export const ANAMNESE_PAYLOAD = JSON.stringify({
  age: 28, gender: 'M', weight_kg: 75.0, height_cm: 178.0,
  activity_level: 'moderate', goal: 'lose', meals_per_day: 4,
  dietary_restrictions: '', allergies: '', food_preferences: '',
  goal_description: 'Teste de carga',
});
