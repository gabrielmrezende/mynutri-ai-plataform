from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse, JsonResponse
from django.views.generic import TemplateView
from django.views.decorators.cache import cache_page
from django.db import connection

# 1 hora para páginas estáticas que não mudam por sessão
_CACHE_1H = cache_page(60 * 60)
# Páginas autenticadas não devem ser cacheadas no browser (dados pessoais)
_CACHE_NO_STORE = cache_page(0)


def health_check(request):
    try:
        connection.ensure_connection()
        return JsonResponse({'status': 'ok'})
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)


# Páginas públicas indexáveis (sitemap) e páginas do app (fora dos buscadores)
_PUBLIC_PAGES = ['/', '/auth/', '/termos/', '/privacidade/', '/contato/']
_PRIVATE_PAGES = ['/dieta/', '/perfil/', '/historico/', '/questionario/', '/api/', '/admin/']


def robots_txt(request):
    lines = ['User-agent: *']
    lines += [f'Allow: {p}' for p in _PUBLIC_PAGES]
    lines += [f'Disallow: {p}' for p in _PRIVATE_PAGES]
    lines += ['', f'Sitemap: {request.build_absolute_uri("/sitemap.xml")}', '']
    return HttpResponse('\n'.join(lines), content_type='text/plain; charset=utf-8')


def sitemap_xml(request):
    urls = ''.join(
        f'  <url><loc>{request.build_absolute_uri(p)}</loc></url>\n' for p in _PUBLIC_PAGES
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'{urls}'
        '</urlset>\n'
    )
    return HttpResponse(body, content_type='application/xml; charset=utf-8')


urlpatterns = [
    # Frontend pages — páginas públicas cacheadas por 1h; páginas autenticadas sem cache
    path('', _CACHE_1H(TemplateView.as_view(template_name='index.html')), name='home'),
    path('auth/', _CACHE_1H(TemplateView.as_view(template_name='auth.html')), name='auth'),
    path('dieta/', _CACHE_NO_STORE(TemplateView.as_view(template_name='dieta.html')), name='dieta'),
    path('perfil/', _CACHE_NO_STORE(TemplateView.as_view(template_name='perfil.html')), name='perfil'),
    path('questionario/', _CACHE_NO_STORE(TemplateView.as_view(template_name='questionario.html')), name='questionario'),
    path('historico/', _CACHE_NO_STORE(TemplateView.as_view(template_name='historico.html')), name='historico'),
    path('contato/', _CACHE_1H(TemplateView.as_view(template_name='contato.html')), name='contato'),
    path('privacidade/', _CACHE_1H(TemplateView.as_view(template_name='privacidade.html')), name='privacidade'),
    path('termos/', _CACHE_1H(TemplateView.as_view(template_name='termos.html')), name='termos'),
    # SEO
    path('robots.txt', _CACHE_1H(robots_txt), name='robots-txt'),
    path('sitemap.xml', _CACHE_1H(sitemap_xml), name='sitemap-xml'),
    # Backend
    path('health/', health_check, name='health-check'),
    path('admin/', admin.site.urls),
    path('api/v1/', include('user.urls', namespace='user')),
    path('api/v1/', include('nutrition.urls', namespace='nutrition')),
]
