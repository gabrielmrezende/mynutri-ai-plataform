from django.contrib import admin
from .models import Anamnese, DietPlan, Meal


class MealInline(admin.TabularInline):
    """Exibe as refeições diretamente dentro do painel do Plano Alimentar."""
    model = Meal
    extra = 0
    readonly_fields = ('meal_name', 'description', 'calories', 'order')
    ordering = ('order',)


@admin.register(Anamnese)
class AnamneseAdmin(admin.ModelAdmin):
    """Painel de administração para as Anamneses."""
    list_display = ('user', 'goal', 'weight_kg', 'height_cm', 'activity_level', 'answered_at')
    list_filter = ('goal', 'activity_level', 'gender')
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('answered_at',)
    ordering = ('-answered_at',)

    fieldsets = (
        ('Usuário', {
            'fields': ('user',),
        }),
        ('Dados Físicos', {
            'fields': ('age', 'gender', 'weight_kg', 'height_cm'),
        }),
        ('Estilo de Vida', {
            'fields': ('activity_level', 'goal', 'meals_per_day'),
        }),
        ('Alimentação', {
            'fields': ('food_restrictions', 'food_preferences', 'allergies'),
        }),
        ('Metadados', {
            'fields': ('answered_at',),
            'classes': ('collapse',),
        }),
    )


@admin.register(DietPlan)
class DietPlanAdmin(admin.ModelAdmin):
    """Painel de administração para os Planos Alimentares."""
    list_display = ('user', 'total_calories', 'goal_description', 'anamnese', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('raw_response', 'created_at')
    ordering = ('-created_at',)
    inlines = [MealInline]

    fieldsets = (
        ('Usuário e Origem', {
            'fields': ('user', 'anamnese'),
        }),
        ('Resumo do Plano', {
            'fields': ('total_calories', 'goal_description'),
        }),
        ('Resposta Bruta da IA', {
            'fields': ('raw_response',),
            'classes': ('collapse',),
            'description': 'JSON completo retornado pela IA.',
        }),
        ('Metadados', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )


@admin.register(Meal)
class MealAdmin(admin.ModelAdmin):
    """Painel de administração para Refeições individuais."""
    list_display = ('meal_name', 'calories', 'order', 'diet_plan')
    list_filter = ('diet_plan__user',)
    search_fields = ('meal_name', 'diet_plan__user__email')
    ordering = ('diet_plan', 'order')
