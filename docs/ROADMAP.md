# Roadmap — MyNutri AI

---

## ✅ MVP (Concluído — Março 2026)

- [x] Cadastro de usuário com email único
- [x] Login com JWT (access + refresh token)
- [x] Questionário de anamnese em 5 steps com validação
- [x] Integração com API de IA (OpenAI-compatible)
- [x] Geração automática de dieta com persistência no banco
- [x] Exibição do plano alimentar com calorias por refeição
- [x] CORS + rate limiting + segurança básica

---

## 🔜 Versão 2 — Histórico e Dashboard

- [ ] Histórico de dietas (`GET /api/v1/diet/list`)
- [ ] Dieta por ID (`GET /api/v1/diet/<id>`)
- [ ] Página `historico.html`
- [ ] Dashboard nutricional (`dashboard.html`)
- [ ] Ajuste automático de dieta ("Aumentar/Diminuir calorias")
- [ ] Dark mode toggle
- [ ] Testes automatizados: pytest (backend) + Cypress (frontend)

---

## 🚀 Versão 3 — Deploy e Produção

- [ ] CI/CD com GitHub Actions
- [ ] Docker + docker-compose
- [ ] Deploy em servidor cloud (Railway, Render ou VPS)
- [ ] Migração para PostgreSQL em produção
- [ ] Monitoramento de erros (Sentry)
- [ ] CDN para assets frontend

---

## 📱 Versão 3.5 — Mobile e Integrações

- [ ] Exportação do plano alimentar em PDF
- [ ] Integração com API de alimentos (FatSecretAPI)
- [ ] React Native app (iOS + Android)
- [ ] Integração com wearables (Fitbit, Apple Watch)
- [ ] Push notifications para refeições

---

## 🤖 Futuro — IA Avançada

- [ ] Nutricionista digital baseado em IA com memória de sessão
- [ ] Fine-tuning com feedback dos usuários
- [ ] Planos alimentares adaptativos (ajuste semana a semana)
- [ ] Geração de receitas automática
- [ ] Sistema de assinatura premium (SaaS)