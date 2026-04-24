# Load Tests — MyNutri AI

Scripts k6 para medir a performance e encontrar os limites da aplicação.

## Instalação do k6

```bash
# macOS
brew install k6

# Windows (Chocolatey)
choco install k6

# Linux (Debian/Ubuntu)
sudo gpg -k
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update && sudo apt-get install k6

# Docker
docker pull grafana/k6
```

## Scripts disponíveis

| Script | VUs | Duração | Propósito |
|--------|-----|---------|-----------|
| `smoke.js` | 1 | ~10s | Sanidade — valida que endpoints respondem |
| `load.js` | 10→50 | ~2min | Baseline — performance em carga típica |
| `stress.js` | 20→200 | ~3min | Stress — encontra o ponto de quebra |

## Como rodar

```bash
# Servidor deve estar rodando antes
python manage.py runserver

# Smoke test (começa sempre por aqui)
k6 run load-tests/smoke.js

# Load test (carga típica)
k6 run load-tests/load.js

# Stress test (staging only — NUNCA em produção)
k6 run load-tests/stress.js

# Contra o servidor de produção
BASE_URL=https://mynutriai.onrender.com k6 run load-tests/smoke.js

# Com relatório HTML
k6 run --out json=results.json load-tests/load.js
k6-reporter results.json
```

## Thresholds esperados (baseline)

Resultados coletados em ambiente local (MacBook M1, SQLite):

| Métrica | Threshold | Significado |
|---------|-----------|-------------|
| `http_req_duration p(95)` | < 2000ms | 95% das requests |
| `http_req_failed` | < 5% | Taxa de falhas globais |
| `profile p(95)` | < 800ms | Endpoint de perfil |

> Em produção (Render + PostgreSQL + Redis), espera-se ~30% de melhora no
> throughput e ~15% de redução na latência em relação ao ambiente local.

## Interpretando os resultados

```
✓ http_req_duration.............: avg=124ms  min=12ms   med=89ms   max=1.2s p(90)=210ms p(95)=380ms
✓ http_req_failed...............: 0.00%  ✓ 0  ✗ 1250
✓ profile_latency_ms............: avg=95ms   min=10ms   med=72ms   max=980ms
```

- `avg` > `med` indica outliers altos — investigar os requests lentos
- `p(95)` acima do threshold → escalar workers ou otimizar queries
- `http_req_failed > 5%` → investigar logs de erros (Sentry)
