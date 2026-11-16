# core/apps.py
"""
Configuración de la app `core`.

Registra las señales para invalidar caché y aplicar cambios
de configuración en runtime.
"""
import logging

from django.apps import AppConfig

log = logging.getLogger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Núcleo del sistema"

    def ready(self):
        """
        Hook que se ejecuta cuando Django está completamente inicializado.

        Aplica la configuración SMTP de `config.toml` a
        `django.conf.settings` para que los envíos de email funcionen
        desde el primer momento, sin necesidad de guardar la config
        desde la UI o "probar el envío".

        ¿Por qué en `ready()` y no en `settings.py`? Porque `settings.py`
        se ejecuta ANTES de que el app registry esté listo, así que
        cualquier import de `core.runtime_config` puede fallar (app
        registry incompleto, settings aún en proceso de carga, etc.).
        `ready()` se ejecuta DESPUÉS de que todas las apps están cargadas
        y Django está completamente operativo.

        Si falla (config.toml corrupto, etc.), se loguea un warning.
        Los envíos de email tienen además un helper defensivo
        (`core.email_utils._ensure_email_config_applied()`) que reintenta
        aplicar la config antes de cada envío.
        """
        try:
            from core.runtime_config import apply_email_config_to_settings
            apply_email_config_to_settings()
            log.info(
                "Configuración SMTP aplicada desde config.toml al arrancar."
            )
        except Exception as e:
            log.warning(
                "No se pudo aplicar la configuración SMTP al arrancar: %s. "
                "Los envíos de email fallarán hasta que se configure o se "
                "guarde desde la UI.", e,
            )