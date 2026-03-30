# Prompts de Inteligência Artificial - MyNutri AI

## Geração de Dieta

Prompt utilizado para gerar dietas personalizadas com base na anamnese do usuário.

Exemplo de prompt:

"Com base nas seguintes informações do usuário, gere um plano alimentar diário equilibrado.

Informações do usuário:

Idade: {idade}
Sexo: {sexo}
Peso: {peso}
Altura: {altura}
Nível de atividade: {atividade}
Objetivo: {objetivo}
Restrições alimentares: {restricoes}

Crie um plano alimentar contendo:

- café da manhã
- almoço
- jantar
- lanches

Inclua estimativa calórica aproximada.

**IMPORTANTE: Sua resposta DEVE OBRIGATORIAMENTE estar em formato JSON válido e estruturado, sem nenhum texto adicional antes ou depois. Use obrigatoriamente a seguinte estrutura:**
```json
{
  "calorias_totais": 2500,
  "objetivo": "Ganho de massa",
  "refeicoes": [
    {
      "nome_refeicao": "Café da manhã",
      "descricao_refeicao": "2 ovos mexidos, 1 fatia de pão integral com queijo branco, 1 xícara de café preto sem açúcar.",
      "calorias_estimadas": 350
    },
    {
      "nome_refeicao": "Almoço",
      "descricao_refeicao": "150g de peito de frango grelhado, 100g de arroz integral, salada de folhas à vontade.",
      "calorias_estimadas": 600
    }
  ]
}
```"