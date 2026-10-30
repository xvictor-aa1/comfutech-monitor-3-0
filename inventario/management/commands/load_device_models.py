# inventario/management/commands/load_device_models.py
from django.core.management.base import BaseCommand
from inventario.models import DeviceModel

MODELS = [
    # MikroTik
    {
        "vendor": "MikroTik", "name": "RB4011iGS+",
        "oids": {
            "cpu_pct": "1.3.6.1.2.1.25.3.3.1.2.1",
            "mem_used": "1.3.6.1.2.1.25.2.3.1.6.65536",
            "mem_size": "1.3.6.1.2.1.25.2.3.1.5.65536",
            "temp_c": "1.3.6.1.4.1.14988.1.1.3.100.1.3.14",
        },
    },
    {
        "vendor": "MikroTik", "name": "hEX S",
        "oids": {
            "cpu_pct": "1.3.6.1.2.1.25.3.3.1.2.1",
            "mem_used": "1.3.6.1.2.1.25.2.3.1.6.65536",
            "mem_size": "1.3.6.1.2.1.25.2.3.1.5.65536",
            "temp_c": "1.3.6.1.4.1.14988.1.1.3.10.0",
        },
    },
    # Ubiquiti
    {
        "vendor": "Ubiquiti", "name": "AirMax LiteBeam M5",
        "oids": {
            "cpu_pct": "1.3.6.1.4.1.41112.1.4.8.3.0",
            "temp_c": "1.3.6.1.4.1.41112.1.4.8.4.0",
        },
    },
    {
        "vendor": "Ubiquiti", "name": "AirMax NanoStation M5",
        "oids": {
            "cpu_pct": "1.3.6.1.4.1.41112.1.4.8.3.0",
            "temp_c": "1.3.6.1.4.1.41112.1.4.8.4.0",
        },
    },
    # Cambium
    {
        "vendor": "Cambium", "name": "ePMP 1000",
        "oids": {
            "cpu_pct": "1.3.6.1.4.1.17713.21.2.1.64.0",
        },
    },
    # Huawei
    {
        "vendor": "Huawei", "name": "AR611",
        "oids": {
            "cpu_pct": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5.0",
            "mem_pct": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7.0",
        },
    },
]


class Command(BaseCommand):
    help = "Carga los modelos de equipos y sus OIDs"

    def handle(self, *args, **options):
        for data in MODELS:
            obj, created = DeviceModel.objects.update_or_create(
                vendor=data["vendor"], name=data["name"],
                defaults={"oids": data["oids"]},
            )
            status = "creado" if created else "actualizado"
            self.stdout.write(self.style.SUCCESS(f"✓ {obj} — {status}"))
