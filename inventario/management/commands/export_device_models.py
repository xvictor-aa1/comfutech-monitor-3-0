# inventario/management/commands/export_device_models.py
"""
Exporta los modelos de equipo a JSON.

Uso:
    python manage.py export_device_models
    python manage.py export_device_models --output backups/models.json

El JSON resultante puede reimportarse fácilmente con
`load_device_models --from-json <archivo>` (comando complementario
pendiente) o editarse a mano.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from inventario.models import DeviceModel


class Command(BaseCommand):
    help = "Exporta los modelos de equipos a JSON"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=str,
            default="backups/device_models.json",
            help="Ruta del archivo JSON de salida (default: backups/device_models.json)",
        )
        parser.add_argument(
            "--pretty",
            action="store_true",
            help="Formatea el JSON con indentación",
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = []
        for m in DeviceModel.objects.all().order_by("vendor", "name"):
            data.append({
                "vendor": m.vendor,
                "name": m.name,
                "oids": m.oids or {},
                "description": m.description or "",
                "is_wireless_link": m.is_wireless_link,
                "active": m.active,
            })

        indent = 2 if options["pretty"] else None
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)

        self.stdout.write(self.style.SUCCESS(
            f"✓ Exportados {len(data)} modelo(s) a {output_path}"
        ))