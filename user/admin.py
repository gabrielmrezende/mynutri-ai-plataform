from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Profile


class ProfileInline(admin.StackedInline):
    """Mostra o Profile dentro da página do usuário no admin."""
    model = Profile
    can_delete = False
    verbose_name = 'Perfil Nutricional'
    verbose_name_plural = 'Perfil Nutricional'


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """Admin customizado para o CustomUser."""
    inlines = [ProfileInline]

    # Adiciona os campos extras na lista de usuários
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff')
    
    # Adiciona os campos extras no formulário de edição
    fieldsets = UserAdmin.fieldsets + (
        ('Dados Extras', {
            'fields': ('phone', 'date_of_birth'),
        }),
    )

    # Adiciona os campos extras no formulário de criação
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Dados Extras', {
            'fields': ('phone', 'date_of_birth'),
        }),
    )


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """Admin para o Profile (também acessível separadamente)."""
    list_display = ('user', 'goal', 'weight', 'height', 'activity_level')
    list_filter = ('goal', 'activity_level', 'gender')
    search_fields = ('user__username', 'user__email')
