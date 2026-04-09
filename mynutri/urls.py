from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.db import connection


def home(request):
    return JsonResponse({
        'status': 'ok',
        'service': 'MyNutri AI API',
        'message': 'API is running',
    })


def health_check(request):
    try:
        connection.ensure_connection()
        return JsonResponse({'status': 'ok'})
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)


urlpatterns = [
    path('', home, name='home'),
    path('health/', health_check, name='health-check'),
    path('admin/', admin.site.urls),
    path('api/v1/', include('user.urls_api')),
    path('api/v1/', include('nutrition.urls_api')),
]
