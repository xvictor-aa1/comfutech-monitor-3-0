# monitoreo/management/commands/poll_health.py
from django.core.management.base import BaseCommand

from monitoreo.services.health import poll_health
from monitoreo.services import influx_writer


class Command(BaseCommand):
    help = "Ejecuta una sola pasada del poller de Core Health"

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== POLL HEALTH ===\n"
        ))

        stats = None
        try:
            stats = poll_health()
        finally:
            # Cerrar el cliente de InfluxDB ANTES de que Python
            # destruya los módulos (evita el TypeError del __del__)
            try:
                influx_writer.close()
            except Exception:
                pass

        if stats:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"  devices: {stats.get('devices', 0)}"))
            self.stdout.write(self.style.WARNING(f"  errors: {stats.get('errors', 0)}"))
            self.stdout.write(self.style.SUCCESS(f"  alerts: {stats.get('alerts', 0)}"))
            self.stdout.write(self.style.SUCCESS(f"  duration_s: {stats.get('duration_s', 0)}"))
            self.stdout.write("")