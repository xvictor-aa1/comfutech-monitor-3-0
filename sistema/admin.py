# sistema/admin.py
"""
AdminSite personalizado de Comfutech Monitor.

Solo el **superadministrador** puede acceder. Se registra como el sitio
por defecto vía `ComfutechAdminConfig` en `sistema/apps.py`.

Este admin funciona como "puerta trasera" para:
  - Diagnóstico y corrección de datos en emergencias.
  - Operaciones masivas sobre modelos (reset, import/export).
  - Auditoría directa sobre la BD.

El acceso está restringido a `is_superuser=True`. Los usuarios con
`is_staff=True` pero `is_superuser=False` (rol "Administrador") NO
tienen acceso.
"""
from django.contrib.admin import AdminSite


class ComfutechAdminSite(AdminSite):
    """AdminSite con branding y permisos restringidos a superadmin."""

    # ---- Branding ----
    site_header = "Comfutech Monitor — Administración"
    site_title = "Comfutech Monitor"
    index_title = "Panel de Administración"
    site_url = "/"  # ← "Ver sitio" apunta al dashboard principal

    # Django 3.1+ muestra sidebar lateral en el admin
    enable_nav_sidebar = True

    def has_permission(self, request):
        """
        Solo superusuarios activos pueden acceder al admin.

        Los usuarios con `is_staff=True` (administradores) NO tienen
        acceso. Este es un admin de "god mode" exclusivo del superadmin.
        """
        return (
            request.user.is_active
            and request.user.is_authenticated
            and request.user.is_superuser
        )

    def each_context(self, request):
        """
        Añade variables de contexto a los templates del admin.

        Permite personalizar los templates sin sobrescribir archivos.
        """
        context = super().each_context(request)
        context["comfutech_app_name"] = "Comfutech Monitor"
        context["comfutech_admin_warning"] = (
            "Acceso restringido al superadministrador. "
            "Los cambios aquí afectan la BD directamente."
        )
        return context