# core/apps.py
"""
Configuración de la app `core`.

Registra las señales para invalidar caché y aplicar cambios
de configuración en runtime.
"""
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Núcleo del sistema"

    def ready(self):
        """
        Importa signals (módulo vacío, conservado por compatibilidad).
        No se necesita registrar ningún receptor.
        """
        try:
            import core.signals  # noqa: F401
        except Exception:
            pass