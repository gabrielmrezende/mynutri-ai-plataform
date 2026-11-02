"""
pdf_generator: texto dinâmico (vindo do LLM ou do usuário) é escapado antes
de virar Paragraph do ReportLab — '&' e tags como <img src=...> não podem
quebrar a geração nem ser interpretados como marcação.
"""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from nutrition.models import DietPlan, Meal
from nutrition.pdf_generator import generate_diet_pdf

User = get_user_model()

_EVIL_IMG = '<img src="/etc/passwd" width="500" height="500"/>'


@pytest.fixture
def evil_plan(db):
    user = User.objects.create_user(username='pdf@test.com', email='pdf@test.com', password='Senha-123')
    raw = {
        'calories': 2000,
        'macros': {'protein_g': 120, 'carbs_g': 220, 'fat_g': 60},
        'notes': '• Arroz & feijão\n• Evite <b>fritura</b> ' + _EVIL_IMG,
        'meals': [{
            'name': 'Almoço & cia',
            'time_suggestion': '12:00 <font size="40">',
            'foods': [
                {'name': 'Arroz & feijão ' + _EVIL_IMG, 'quantity': '100g <br/>', 'calories': 300},
                {'name': 'Frango <unclosed', 'quantity_g': 150, 'calories': '<b>240</b>'},
            ],
        }],
        'substitutions': [{'food': 'Arroz & feijão <i>', 'alternatives': ['Batata <img src=x>', 'Mandioca & cia']}],
    }
    plan = DietPlan.objects.create(
        user=user, raw_response=raw, total_calories=2000,
        goal_description='Emagrecer <b>rápido</b> & bem',
    )
    Meal.objects.create(diet_plan=plan, meal_name='Almoço & <i>cia', description='x', calories=540, order=0)
    return plan


@pytest.mark.django_db
class TestPdfEscaping:

    def test_gera_pdf_com_texto_malicioso(self, evil_plan):
        pdf = generate_diet_pdf(evil_plan)
        assert pdf.startswith(b'%PDF')

    def test_texto_dinamico_chega_escapado_ao_paragraph(self, evil_plan):
        from nutrition import pdf_generator
        texts = []
        real_paragraph = pdf_generator.Paragraph

        def spy(text, *args, **kwargs):
            texts.append(text)
            return real_paragraph(text, *args, **kwargs)

        with patch.object(pdf_generator, 'Paragraph', side_effect=spy):
            generate_diet_pdf(evil_plan)

        joined = '\n'.join(texts)
        assert '<img' not in joined
        assert '<unclosed' not in joined
        assert '&lt;img' in joined
        assert 'Arroz &amp; feijão' in joined

    def test_pdf_inclui_data_e_aviso(self, evil_plan):
        from nutrition import pdf_generator
        texts = []
        real_paragraph = pdf_generator.Paragraph
        with patch.object(pdf_generator, 'Paragraph',
                          side_effect=lambda t, *a, **k: texts.append(t) or real_paragraph(t, *a, **k)):
            generate_diet_pdf(evil_plan)
        joined = '\n'.join(texts)
        assert evil_plan.created_at.strftime('%d/%m/%Y') in joined
        assert 'não substitui' in joined
