# Prompts de Inteligência Artificial - MyNutri AI

## Geração de Dieta

O prompt é construído dinamicamente em `nutrition/prompts.py` pela função `build_diet_prompt(anamnese)`.

### Campos utilizados da Anamnese

| Campo do Model | Descrição |
| --- | --- |
| `age` | Idade em anos |
| `gender` | Sexo (Masculino / Feminino / Outro) |
| `weight_kg` | Peso em kg |
| `height_cm` | Altura em cm |
| `activity_level` | Nível de atividade (display em PT) |
| `goal` | Objetivo (display em PT) |
| `food_preferences` | Preferências alimentares (ponto de partida) |
| `food_restrictions` | Restrições alimentares (evitar) |
| `allergies` | Alergias (proibido incluir) |
| `meals_per_day` | Número de refeições por dia |

### Lógica de cálculo calórico solicitada à IA

A IA é instruída a calcular internamente:

1. **TMB** via Mifflin-St Jeor
2. **TDEE** = TMB × fator de atividade
3. **Meta calórica** = TDEE ajustado pelo objetivo (−400~500 para emagrecimento, neutro para manutenção, +300~400 para hipertrofia)

### Formato de resposta esperado (JSON)

```json
{
  "goal_description": "Emagrecimento saudável — déficit calórico moderado de ~400 kcal/dia",
  "calories": 1900,
  "macros": {
    "protein_g": 150,
    "carbs_g": 190,
    "fat_g": 55
  },
  "meals": [
    {
      "name": "Café da manhã",
      "time_suggestion": "07:00",
      "foods": [
        {
          "name": "Ovos mexidos",
          "quantity": "3 unidades (150g)",
          "calories": 220
        },
        {
          "name": "Pão integral",
          "quantity": "2 fatias (60g)",
          "calories": 150
        }
      ]
    }
  ],
  "substitutions": [
    {
      "food": "Arroz integral",
      "alternatives": ["Batata-doce", "Macarrão integral", "Mandioca", "Quinoa"]
    }
  ],
  "notes": "Beba pelo menos 2 a 3 litros de água por dia..."
}
```

### Mapeamento JSON → banco de dados

| Campo JSON | Campo `DietPlan` |
| --- | --- |
| `calories` | `total_calories` |
| `goal_description` | `goal_description` |
| JSON completo | `raw_response` |

| Campo JSON | Campo `Meal` |
| --- | --- |
| `meals[].name` + `time_suggestion` | `meal_name` (ex: "Almoço (12:00)") |
| `meals[].foods[]` formatados | `description` (lista com bullet points) |
| soma de `foods[].calories` | `calories` |
| índice do array | `order` |
