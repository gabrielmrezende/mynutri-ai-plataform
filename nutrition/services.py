import json
import os
import logging
import urllib.request
import urllib.error

from .models import Anamnese, DietPlan, Meal
from .prompts import SYSTEM_PROMPT, build_diet_prompt

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
        return build_diet_prompt(anamnese)

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
                {'role': 'system', 'content': SYSTEM_PROMPT},
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

        with urllib.request.urlopen(req, timeout=120) as response:
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
            total_calories=diet_data.get('calories'),
            goal_description=diet_data.get('notes', ''),
        )

        # Persiste cada refeição individualmente
        # Novo formato: meals[].foods[] — monta descrição a partir dos alimentos
        meals_to_create = []
        for idx, meal in enumerate(diet_data.get('meals', [])):
            foods = meal.get('foods', [])
            description = ', '.join(
                f'{f.get("name", "")} ({f.get("quantity", "")})'
                for f in foods
            )
            total_meal_calories = sum(f.get('calories', 0) for f in foods)
            meals_to_create.append(
                Meal(
                    diet_plan=diet_plan,
                    meal_name=meal.get('name', ''),
                    description=description,
                    calories=total_meal_calories,
                    order=idx,
                )
            )
        Meal.objects.bulk_create(meals_to_create)

        logger.info(
            'Dieta gerada com sucesso: DietPlan#%s (%d refeições, %s kcal)',
            diet_plan.id, len(meals_to_create), diet_plan.total_calories
        )
        return diet_plan
