from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .api_views import RegisterAPIView, ProfileAPIView

urlpatterns = [
    # POST /api/auth/register  → Criação de conta + retorna token JWT
    path('auth/register', RegisterAPIView.as_view(), name='api-register'),

    # POST /api/auth/login     → Login com email/senha → retorna access + refresh token
    path('auth/login', TokenObtainPairView.as_view(), name='api-login'),

    # POST /api/auth/token/refresh → Renova o access token usando o refresh token
    path('auth/token/refresh', TokenRefreshView.as_view(), name='api-token-refresh'),

    # GET /api/user/profile    → Dados do usuário logado
    path('user/profile', ProfileAPIView.as_view(), name='api-profile'),
]
