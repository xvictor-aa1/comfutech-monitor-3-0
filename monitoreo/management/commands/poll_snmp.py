# monitoreo/management/commands/poll_snmp.py
"""
Ejecuta una sola pasada del poller SNMP de tráfico.

Uso:
    python manage.py poll_snmp

v4: antes de cerrar el cliente de InfluxDB, se hace `flush()` para
volcar el buffer batch acumulado por el poller. Sin esto, los puntos
quedarían en memoria del thread y se perderían al terminar el
proceso (el scheduler sí hace flush, pero los comandos CLI no pasan
por él).
"""
from django.core.management.base import BaseCommand

from monitoreo.services.traffic import poll_traffic
from monitoreo.services import influx_writer


class Command(BaseCommand):
    help = "Ejecuta una sola pasada del poller SNMP de tráfico"

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== POLL SNMP (Tráfico) ===\n"
        ))

        stats = None
        try:
            stats = poll_traffic()
        finally:
            # v4: volcar el buffer batch a InfluxDB antes de cerrar.
            try:
                influx_writer.flush()
            except Exception:
                pass
            # Cerrar el cliente de InfluxDB antes de que Python
            # destruya los módulos (evita el TypeError del __del__).
            try:
                influx_writer.close()
            except Exception:
                pass

        if stats:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"  devices: {stats.get('devices', 0)}"))
            self.stdout.write(self.style.SUCCESS(f"  interfaces: {stats.get('interfaces', 0)}"))
            self.stdout.write(self.style.WARNING(f"  errors: {stats.get('errors', 0)}"))
            self.stdout.write(self.style.SUCCESS(f"  duration_s: {stats.get('duration_s', 0)}"))
            self.stdout.write("")