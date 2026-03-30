from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import RegisterSerializer, UserProfileSerializer


class RegisterAPIView(APIView):
    """
    POST /api/auth/register
    Cria uma nova conta e retorna o token JWT imediatamente,
    permitindo que o usuário já fique autenticado após o cadastro.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.save()

        # Gera par de tokens JWT para o novo usuário
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'token': str(refresh.access_token),
                'refresh': str(refresh),
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'nome': user.first_name,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class ProfileAPIView(APIView):
    """
    GET /api/user/profile
    Retorna os dados do usuário autenticado.
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)
