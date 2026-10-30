# monitoreo/management/commands/validate_radio_oids.py
"""
Comando para validar OIDs de radiofrecuencia contra un equipo real.

Uso:
    # Validar por IP (crea un Device temporal en memoria)
    python manage.py validate_radio_oids 192.168.1.50

    # Validar con community específica
    python manage.py validate_radio_oids 192.168.1.50 -c private

    # Validar un Device registrado en la BD (usa su config SNMP)
    python manage.py validate_radio_oids --device-id 3

    # Validar SNMPv3 (SNMP version se pasa con --snmp-version)
    python manage.py validate_radio_oids 192.168.1.50 --snmp-version 3 \
        -u admin -a authpass -p privpass

    # Guardar reporte JSON
    python manage.py validate_radio_oids 192.168.1.50 --output reporte.json

    # Probar un OID específico
    python manage.py validate_radio_oids 192.168.1.50 \
        --oid 1.3.6.1.4.1.41112.1.4.5.1.5.1
"""
import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from inventario.models import Device
from monitoreo.services.snmp_client import (
    snmp_get_multiple,
    snmp_walk,
    to_float,
    to_int,
    to_str,
)


# ============================================================
# CATÁLOGO DE OIDs CANDIDATOS PARA UBIQUITI AIRMAX
# ============================================================
# Cada entrada incluye:
#   key:       nombre de la clave en radio_oids
#   oid:       OID base a probar (sin índice si es escalar, con índice si aplica)
#   tipo:      tipo esperado (float, int, str)
#   desc:      descripción legible
#   rango:     rango esperado (informativo)
#
# Los valores exactos pueden variar según firmware (AirOS 6, 7, 8, etc.).
# Si un OID no responde, prueba con otros índices (ej. .1, .0) o consulta
# la MIB del equipo con `snmpwalk`.
CANDIDATE_OIDS = [
    # --- airMAX AC (AirOS 8) — LiteAP GPS, LiteBeam, PowerBeam ---
    {"key": "radio_freq",      "oid": "1.3.6.1.4.1.41112.1.4.1.1.4.1",  "tipo": "int",   "desc": "Frecuencia de operación (MHz)",       "rango": "2400-6000 MHz"},
    {"key": "radio_txpower",   "oid": "1.3.6.1.4.1.41112.1.4.1.1.6.1",  "tipo": "int",   "desc": "Potencia de TX (dBm)",                 "rango": "0-30 dBm"},
    {"key": "wl_signal",       "oid": "1.3.6.1.4.1.41112.1.4.5.1.5.1",  "tipo": "int",   "desc": "Señal recibida (dBm)",                 "rango": "-100 a -20 dBm"},
    {"key": "wl_noise_floor",  "oid": "1.3.6.1.4.1.41112.1.4.5.1.8.1",  "tipo": "int",   "desc": "Piso de ruido (dBm)",                  "rango": "-100 a -60 dBm"},
    {"key": "wl_ccq",          "oid": "1.3.6.1.4.1.41112.1.4.5.1.7.1",  "tipo": "int",   "desc": "CCQ - Calidad de enlace (%)",          "rango": "0-100 %"},
    {"key": "wl_tx_rate",      "oid": "1.3.6.1.4.1.41112.1.4.5.1.9.1",  "tipo": "int",   "desc": "Tasa de TX (kbps)",                    "rango": "0-1000000 kbps"},
    {"key": "wl_rx_rate",      "oid": "1.3.6.1.4.1.41112.1.4.5.1.10.1", "tipo": "int",   "desc": "Tasa de RX (kbps)",                    "rango": "0-1000000 kbps"},
    {"key": "airmax_quality",  "oid": "1.3.6.1.4.1.41112.1.4.6.1.4.1",  "tipo": "int",   "desc": "Calidad airMAX (%)",                   "rango": "0-100 %"},
    {"key": "airmax_capacity", "oid": "1.3.6.1.4.1.41112.1.4.6.1.5.1",  "tipo": "int",   "desc": "Capacidad airMAX (%)",                 "rango": "0-100 %"},
    {"key": "chan_width",      "oid": "1.3.6.1.4.1.41112.1.4.5.1.14.1", "tipo": "int",   "desc": "Ancho de canal (MHz)",                 "rango": "5, 10, 20, 40, 80 MHz"},

    # --- Alternativas airMAX AC (algunos firmwares) ---
    {"key": "airmax_quality_alt",  "oid": "1.3.6.1.4.1.41112.1.4.6.1.3.1", "tipo": "int", "desc": "airMAX Quality (alternativa)", "rango": "0-100 %"},
    {"key": "airmax_capacity_alt", "oid": "1.3.6.1.4.1.41112.1.4.6.1.6.1", "tipo": "int", "desc": "airMAX Capacity (alternativa)", "rango": "0-100 %"},

    # --- airMAX M (AirOS 5/6) ---
    {"key": "wl_signal_m",      "oid": "1.3.6.1.4.1.41112.1.4.5.1.5.1", "tipo": "int", "desc": "Señal (airMAX M)",  "rango": "-100 a -20 dBm"},
]

# Subárboles a recorrer con SNMP walk para descubrir OIDs alternativos
WALK_TREES = {
    "airMAX":     "1.3.6.1.4.1.41112.1.4",
    "interfaces": "1.3.6.1.2.1.2.2.1",
    "system":     "1.3.6.1.2.1.1",
}


class Command(BaseCommand):
    help = "Valida OIDs de radiofrecuencia contra un equipo (por IP o Device)"

    def add_arguments(self, parser):
        parser.add_argument(
            "ip", nargs="?", type=str,
            help="IP del equipo a validar (si no se usa --device-id)",
        )
        parser.add_argument(
            "--device-id", type=int,
            help="ID de un Device registrado en la BD (usa su config SNMP)",
        )
        parser.add_argument(
            "-c", "--community", type=str, default="public",
            help="Community SNMPv1/v2c (default: public)",
        )
        # ⚠️ NO usar -v/--version: conflictúa con el flag global de Django.
        parser.add_argument(
            "--snmp-version", type=str, default="2c", choices=["1", "2c", "3"],
            help="Versión SNMP: 1, 2c o 3 (default: 2c)",
        )
        parser.add_argument("-u", "--user", type=str, default="",
                            help="Usuario SNMPv3")
        parser.add_argument("-a", "--auth", type=str, default="",
                            help="Auth key SNMPv3")
        parser.add_argument("-p", "--priv", type=str, default="",
                            help="Priv key SNMPv3")
        parser.add_argument(
            "--oid", type=str, action="append",
            help="OID específico a probar (puede repetirse)",
        )
        parser.add_argument(
            "--walk", action="store_true",
            help="Ejecutar SNMP walk sobre los subárboles conocidos",
        )
        parser.add_argument(
            "--output", type=str, default="",
            help="Ruta del archivo JSON de salida con el reporte",
        )

    def handle(self, *args, **options):
        # --- 1. Construir un objeto device-like ---
        device = self._build_device(options)

        if not device:
            raise CommandError(
                "Debes especificar una IP o --device-id."
            )

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== Validación de OIDs de RF ===\n"
            f"  Equipo:    {device.name} ({device.ip})\n"
            f"  SNMP:      v{device.snmp_version}\n"
            f"  Community: {'*' * len(device.snmp_community) if device.snmp_version != '3' else '(v3)'}\n"
        ))

        # --- 2. Probar OIDs individuales ---
        oids_to_test = self._collect_oids(options)
        results = self._probe_oids(device, oids_to_test)

        # --- 3. Mostrar tabla de resultados ---
        self._print_results_table(results)

        # --- 4. SNMP walk (opcional) ---
        walk_results = {}
        if options["walk"]:
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n=== SNMP Walk (subárboles conocidos) ===\n"
            ))
            walk_results = self._walk_trees(device)

        # --- 5. Generar reporte JSON ---
        if options["output"]:
            self._save_report(device, results, walk_results, options["output"])

        # --- 6. Sugerencia final ---
        self._print_suggestion(results)

    # ============================================================
    # CONSTRUCCIÓN DEL DEVICE TEMPORAL
    # ============================================================
    def _build_device(self, options):
        """
        Construye un objeto Device (existente o temporal) con la config
        SNMP adecuada.

        Args:
            options: dict de opciones del comando.

        Returns:
            Device o None si no hay IP ni device-id.
        """
        if options["device_id"]:
            try:
                return Device.objects.get(pk=options["device_id"])
            except Device.DoesNotExist:
                raise CommandError(f"No existe Device con id={options['device_id']}")

        if not options["ip"]:
            return None

        # Device temporal en memoria (no se guarda en BD)
        return Device(
            name=f"validate-{options['ip']}",
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
    # RECOLECCIÓN DE OIDs A PROBAR
    # ============================================================
    def _collect_oids(self, options):
        """
        Devuelve la lista de OIDs a probar (del catálogo + los --oid).
        """
        # OIDs explícitos del usuario
        if options["oid"]:
            return [
                {"key": f"custom_{i}", "oid": oid, "tipo": "int",
                 "desc": "OID personalizado", "rango": "—"}
                for i, oid in enumerate(options["oid"])
            ]

        # Catálogo por defecto
        return list(CANDIDATE_OIDS)

    # ============================================================
    # PROBING DE OIDs
    # ============================================================
    def _probe_oids(self, device, oids_list):
        """
        Prueba cada OID individualmente con GET.

        Args:
            device: instancia de Device.
            oids_list: lista de dicts con clave, oid, tipo, desc.

        Returns:
            list: lista de dicts con {key, oid, ok, value, raw, error, ms}.
        """
        results = []
        for item in oids_list:
            t0 = time.time()
            try:
                values = snmp_get_multiple(device, [item["oid"]])
                raw = values[0] if values else None
                ms = int((time.time() - t0) * 1000)

                if raw is None:
                    results.append({
                        **item,
                        "ok": False,
                        "value": None,
                        "raw": None,
                        "error": "sin respuesta",
                        "ms": ms,
                    })
                    continue

                # Convertir según tipo
                if item["tipo"] == "int":
                    parsed = to_int(raw)
                elif item["tipo"] == "float":
                    parsed = to_float(raw)
                else:
                    parsed = to_str(raw)

                results.append({
                    **item,
                    "ok": parsed is not None,
                    "value": parsed,
                    "raw": to_str(raw),
                    "error": None if parsed is not None else "no convertible",
                    "ms": ms,
                })
            except Exception as e:
                results.append({
                    **item,
                    "ok": False,
                    "value": None,
                    "raw": None,
                    "error": str(e),
                    "ms": int((time.time() - t0) * 1000),
                })
        return results

    # ============================================================
    # SNMP WALK (opcional)
    # ============================================================
    def _walk_trees(self, device):
        """
        Ejecuta SNMP walk sobre los subárboles conocidos.

        Returns:
            dict: {tree_name: [(oid_str, value_str), ...]}
        """
        results = {}
        for name, base_oid in WALK_TREES.items():
            self.stdout.write(f"  Walking {name} ({base_oid})... ", ending="")
            try:
                pairs = snmp_walk(device, base_oid)
                self.stdout.write(self.style.SUCCESS(f"{len(pairs)} OIDs"))
                results[name] = [
                    (oid, to_str(val)) for oid, val in pairs
                ]
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"ERROR: {e}"))
                results[name] = []
        return results

    # ============================================================
    # PRESENTACIÓN DE RESULTADOS
    # ============================================================
    def _print_results_table(self, results):
        """Imprime una tabla con el resultado de cada OID probado."""
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== Resultados por OID ===\n"
        ))

        for r in results:
            if r["ok"]:
                icon = self.style.SUCCESS("✓")
                value = self.style.SUCCESS(f"{r['value']}")
                line = f"  {icon} {r['key']:<22} {r['desc']:<35} = {value}"
                if r["rango"] and r["rango"] != "—":
                    line += f"  (rango esperado: {r['rango']})"
            else:
                icon = self.style.ERROR("✗")
                line = f"  {icon} {r['key']:<22} {r['desc']:<35} {r['error']}"

            self.stdout.write(line)
            if r["raw"] is not None and r["raw"] != str(r["value"]):
                self.stdout.write(
                    f"      raw: {r['raw'][:80]}  ({r['ms']} ms)"
                )

    # ============================================================
    # GUARDADO DEL REPORTE
    # ============================================================
    def _save_report(self, device, results, walk_results, output_path):
        """
        Guarda un reporte JSON con los resultados.

        Args:
            device: instancia de Device.
            results: lista de dicts de resultados.
            walk_results: dict con resultados del walk.
            output_path: ruta del archivo.
        """
        report = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "device": {
                "name": device.name,
                "ip": device.ip,
                "snmp_version": device.snmp_version,
                "vendor": device.vendor,
            },
            "results": results,
            "walk": {
                name: [{"oid": oid, "value": val} for oid, val in pairs]
                for name, pairs in walk_results.items()
            },
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

    # ============================================================
    # SUGERENCIA FINAL
    # ============================================================
    def _print_suggestion(self, results):
        """
        Genera una sugerencia de dict `radio_oids` con los OIDs que
        respondieron correctamente.
        """
        ok_items = [
            r for r in results
            if r["ok"] and not r["key"].endswith("_alt")
        ]
        if not ok_items:
            self.stdout.write(self.style.WARNING(
                "\n⚠ Ningún OID respondió. Verifica:\n"
                "   - La IP y la community\n"
                "   - Que el equipo tenga SNMP habilitado\n"
                "   - Que el firewall no bloquee el puerto 161/UDP\n"
                "   - Que el firmware sea compatible\n"
            ))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== Sugerencia de radio_oids ===\n"
            "Copia este JSON en el campo 'OIDs de radiofrecuencia' "
            "del modelo en el CRUD:\n"
        ))

        suggestion = {}
        for r in ok_items:
            # Normalizar la clave (quitar sufijos _alt, _m)
            key = r["key"]
            for suffix in ("_alt", "_m"):
                if key.endswith(suffix):
                    key = key[: -len(suffix)]
                    break
            suggestion[key] = r["oid"]

        formatted = json.dumps(suggestion, indent=2, ensure_ascii=False)
        self.stdout.write(self.style.SUCCESS(formatted + "\n"))

        # Estadísticas
        n_ok = sum(1 for r in results if r["ok"])
        n_total = len(results)
        self.stdout.write(
            f"  {n_ok}/{n_total} OIDs válidos. "
            f"Los que no respondieron pueden no existir en este firmware.\n"
        )