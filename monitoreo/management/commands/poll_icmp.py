# monitoreo/management/commands/poll_icmp.py
from django.core.management.base import BaseCommand

from monitoreo.services.icmp_tcp import poll_icmp_tcp
from monitoreo.services import influx_writer


class Command(BaseCommand):
    help = "Ejecuta una sola pasada del poller ICMP/TCP"

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== POLL ICMP/TCP ===\n"
        ))

        stats = None
        try:
            stats = poll_icmp_tcp()
        finally:
            try:
                influx_writer.close()
            except Exception:
                pass

        if stats:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"  devices: {stats.get('devices', 0)}"))
            self.stdout.write(self.style.SUCCESS(f"  alive: {stats.get('alive', 0)}"))
            self.stdout.write(self.style.WARNING(f"  down: {stats.get('down', 0)}"))
            self.stdout.write(self.style.WARNING(f"  errors: {stats.get('errors', 0)}"))
            self.stdout.write(self.style.SUCCESS(f"  duration_s: {stats.get('duration_s', 0)}"))
            self.stdout.write("")