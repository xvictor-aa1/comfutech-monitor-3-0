# monitoreo/management/commands/poll_ap_clients.py
"""Ejecuta una sola pasada del poller de clientes AP."""
from django.core.management.base import BaseCommand
from monitoreo.services.ap_clients import poll_ap_clients
from monitoreo.services import influx_writer


class Command(BaseCommand):
    help = "Ejecuta una sola pasada del poller de clientes AP"

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== POLL AP CLIENTS ===\n"
        ))
        stats = None
        try:
            stats = poll_ap_clients()
        finally:
            try:
                influx_writer.close()
            except Exception:
                pass
        if stats:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"  devices: {stats.get('devices', 0)}"))
            self.stdout.write(self.style.SUCCESS(f"  clients: {stats.get('clients', 0)}"))
            self.stdout.write(self.style.WARNING(f"  skipped: {stats.get('skipped', 0)}"))
            self.stdout.write(self.style.WARNING(f"  errors: {stats.get('errors', 0)}"))
            self.stdout.write(self.style.SUCCESS(f"  duration_s: {stats.get('duration_s', 0)}"))
            self.stdout.write("")