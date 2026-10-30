# monitoreo/management/commands/validate_ap_clients.py
"""
Valida los OIDs de clientes AP (ubntWlStatTable) contra un equipo real.

Uso:
    python manage.py validate_ap_clients 172.14.3.254 -c comfutech_monitor --snmp-version 1

    python manage.py validate_ap_clients --device-id 3

    python manage.py validate_ap_clients 172.14.3.254 -c comfutech_monitor --snmp-version 1 \
        --output backups/ap-clients.json
"""
import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from inventario.models import Device
from monitoreo.services.snmp_client import snmp_walk, to_int, to_str


# ============================================================
# COLUMNAS DE ubntWlStatTable (airOS 8.x)
# ============================================================
# La tabla completa vive en:
#   1.3.6.1.4.1.41112.1.4.5.1
#
# Cada columna es un subárbol con índice N al final:
#   1.3.6.1.4.1.41112.1.4.5.1.<col>.<N>
#
# Basado en la MIB UBNT-AirMAX y validado empíricamente en airOS 8.7.x.
AP_COLUMNS = {
    "mac":          "1.3.6.1.4.1.41112.1.4.5.1.2",
    "essid":        "1.3.6.1.4.1.41112.1.4.5.1.3",
    "ip":           "1.3.6.1.4.1.41112.1.4.5.1.4",
    "signal":       "1.3.6.1.4.1.41112.1.4.5.1.5",
    "rssi":         "1.3.6.1.4.1.41112.1.4.5.1.6",
    "ccq":          "1.3.6.1.4.1.41112.1.4.5.1.7",
    "noise_floor":  "1.3.6.1.4.1.41112.1.4.5.1.8",
    "tx_rate":      "1.3.6.1.4.1.41112.1.4.5.1.9",
    "rx_rate":      "1.3.6.1.4.1.41112.1.4.5.1.10",
}

# Descripción legible de cada columna
COLUMN_LABELS = {
    "mac":          "MAC del cliente",
    "essid":        "SSID",
    "ip":           "IP del cliente",
    "signal":       "Señal (dBm)",
    "rssi":         "RSSI",
    "ccq":          "CCQ (%)",
    "noise_floor":  "Piso de ruido (dBm)",
    "tx_rate":      "TX Rate (kbps)",
    "rx_rate":      "RX Rate (kbps)",
}


class Command(BaseCommand):
    help = "Valida OIDs de clientes AP (ubntWlStatTable)"

    def add_arguments(self, parser):
        parser.add_argument("ip", nargs="?", type=str,
                            help="IP del equipo a validar")
        parser.add_argument("--device-id", type=int,
                            help="ID de un Device registrado en la BD")
        parser.add_argument("-c", "--community", type=str, default="public",
                            help="Community SNMPv1/v2c")
        parser.add_argument("--snmp-version", type=str, default="2c",
                            choices=["1", "2c", "3"],
                            help="Versión SNMP")
        parser.add_argument("-u", "--user", type=str, default="")
        parser.add_argument("-a", "--auth", type=str, default="")
        parser.add_argument("-p", "--priv", type=str, default="")
        parser.add_argument("--output", type=str, default="",
                            help="Ruta del archivo JSON de salida")

    def handle(self, *args, **options):
        device = self._build_device(options)
        if not device:
            raise CommandError("Debes especificar una IP o --device-id.")

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== Validación de Clientes AP ===\n"
            f"  Equipo:    {device.name} ({device.ip})\n"
            f"  SNMP:      v{device.snmp_version}\n"
        ))

        # Walk de cada columna
        all_entries = self._walk_all_columns(device)

        if not all_entries:
            self.stdout.write(self.style.WARNING(
                "\n⚠ No se encontraron clientes AP.\n"
                "  Posibles causas:\n"
                "   - El equipo NO está en modo Access Point\n"
                "   - No hay clientes conectados\n"
                "   - Los OIDs no son válidos para este firmware\n"
            ))
            return

        self._print_clients_table(all_entries)

        if options["output"]:
            self._save_report(device, all_entries, options["output"])

    # ============================================================
    # CONSTRUCCIÓN DEL DEVICE
    # ============================================================
    def _build_device(self, options):
        """Construye un Device (existente o temporal)."""
        if options["device_id"]:
            try:
                return Device.objects.get(pk=options["device_id"])
            except Device.DoesNotExist:
                raise CommandError(f"No existe Device con id={options['device_id']}")

        if not options["ip"]:
            return None

        return Device(
            name=f"validate-ap-{options['ip']}",
            ip=options["ip"],
            snmp_version=options["snmp_version"],
            snmp_community=options["community"],
            snmp_user=options["user"] or None,
            snmp_auth=options["auth"] or None,
            snmp_priv=options["priv"] or None,
            device_role="access",
            vendor="Ubiquiti",
        )

    # ============================================================
    # WALK DE TODAS LAS COLUMNAS
    # ============================================================
    def _walk_all_columns(self, device):
        """
        Hace walk de cada columna y agrupa por índice.

        Returns:
            list: [{index, mac, essid, ip, signal, rssi, ccq,
                    noise_floor, tx_rate, rx_rate}, ...]
        """
        self.stdout.write("\n  Haciendo walk de columnas...\n")
        raw = {}

        for col_name, base_oid in AP_COLUMNS.items():
            self.stdout.write(f"    {col_name:<14} ", ending="")
            try:
                pairs = snmp_walk(device, base_oid)
                values = {}
                prefix = base_oid + "."
                for oid_str, val in pairs:
                    if not oid_str.startswith(prefix):
                        continue
                    try:
                        idx = int(oid_str[len(prefix):].split(".")[0])
                    except (ValueError, IndexError):
                        continue
                    values[idx] = val
                raw[col_name] = values
                self.stdout.write(self.style.SUCCESS(f"{len(values)} entradas"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"ERROR: {e}"))
                raw[col_name] = {}

        # Unión de todos los índices
        all_indexes = set()
        for values in raw.values():
            all_indexes.update(values.keys())

        if not all_indexes:
            return []

        # Construir entradas
        entries = []
        for idx in sorted(all_indexes):
            entry = {"index": idx}
            entry["mac"] = self._format_mac(raw["mac"].get(idx))
            entry["essid"] = to_str(raw["essid"].get(idx)) or ""
            entry["ip"] = to_str(raw["ip"].get(idx)) or ""
            entry["signal"] = to_int(raw["signal"].get(idx))
            entry["rssi"] = to_int(raw["rssi"].get(idx))
            entry["ccq"] = to_int(raw["ccq"].get(idx))
            entry["noise_floor"] = to_int(raw["noise_floor"].get(idx))
            entry["tx_rate"] = to_int(raw["tx_rate"].get(idx))
            entry["rx_rate"] = to_int(raw["rx_rate"].get(idx))
            entries.append(entry)

        return entries

    # ============================================================
    # HELPERS
    # ============================================================
    def _format_mac(self, raw):
        """Convierte un valor SNMP OctetString a MAC formateada."""
        if raw is None:
            return ""
        s = to_str(raw)
        if not s:
            return ""
        # Si ya viene con ':' o '-', normalizar
        s = s.replace("-", ":").replace(".", "")
        s = "".join(c for c in s if c.isalnum())
        if len(s) == 12:
            return ":".join(s[i:i+2].upper() for i in range(0, 12, 2))
        return s

    # ============================================================
    # PRESENTACIÓN
    # ============================================================
    def _print_clients_table(self, entries):
        """Muestra tabla de clientes encontrados."""
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== {len(entries)} cliente(s) encontrados ===\n"
        ))
        self.stdout.write(
            f"  {'#':<3} {'MAC':<18} {'IP':<16} {'Signal':>7} "
            f"{'CCQ':>5} {'Noise':>7} {'TX':>10} {'RX':>10}\n"
        )
        self.stdout.write("  " + "-" * 88 + "\n")

        for e in entries:
            signal = f"{e['signal']} dBm" if e['signal'] is not None else "—"
            ccq = f"{e['ccq']}%" if e['ccq'] is not None else "—"
            noise = f"{e['noise_floor']} dBm" if e['noise_floor'] is not None else "—"
            tx = f"{e['tx_rate']}" if e['tx_rate'] is not None else "—"
            rx = f"{e['rx_rate']}" if e['rx_rate'] is not None else "—"
            self.stdout.write(
                f"  {e['index']:<3} {e['mac']:<18} {e['ip']:<16} "
                f"{signal:>7} {ccq:>5} {noise:>7} {tx:>10} {rx:>10}\n"
            )

        self.stdout.write("\n")
        self.stdout.write(self.style.SUCCESS(
            "✓ Si ves clientes aquí, los OIDs son correctos.\n"
            "  El poller los descubrirá automáticamente.\n"
        ))

    # ============================================================
    # REPORTE
    # ============================================================
    def _save_report(self, device, entries, output_path):
        """Guarda reporte JSON."""
        report = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "device": {"name": device.name, "ip": device.ip},
            "clients": entries,
        }
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(
            f"\n✓ Reporte guardado en: {output_path}\n"
        ))