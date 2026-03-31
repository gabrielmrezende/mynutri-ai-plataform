from django.urls import path
from .api_views import AnamneseAPIView, DietGenerateAPIView, DietAPIView

urlpatterns = [
    # POST /api/v1/anamnese           → Salva respostas do questionário nutricional
    path('anamnese', AnamneseAPIView.as_view(), name='api-anamnese'),

    # POST /api/v1/diet/generate      → Aciona a IA para gerar a dieta
    path('diet/generate', DietGenerateAPIView.as_view(), name='api-diet-generate'),

    # GET  /api/v1/diet               → Retorna o plano alimentar mais recente
    path('diet', DietAPIView.as_view(), name='api-diet'),
]
