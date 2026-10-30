# monitoreo/management/commands/poll_radio.py
"""
Comando de gestión para ejecutar una sola pasada del poller de
radiofrecuencia.

Uso:
    python manage.py poll_radio

Útil para validar manualmente la recolección de métricas de radio
(frecuencia, capacidad RX/TX, señal, ruido, CCQ, etc.) antes de
integrarlo en el scheduler.
"""
from django.core.management.base import BaseCommand
from monitoreo.services.radio import poll_radio
from monitoreo.services import influx_writer


class Command(BaseCommand):
    """
    Ejecuta `poll_radio()` una vez y muestra las estadísticas.

    Cierra explícitamente el cliente de InfluxDB al final para evitar
    el error `TypeError: 'NoneType' object is not callable` que ocurre
    cuando el intérprete de Python destruye los módulos durante el
    cierre (`__del__` del cliente de influxdb_client).
    """
    help = "Ejecuta una sola pasada del poller de radiofrecuencia"

    def handle(self, *args, **options):
        """
        Punto de entrada del comando.

        - Imprime un encabezado.
        - Ejecuta `poll_radio()` capturando cualquier excepción para
          que el comando no termine con un traceback crudo.
        - En el bloque `finally`, cierra el cliente de InfluxDB.
        - Muestra las métricas de rendimiento del ciclo.
        """
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== POLL RADIO (Radiofrecuencia) ===\n"
        ))
        stats = None
        try:
            stats = poll_radio()
        except Exception as e:
            # No relanzamos: mostramos el error de forma legible.
            self.stdout.write(self.style.ERROR(f"Error en poll_radio: {e}"))
        finally:
            # Cierre defensivo del cliente InfluxDB.
            try:
                influx_writer.close()
            except Exception:
                pass

        if stats:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(
                f"  devices: {stats.get('devices', 0)}"
            ))
            self.stdout.write(self.style.WARNING(
                f"  skipped: {stats.get('skipped', 0)}"
            ))
            self.stdout.write(self.style.WARNING(
                f"  errors: {stats.get('errors', 0)}"
            ))
            self.stdout.write(self.style.SUCCESS(
                f"  duration_s: {stats.get('duration_s', 0)}"
            ))
            self.stdout.write("")