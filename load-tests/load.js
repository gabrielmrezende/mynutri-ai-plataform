/**
 * Load test — baseline de performance com carga típica.
 * Simula 50 usuários simultâneos durante 2 minutos.
 * Foco: endpoints leves (perfil, histórico, anamnese). Diet/generate excluído
 * pois consome quota de IA — testar separado com mock se necessário.
 *
 * Uso: k6 run load-tests/load.js
 * Com servidor remoto: BASE_URL=https://myapp.onrender.com k6 run load-tests/load.js
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { API, registerUser, authHeaders, ANAMNESE_PAYLOAD } from './config.js';

// Métricas customizadas
const loginErrors    = new Counter('login_errors');
const profileLatency = new Trend('profile_latency_ms', true);
const anamneseErrors = new Counter('anamnese_errors');

export const options = {
  stages: [
    { duration: '30s', target: 10 },  // rampa de subida
    { duration: '60s', target: 50 },  // carga alvo
    { duration: '30s', target: 0  },  // rampa de descida
  ],
  thresholds: {
    http_req_failed:              ['rate<0.05'],    // < 5% de falhas globais
    http_req_duration:            ['p(95)<2000'],   // 95% < 2s
    'http_req_duration{name:profile}': ['p(95)<800'],  // perfil < 800ms
    login_errors:                 ['count<5'],      // < 5 erros de login total
  },
};

// Setup: cria um pool de usuários antes de iniciar o teste
// (executado uma vez por instância k6 antes dos VUs rodarem)
export function setup() {
  const users = [];
  for (let i = 0; i < 20; i++) {
    const email = `load_${Date.now()}_${i}@test.com`;
    const user  = registerUser(http, email);
    if (user) users.push(user);
  }
  return { users };
}

export default function ({ users }) {
  // Cada VU pega um usuário aleatório do pool
  const user = users[Math.floor(Math.random() * users.length)];
  if (!user) return;

  const headers = authHeaders(user.token);

  group('Perfil', () => {
    const start = Date.now();
    const res = http.get(`${API}/user/profile`, {
      headers,
      tags: { name: 'profile' },
    });
    profileLatency.add(Date.now() - start);

    check(res, {
      'profile: 200': (r) => r.status === 200,
    }) || loginErrors.add(1);
  });

  sleep(0.5);

  group('Anamnese', () => {
    const res = http.post(`${API}/anamnese`, ANAMNESE_PAYLOAD, { headers });
    const ok = check(res, {
      'anamnese: 2xx': (r) => r.status >= 200 && r.status < 300,
    });
    if (!ok) anamneseErrors.add(1);
  });

  sleep(0.5);

  group('Histórico de dietas', () => {
    const res = http.get(`${API}/diet/list`, { headers });
    check(res, {
      'diet/list: 200 ou 404': (r) => r.status === 200 || r.status === 404,
    });
  });

  sleep(1);
}
