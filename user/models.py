from django.db import models
from django.contrib.auth.models import AbstractUser


class CustomUser(AbstractUser):
    """Modelo de usuário customizado do MyNutri AI."""

    phone = models.CharField('Telefone', max_length=20, blank=True)
    date_of_birth = models.DateField('Data de Nascimento', null=True, blank=True)

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'

    def __str__(self):
        return self.email or self.username


class Profile(models.Model):
    """Perfil nutricional do usuário."""

    GENDER_CHOICES = [
        ('M', 'Masculino'),
        ('F', 'Feminino'),
        ('O', 'Outro'),
    ]

    ACTIVITY_LEVEL_CHOICES = [
        ('sedentary', 'Sedentário'),
        ('light', 'Levemente ativo'),
        ('moderate', 'Moderadamente ativo'),
        ('intense', 'Muito ativo'),
        ('athlete', 'Atleta'),
    ]

    GOAL_CHOICES = [
        ('lose', 'Emagrecimento'),
        ('maintain', 'Manutenção'),
        ('gain', 'Hipertrofia'),
    ]

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name='profile'
    )
    gender = models.CharField(
        'Sexo', max_length=1, choices=GENDER_CHOICES, blank=True
    )
    weight = models.DecimalField(
        'Peso (kg)', max_digits=5, decimal_places=2, null=True, blank=True
    )
    height = models.DecimalField(
        'Altura (cm)', max_digits=5, decimal_places=2, null=True, blank=True
    )
    activity_level = models.CharField(
        'Nível de Atividade', max_length=20,
        choices=ACTIVITY_LEVEL_CHOICES, blank=True
    )
    goal = models.CharField(
        'Objetivo', max_length=20, choices=GOAL_CHOICES, blank=True
    )
    allergies = models.TextField('Alergias Alimentares', blank=True)
    food_restrictions = models.TextField('Restrições Alimentares', blank=True)
    food_preferences = models.TextField('Preferências Alimentares', blank=True)
    meals_per_day = models.PositiveIntegerField('Refeições por dia', default=4)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Perfil'
        verbose_name_plural = 'Perfis'

    def __str__(self):
        return f'Perfil de {self.user.username}'
