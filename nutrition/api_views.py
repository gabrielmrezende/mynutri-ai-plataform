from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle

from .models import Anamnese, DietPlan
from .serializers import AnamneseSerializer, DietPlanSerializer
from .services import AIService


class AnamneseAPIView(APIView):
    """
    POST /api/anamnese
    Salva as respostas do questionário nutricional do usuário logado.
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AnamneseSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        anamnese = serializer.save(user=request.user)
        return Response(
            AnamneseSerializer(anamnese).data,
            status=status.HTTP_201_CREATED,
        )


class DietGenerateAPIView(APIView):
    """
    POST /api/diet/generate
    Aciona a IA para gerar um plano alimentar com base na última anamnese do usuário.
    Requer: Authorization: Bearer <token>
    Limite: 3 gerações por dia por usuário.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'diet_generate'

    def post(self, request):
        # Busca a anamnese mais recente do usuário
        anamnese = (
            Anamnese.objects.filter(user=request.user)
            .order_by('-answered_at')
            .first()
        )

        if not anamnese:
            return Response(
                {'error': 'Nenhuma anamnese encontrada. Responda o questionário primeiro.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            service = AIService()
            diet_plan = service.generate_diet(anamnese)
        except ValueError as e:
            # Erro de configuração ou formato inválido da IA
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            # Falha de comunicação com a API da IA
            return Response(
                {'error': 'Falha ao gerar o plano alimentar via IA, tente novamente mais tarde.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            DietPlanSerializer(diet_plan).data,
            status=status.HTTP_201_CREATED,
        )


class DietAPIView(APIView):
    """
    GET /api/diet
    Retorna o plano alimentar mais recente do usuário logado.
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        diet_plan = (
            DietPlan.objects.filter(user=request.user)
            .prefetch_related('meals')
            .order_by('-created_at')
            .first()
        )

        if not diet_plan:
            return Response(
                {'error': 'Você ainda não possui um plano alimentar gerado.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(DietPlanSerializer(diet_plan).data, status=status.HTTP_200_OK)
