/**
 * Smoke test — 1 usuário virtual, 1 iteração.
 * Valida que os endpoints principais estão respondendo corretamente.
 * Roda em < 30 segundos.
 *
 * Uso: k6 run load-tests/smoke.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';
import { BASE_URL, API, registerUser, authHeaders, ANAMNESE_PAYLOAD } from './config.js';

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    http_req_failed:   ['rate<0.01'],   // < 1% de falhas
    http_req_duration: ['p(95)<3000'],  // 95% das requests < 3s
  },
};

export default function () {
  const email = `smoke_${Date.now()}@test.com`;

  // 1. Cadastro
  const registerRes = http.post(
    `${API}/auth/register`,
    JSON.stringify({ nome: 'Smoke Test', email, senha: 'LoadTest@123' }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  check(registerRes, {
    'register: status 201':      (r) => r.status === 201,
    'register: tem token':       (r) => !!JSON.parse(r.body).token,
    'register: seta cookie':     (r) => r.headers['Set-Cookie']?.includes('mynutri_access'),
  });

  const token = JSON.parse(registerRes.body).token;
  const headers = authHeaders(token);

  sleep(0.5);

  // 2. Perfil
  const profileRes = http.get(`${API}/user/profile`, { headers });
  check(profileRes, {
    'profile: status 200':   (r) => r.status === 200,
    'profile: tem email':    (r) => !!JSON.parse(r.body).email,
  });

  sleep(0.5);

  // 3. Health check
  const healthRes = http.get(`${BASE_URL}/health/`);
  check(healthRes, {
    'health: status 200': (r) => r.status === 200,
    'health: status ok':  (r) => JSON.parse(r.body).status === 'ok',
  });

  sleep(0.5);

  // 4. Anamnese
  const anamneseRes = http.post(`${API}/anamnese`, ANAMNESE_PAYLOAD, { headers });
  check(anamneseRes, {
    'anamnese: status 201': (r) => r.status === 201,
  });

  sleep(0.5);

  // 5. Testimonials (público)
  const testimonialsRes = http.get(`${API}/testimonials`);
  check(testimonialsRes, {
    'testimonials: status 200': (r) => r.status === 200,
  });

  // 6. Logout
  const logoutRes = http.post(`${API}/auth/logout`, null, { headers });
  check(logoutRes, {
    'logout: status 200': (r) => r.status === 200,
  });
}
