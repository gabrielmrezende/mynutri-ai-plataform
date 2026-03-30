import json
import os
import logging
import urllib.request
import urllib.error

from .models import Anamnese, DietPlan, Meal

logger = logging.getLogger(__name__)


class AIService:
    """
    Responsável por chamar a API de IA e transformar a resposta
    em registros de DietPlan e Meal no banco de dados.

    Usa as variáveis de ambiente:
        AI_API_KEY  → chave de autenticação da IA
        AI_API_URL  → endpoint da API (ex: OpenAI, Gemini, etc.)
    """

    def __init__(self):
        self.api_key = os.getenv('AI_API_KEY', '')
        self.api_url = os.getenv('AI_API_URL', '')

    def _build_prompt(self, anamnese: Anamnese) -> str:
        """
        Monta o prompt conforme o padrão definido em docs/PROMPTS.md,
        exigindo resposta em JSON estruturado.
        """
        restricoes = anamnese.food_restrictions or 'Nenhuma'
        preferencias = anamnese.food_preferences or 'Sem preferências específicas'

        return f"""Com base nas seguintes informações do usuário, gere um plano alimentar diário equilibrado.

Informações do usuário:

Idade: {anamnese.age}
Sexo: {anamnese.get_gender_display()}
Peso: {anamnese.weight_kg} kg
Altura: {anamnese.height_cm} cm
Nível de atividade: {anamnese.get_activity_display_pt()}
Objetivo: {anamnese.get_goal_display_pt()}
Restrições alimentares: {restricoes}
Preferências alimentares: {preferencias}
Refeições por dia: {anamnese.meals_per_day}

Crie um plano alimentar contendo exatamente {anamnese.meals_per_day} refeições com estimativa calórica aproximada.

IMPORTANTE: Sua resposta DEVE OBRIGATORIAMENTE estar em formato JSON válido e estruturado, sem nenhum texto adicional antes ou depois. Use obrigatoriamente a seguinte estrutura:

{{
  "calorias_totais": 2500,
  "objetivo": "Ganho de massa",
  "refeicoes": [
    {{
      "nome_refeicao": "Café da manhã",
      "descricao_refeicao": "2 ovos mexidos, 1 fatia de pão integral com queijo branco.",
      "calorias_estimadas": 350
    }}
  ]
}}"""

    def _call_api(self, prompt: str) -> dict:
        """
        Realiza a chamada HTTP à API de IA.
        Suporta qualquer API compatível com o formato OpenAI Chat Completions.
        """
        if not self.api_key or not self.api_url:
            raise ValueError(
                'AI_API_KEY e AI_API_URL devem estar configurados no arquivo .env'
            )

        payload = json.dumps({
            'model': os.getenv('AI_MODEL', 'gpt-3.5-turbo'),
            'messages': [
                {
                    'role': 'system',
                    'content': 'Você é um nutricionista especializado. Sempre responda APENAS em JSON válido, sem texto adicional.',
                },
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0.7,
        }).encode('utf-8')

        req = urllib.request.Request(
            self.api_url,
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}',
            },
            method='POST',
        )

        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read().decode('utf-8')
            return json.loads(raw)

    def _parse_response(self, api_response: dict) -> dict:
        """
        Extrai o conteúdo JSON gerado pela IA da resposta da API.
        Suporta o formato padrão OpenAI (choices[0].message.content).
        """
        try:
            content = api_response['choices'][0]['message']['content']
            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error('Falha ao parsear resposta da IA: %s | Resposta: %s', e, api_response)
            raise ValueError('A IA retornou um formato inesperado. Tente novamente.')

    def generate_diet(self, anamnese: Anamnese) -> DietPlan:
        """
        Método principal: monta o prompt, chama a IA, parseia JSON e
        persiste DietPlan + Meals no banco de dados.

        Returns:
            DietPlan: objeto criado no banco com todas as refeições.

        Raises:
            ValueError: se a IA estiver mal configurada ou retornar formato inválido.
            Exception: se a chamada HTTP falhar.
        """
        prompt = self._build_prompt(anamnese)
        logger.info('Gerando dieta para usuário %s via IA...', anamnese.user_id)

        try:
            raw_response = self._call_api(prompt)
        except urllib.error.HTTPError as e:
            logger.error('Erro HTTP na chamada à IA: %s', e)
            raise Exception(f'Falha ao contatar a API da IA: HTTP {e.code}')
        except Exception as e:
            logger.error('Erro inesperado na chamada à IA: %s', e)
            raise Exception('Falha ao gerar o plano alimentar via IA, tente novamente mais tarde.')

        diet_data = self._parse_response(raw_response)

        # Persiste o DietPlan com o JSON bruto completo
        diet_plan = DietPlan.objects.create(
            user=anamnese.user,
            anamnese=anamnese,
            raw_response=diet_data,
            total_calories=diet_data.get('calorias_totais'),
            goal_description=diet_data.get('objetivo', ''),
        )

        # Persiste cada refeição individualmente
        refeicoes = diet_data.get('refeicoes', [])
        meals_to_create = [
            Meal(
                diet_plan=diet_plan,
                meal_name=r.get('nome_refeicao', ''),
                description=r.get('descricao_refeicao', ''),
                calories=r.get('calorias_estimadas', 0),
                order=idx,
            )
            for idx, r in enumerate(refeicoes)
        ]
        Meal.objects.bulk_create(meals_to_create)

        logger.info(
            'Dieta gerada com sucesso: DietPlan#%s (%d refeições, %s kcal)',
            diet_plan.id, len(meals_to_create), diet_plan.total_calories
        )
        return diet_plan
