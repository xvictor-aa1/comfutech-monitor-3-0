# sistema/apps.py
"""
Configuración del admin de Django para Comfutech Monitor.

Reemplaza el `AdminConfig` por defecto para usar `ComfutechAdminSite`
en lugar de `django.contrib.admin.sites.AdminSite`.

Uso en `settings.INSTALLED_APPS`:

    INSTALLED_APPS = [
        'sistema.apps.ComfutechAdminConfig',  # ← en lugar de 'django.contrib.admin'
        'django.contrib.auth',
        ...
    ]

Esto hace que `admin.site` sea una instancia de `ComfutechAdminSite`,
por lo que todos los `@admin.register(Model)` lo usan automáticamente.
"""
from django.contrib.admin.apps import AdminConfig


class ComfutechAdminConfig(AdminConfig):
    """Config que apunta al AdminSite personalizado."""

    # Ruta del AdminSite personalizado (se importa perezosamente)
    default_site = "sistema.admin.ComfutechAdminSite"