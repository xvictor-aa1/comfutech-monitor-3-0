# monitoreo/management/commands/run_monitor.py
"""
Lanza el monitor en background.

Uso:
    python manage.py run_monitor                    # INFO
    python manage.py run_monitor --silent           # Solo WARNING+
    python manage.py run_monitor --skip-discovery   # Sin discovery inicial
"""
import logging
import signal
import time

from django.core.management.base import BaseCommand

from monitoreo.scheduler import (
    start_scheduler, stop_scheduler, set_silent_mode,
)
from monitoreo.services import influx_writer

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Lanza el monitor de red en background"

    def add_arguments(self, parser):
        parser.add_argument(
            "--silent", action="store_true",
            help="Modo silencioso: solo WARNING+",
        )
        parser.add_argument(
            "--skip-discovery", action="store_true",
            help="No ejecutar Discovery automático al arrancar",
        )

    def handle(self, *args, **options):
        silent = options["silent"]

        if silent:
            set_silent_mode(True)

        self.stdout.write(self.style.SUCCESS(
            "Iniciando monitor de red..."
            + (" [MODO SILENCIOSO]" if silent else "")
        ))

        # ============================================================
        # AUTO-DISCOVERY INICIAL
        # ============================================================
        if not options["skip_discovery"]:
            if not silent:
                self.stdout.write(self.style.MIGRATE_HEADING(
                    "\n=== Discovery inicial ==="
                ))
            self._run_initial_discovery()
        else:
            self.stdout.write(self.style.WARNING(
                "Discovery inicial saltado (--skip-discovery)."
            ))

        # ============================================================
        # SCHEDULER
        # ============================================================
        if not silent:
            self.stdout.write(self.style.MIGRATE_HEADING("\n=== Scheduler ==="))

        scheduler = start_scheduler()
        if scheduler is None:
            self.stdout.write(self.style.WARNING(
                "El monitor está deshabilitado (monitor_enabled=False)."
            ))
            try:
                influx_writer.close()
            except Exception:
                pass
            return

        self.stdout.write(self.style.SUCCESS(
            "Monitor iniciado. Presiona Ctrl+C para detener.\n"
        ))

        # ============================================================
        # LOOP INFINITO
        # ============================================================
        stopped = False

        def _signal_handler(sig, frame):
            nonlocal stopped
            if stopped:
                return
            stopped = True
            self.stdout.write(self.style.WARNING("\nDeteniendo monitor..."))

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        try:
            while not stopped:
                time.sleep(1)
        finally:
            stop_scheduler()
            try:
                influx_writer.close()
            except Exception:
                pass
            # Segundo cierre defensivo
            influx_writer.close()
            self.stdout.write(self.style.SUCCESS(
                "Monitor detenido correctamente."
            ))

    # ============================================================
    # DISCOVERY INICIAL
    # ============================================================
    def _run_initial_discovery(self):
        try:
            import time as _time
            from django.utils import timezone
            from inventario.models import Device
            from monitoreo.services.discovery import discover_interfaces
            from monitoreo.models import DiscoveryJob

            devices = Device.objects.filter(active=True)
            total = devices.count()

            if total == 0:
                self.stdout.write(self.style.WARNING(
                    "No hay equipos activos. Saltando Discovery."
                ))
                return

            self.stdout.write(f"Ejecutando Discovery en {total} equipo(s)...")
            ok = 0
            failed = 0

            for device in devices:
                job = DiscoveryJob.objects.create(
                    device=device, status="running",
                )
                start = _time.time()
                result = discover_interfaces(device)
                elapsed_ms = int((_time.time() - start) * 1000)

                job.finished_at = timezone.now()
                job.duration_ms = elapsed_ms
                job.interfaces_found = result["interfaces_found"]
                job.interfaces_up = result["interfaces_up"]
                job.interfaces_created = result["created"]
                job.interfaces_updated = result["updated"]
                job.interfaces_deleted = result["deleted"]
                job.status = "success" if result["success"] else "failed"
                if not result["success"]:
                    job.error_message = result.get("error") or "Error"
                job.save()

                if result["success"]:
                    ok += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✅ {device.name}: "
                        f"{result['interfaces_found']} interfaces "
                        f"(+{result['created']} nuevas, "
                        f"{result['updated']} act., "
                        f"-{result['deleted']} elim.) "
                        f"[{elapsed_ms}ms]"
                    ))
                else:
                    failed += 1
                    self.stdout.write(self.style.ERROR(
                        f"  ❌ {device.name}: {result.get('error')}"
                    ))

            self.stdout.write(self.style.SUCCESS(
                f"\nDiscovery inicial: {ok}/{total} equipos OK."
            ))
            if failed:
                self.stdout.write(self.style.WARNING(
                    f"{failed} equipo(s) fallaron."
                ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f"Error en Discovery inicial: {e}"
            ))
            log.exception("Error en Discovery inicial")