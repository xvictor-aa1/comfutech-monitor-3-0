# monitoreo/management/commands/poll_once.py
"""
Ejecuta una pasada de los 4 pollers (traffic, health, icmp, radio).

Uso:
    python manage.py poll_once
    python manage.py poll_once --only traffic
    python manage.py poll_once --only radio
"""
from django.core.management.base import BaseCommand

from monitoreo.services.traffic import poll_traffic
from monitoreo.services.health import poll_health
from monitoreo.services.icmp_tcp import poll_icmp_tcp
from monitoreo.services.radio import poll_radio
from monitoreo.services import influx_writer


class Command(BaseCommand):
    help = "Ejecuta una pasada de los 4 pollers (o el indicado con --only)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            choices=["traffic", "health", "icmp", "radio", "ap_clients"],
            help="Ejecutar solo un poller",
        )

    def handle(self, *args, **options):
        only = options.get("only")

        try:
            if not only or only == "traffic":
                self.stdout.write(self.style.MIGRATE_HEADING("\n=== TRAFFIC ==="))
                self.stdout.write(str(poll_traffic()))

            if not only or only == "health":
                self.stdout.write(self.style.MIGRATE_HEADING("\n=== HEALTH ==="))
                self.stdout.write(str(poll_health()))

            if not only or only == "icmp":
                self.stdout.write(self.style.MIGRATE_HEADING("\n=== ICMP/TCP ==="))
                self.stdout.write(str(poll_icmp_tcp()))

            if not only or only == "radio":
                self.stdout.write(self.style.MIGRATE_HEADING("\n=== RADIO ==="))
                self.stdout.write(str(poll_radio()))
            
            if not only or only == "ap_clients":
                from monitoreo.services.ap_clients import poll_ap_clients
                self.stdout.write(self.style.MIGRATE_HEADING("\n=== AP CLIENTS ==="))
                self.stdout.write(str(poll_ap_clients()))

            self.stdout.write(self.style.SUCCESS("\nListo."))
        finally:
            # Cerrar el cliente de InfluxDB para evitar el TypeError
            # del __del__ cuando el intérprete esté cerrando
            try:
                influx_writer.close()
            except Exception:
                pass