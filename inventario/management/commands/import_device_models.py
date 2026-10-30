# inventario/management/commands/import_device_models.py
"""
Importa modelos de equipo desde un JSON (idempotente).

Uso:
    python manage.py import_device_models --input backups/device_models.json

Los modelos existentes (mismo vendor + name) se actualizan.
Los nuevos se crean.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from inventario.models import DeviceModel


class Command(BaseCommand):
    help = "Importa modelos de equipo desde un JSON"

    def add_arguments(self, parser):
        parser.add_argument(
            "--input", type=str, required=True,
            help="Ruta del archivo JSON de entrada",
        )

    def handle(self, *args, **options):
        input_path = Path(options["input"])
        if not input_path.exists():
            raise CommandError(f"No existe el archivo: {input_path}")

        with input_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise CommandError("El JSON debe ser una lista de modelos.")

        created = updated = 0
        for item in data:
            vendor = (item.get("vendor") or "").strip()
            name = (item.get("name") or "").strip()
            if not vendor or not name:
                self.stdout.write(self.style.WARNING(
                    f"  ⚠ Saltando entrada sin vendor/name: {item}"
                ))
                continue

            obj, was_created = DeviceModel.objects.update_or_create(
                vendor=vendor,
                name=name,
                defaults={
                    "oids": item.get("oids") or {},
                    "description": item.get("description") or "",
                    "is_wireless_link": bool(item.get("is_wireless_link")),
                    "active": bool(item.get("active", True)),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"✓ Importación completa: {created} creado(s), "
            f"{updated} actualizado(s)."
        ))