/**
 * Stress test — encontra o ponto de quebra da aplicação.
 * Aumenta a carga progressivamente até o sistema degradar ou falhar.
 * Use APENAS em ambiente de staging — nunca em produção.
 *
 * Uso: k6 run load-tests/stress.js
 * Abortará automaticamente se a taxa de erros ultrapassar 20%.
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';
import { API, registerUser, authHeaders } from './config.js';

const errorRate = new Rate('error_rate');

export const options = {
  stages: [
    { duration: '30s', target: 20  },
    { duration: '30s', target: 50  },
    { duration: '30s', target: 100 },
    { duration: '30s', target: 150 },
    { duration: '30s', target: 200 },
    { duration: '60s', target: 200 },  // mantém o pico
    { duration: '30s', target: 0   },  // recovery
  ],
  thresholds: {
    error_rate:        [{ threshold: 'rate<0.20', abortOnFail: true }],  // aborta se > 20% erros
    http_req_duration: ['p(99)<5000'],   // 99% das requests < 5s no pico
  },
};

export function setup() {
  const users = [];
  for (let i = 0; i < 50; i++) {
    const email = `stress_${Date.now()}_${i}@test.com`;
    const user  = registerUser(http, email);
    if (user) users.push(user);
  }
  return { users };
}

export default function ({ users }) {
  const user = users[Math.floor(Math.random() * users.length)];
  if (!user) return;

  const headers = authHeaders(user.token);

  const res = http.get(`${API}/user/profile`, { headers });
  const ok  = check(res, { 'status 200': (r) => r.status === 200 });
  errorRate.add(!ok);

  sleep(0.3);
}
