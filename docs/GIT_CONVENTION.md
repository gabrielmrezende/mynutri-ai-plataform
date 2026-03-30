# Git Convention

Para manter o histórico e a organização do projeto, seguimos convenções padronizadas de commits e branches.

---

## Branches

### Nomenclatura

Todas as branches devem seguir este formato:

```
tipo/descricao-curta
```

Use kebab-case (letras minúsculas separadas por hífen) na descrição.

### Tipos de branch

| Tipo | Uso | Exemplo |
|------|-----|---------|
| `feat` | Nova funcionalidade | `feat/questionario-nutricional` |
| `fix` | Correção de bug | `fix/calculo-de-macros` |
| `hotfix` | Correção urgente em produção | `hotfix/erro-no-pagamento` |
| `refactor` | Refatoração sem mudança de comportamento | `refactor/servicos-de-autenticacao` |
| `docs` | Mudanças apenas na documentação | `docs/documentacao-da-api` |
| `chore` | Tarefas de manutenção (configs, dependências) | `chore/atualiza-dependencias` |

### Branches protegidas

| Branch | Finalidade |
|--------|-----------|
| `main` | Código em produção. Nunca recebe commits diretos |
| `develop` | Branch de desenvolvimento. Merge de todas as features |

### Fluxo de trabalho

```
main
 └── develop
      ├── feat/nova-funcionalidade
      ├── fix/correcao-de-bug
      └── refactor/melhoria-de-codigo
```

1. Crie sua branch sempre a partir de `develop`
2. Desenvolva e faça commits na sua branch
3. Abra um Pull Request de volta para `develop`
4. Após revisão e aprovação, faça o merge
5. Deploys para produção saem de `main`

---

## Commits

Usamos o padrão [Conventional Commits](https://www.conventionalcommits.org/).

### Formato

```
tipo: descrição curta da mudança
```

A descrição deve ser escrita no presente do indicativo e em minúsculas.

### Tipos de commit

| Tipo | Uso |
|------|-----|
| `feat` | Nova funcionalidade |
| `fix` | Correção de bug |
| `docs` | Mudanças apenas na documentação |
| `refactor` | Refatoração sem mudança de comportamento |
| `style` | Formatação, ponto e vírgula, espaços (sem lógica) |
| `test` | Adição ou correção de testes |
| `chore` | Atualizações de dependências, configurações, CI |
| `perf` | Melhoria de performance |

### Exemplos

```
feat: cria questionário nutricional
fix: corrige cálculo de macros
docs: adiciona documentação da API
refactor: reorganiza serviços de autenticação
style: formata arquivos com prettier
test: adiciona testes unitários para cálculo de macros
chore: atualiza dependências do projeto
perf: otimiza query de busca de usuários
```

### Boas práticas

- Use o tipo correto — isso facilita o `CHANGELOG` e o entendimento do histórico
- Escreva a descrição em minúsculas
- Seja específico: prefira `fix: corrige erro no cálculo de IMC` a `fix: corrige bug`
- Cada commit deve representar **uma única mudança lógica**
- Evite commits como `fix: ajustes`, `feat: coisas`, `wip`

### Commits com escopo (opcional)

Para projetos maiores, você pode adicionar um escopo para indicar qual parte do sistema foi alterada:

```
tipo(escopo): descrição curta
```

```
feat(auth): implementa login com Google
fix(dieta): corrige geração de plano alimentar
refactor(api): reorganiza rotas de usuário
```

---

## Resumo rápido

| Situação | Branch | Commit |
|----------|--------|--------|
| Nova tela de login | `feat/tela-de-login` | `feat(auth): cria tela de login` |
| Bug no cálculo de calorias | `fix/calculo-calorias` | `fix: corrige cálculo de calorias diárias` |
| Atualizar README | `docs/atualiza-readme` | `docs: atualiza instruções de instalação` |
| Limpar código legado | `refactor/limpeza-auth` | `refactor: remove código legado de autenticação` |