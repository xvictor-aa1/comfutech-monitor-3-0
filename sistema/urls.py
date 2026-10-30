# sistema/urls.py
"""
URL configuration for sistema project.

El admin de Django está expuesto en `/django-admin/` **siempre**
(no solo en DEBUG). El acceso está restringido por
`ComfutechAdminSite.has_permission()` a superusuarios activos.
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

from core.views_auth import CustomLoginView


urlpatterns = [
    # ============================================================
    # Autenticación
    # ============================================================
    path("accounts/login/", CustomLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),

    # ============================================================
    # Apps
    # ============================================================
    path("", include("core.urls")),
    path("equipos/", include("inventario.urls")),
    path("alertas/", include("alertas.urls")),
    path("monitoreo/", include("monitoreo.urls")),
    path("mantenimiento/", include("mantenimiento.urls")),

    # ============================================================
    # Django Admin — "puerta trasera"
    # ============================================================
    # Disponible siempre (DEBUG=True o False). El acceso está
    # restringido por `ComfutechAdminSite.has_permission()` a
    # superusuarios activos únicamente.
    #
    # La URL `/django-admin/` (en lugar de `/admin/`) es intencional:
    # no es la ruta estándar de Django, lo que reduce la superficie
    # de ataques por escaneo de bots.
    path("django-admin/", admin.site.urls),
]


# ============================================================
# Archivos estáticos en desarrollo
# ============================================================
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)