# monitoreo/apps.py
from django.apps import AppConfig


class MonitoreoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "monitoreo"
    verbose_name = "Monitoreo de Red"

    # NO añadimos ready() aquí.
    # El scheduler se arranca explícitamente con `manage.py run_monitor`,
    # no automáticamente al iniciar Django.