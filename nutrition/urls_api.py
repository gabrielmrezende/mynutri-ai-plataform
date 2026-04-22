from django.urls import path
from .api_views import (
    AnamneseAPIView,
    AnamneseLastAPIView,
    DietGenerateAPIView,
    DietJobStatusAPIView,
    DietAPIView,
    DietListAPIView,
    DietDetailAPIView,
    DietPDFAPIView,
)

urlpatterns = [
    # POST /api/v1/anamnese               → Salva respostas do questionário nutricional
    path('anamnese', AnamneseAPIView.as_view(), name='api-anamnese'),

    # GET  /api/v1/anamnese/last          → Retorna a anamnese mais recente (pré-preenchimento)
    path('anamnese/last', AnamneseLastAPIView.as_view(), name='api-anamnese-last'),

    # POST /api/v1/diet/generate          → Enfileira geração de dieta (retorna job_id)
    path('diet/generate', DietGenerateAPIView.as_view(), name='api-diet-generate'),

    # GET  /api/v1/diet/status/<job_id>   → Polling do estado de um job de geração
    path('diet/status/<int:job_id>', DietJobStatusAPIView.as_view(), name='api-diet-status'),

    # GET  /api/v1/diet                   → Retorna o plano alimentar mais recente
    path('diet', DietAPIView.as_view(), name='api-diet'),

    # GET  /api/v1/diet/list              → Histórico completo de planos alimentares
    path('diet/list', DietListAPIView.as_view(), name='api-diet-list'),

    # GET  /api/v1/diet/<id>/pdf          → Baixa o plano alimentar em PDF
    path('diet/<int:pk>/pdf', DietPDFAPIView.as_view(), name='api-diet-pdf'),

    # GET  /api/v1/diet/<id>              → Plano alimentar específico por ID
    path('diet/<int:pk>', DietDetailAPIView.as_view(), name='api-diet-detail'),
]
