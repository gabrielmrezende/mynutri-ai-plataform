from rest_framework import status, serializers as drf_serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model

from .serializers import RegisterSerializer, UserProfileSerializer

User = get_user_model()


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Substitui o campo 'username' por 'email' na autenticação JWT.
    Como o sistema usa username=email internamente, apenas renomeamos o campo.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'] = drf_serializers.EmailField()
        del self.fields[self.username_field]

    def validate(self, attrs):
        attrs[self.username_field] = attrs.pop('email', '').lower()
        return super().validate(attrs)


class EmailTokenObtainPairView(TokenObtainPairView):
    """
    POST /api/auth/login
    Aceita { email, password } e retorna { token, refresh }.
    """
    serializer_class = EmailTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            # Renomeia 'access' para 'token' para consistência com o endpoint de registro
            response.data['token'] = response.data.pop('access')
        return response


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
