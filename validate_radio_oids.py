# validate_radio_oids.py
"""
Script standalone para validar OIDs SNMP de radiofrecuencia
contra un equipo Ubiquiti airMAX (LiteAP GPS, LiteBeam, PowerBeam, etc.).

NO requiere Django. Solo `pysnmp`.

Uso:
    python scripts/validate_radio_oids.py 192.168.1.50
    python scripts/validate_radio_oids.py 192.168.1.50 -c private
    python scripts/validate_radio_oids.py 192.168.1.50 --walk
    python scripts/validate_radio_oids.py 192.168.1.50 --json reporte.json

Requiere:
    pip install pysnmp
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

try:
    from pysnmp.hlapi.v3arch.asyncio import (
        SnmpEngine,
        CommunityData,
        UsmUserData,
        UdpTransportTarget,
        ContextData,
        ObjectType,
        ObjectIdentity,
        get_cmd,
        bulk_cmd,
    )
except ImportError:
    print("ERROR: pysnmp no está instalado. Ejecuta: pip install pysnmp")
    sys.exit(1)


# ============================================================
# CATÁLOGO DE OIDs (idéntico al comando de management)
# ============================================================
CANDIDATE_OIDS = [
    {"key": "radio_freq",      "oid": "1.3.6.1.4.1.41112.1.4.1.1.4.1",  "desc": "Frecuencia RF (MHz)",      "rango": "2400-6000"},
    {"key": "radio_txpower",   "oid": "1.3.6.1.4.1.41112.1.4.1.1.6.1",  "desc": "TX Power (dBm)",            "rango": "0-30"},
    {"key": "wl_signal",       "oid": "1.3.6.1.4.1.41112.1.4.5.1.5.1",  "desc": "Signal (dBm)",              "rango": "-100 a -20"},
    {"key": "wl_noise_floor",  "oid": "1.3.6.1.4.1.41112.1.4.5.1.8.1",  "desc": "Noise Floor (dBm)",         "rango": "-100 a -60"},
    {"key": "wl_ccq",          "oid": "1.3.6.1.4.1.41112.1.4.5.1.7.1",  "desc": "CCQ (%)",                   "rango": "0-100"},
    {"key": "wl_tx_rate",      "oid": "1.3.6.1.4.1.41112.1.4.5.1.9.1",  "desc": "TX Rate (kbps)",            "rango": "0-1000000"},
    {"key": "wl_rx_rate",      "oid": "1.3.6.1.4.1.41112.1.4.5.1.10.1", "desc": "RX Rate (kbps)",            "rango": "0-1000000"},
    {"key": "airmax_quality",  "oid": "1.3.6.1.4.1.41112.1.4.6.1.4.1",  "desc": "airMAX Quality (%)",        "rango": "0-100"},
    {"key": "airmax_capacity", "oid": "1.3.6.1.4.1.41112.1.4.6.1.5.1",  "desc": "airMAX Capacity (%)",       "rango": "0-100"},
    {"key": "chan_width",      "oid": "1.3.6.1.4.1.41112.1.4.5.1.14.1", "desc": "Ancho de canal (MHz)",      "rango": "5,10,20,40,80"},
    {"key": "airmax_quality_alt",  "oid": "1.3.6.1.4.1.41112.1.4.6.1.3.1", "desc": "airMAX Quality (alt)",  "rango": "0-100"},
    {"key": "airmax_capacity_alt", "oid": "1.3.6.1.4.1.41112.1.4.6.1.6.1", "desc": "airMAX Capacity (alt)", "rango": "0-100"},
]

WALK_TREES = {
    "airMAX":     "1.3.6.1.4.1.41112.1.4",
    "system":     "1.3.6.1.2.1.1",
    "interfaces": "1.3.6.1.2.1.2.2.1",
}

SNMP_TIMEOUT = 3
SNMP_RETRIES = 1
MAX_REPETITIONS = 25
MAX_RESULTS = 2048


# ============================================================
# HELPERS SNMP
# ============================================================
def _build_auth(args):
    """Construye el objeto de autenticación SNMP."""
    if args.version == "3":
        if not args.user:
            print("ERROR: SNMPv3 requiere --user")
            sys.exit(1)
        return UsmUserData(
            args.user,
            authKey=args.auth or None,
            privKey=args.priv or None,
        )
    mp_model = 0 if args.version == "1" else 1
    return CommunityData(args.community, mpModel=mp_model)


async def _snmp_get(auth, ip, oids):
    """Ejecuta un GET múltiple y devuelve valores."""
    try:
        transport = await UdpTransportTarget.create(
            (ip, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES
        )
        err_ind, err_stat, _, var_binds = await get_cmd(
            SnmpEngine(), auth, transport, ContextData(),
            *[ObjectType(ObjectIdentity(o)) for o in oids],
        )
        if err_ind or err_stat:
            return [None] * len(oids)
        return [vb[1] for vb in var_binds]
    except Exception:
        return [None] * len(oids)


async def _snmp_walk(auth, ip, base_oid):
    """Ejecuta un WALK y devuelve [(oid, valor)]."""
    results = []
    try:
        transport = await UdpTransportTarget.create(
            (ip, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES
        )
        engine = SnmpEngine()
        context = ContextData()
        current = base_oid
        prefix = base_oid + "."

        while True:
            err_ind, err_stat, _, var_binds = await bulk_cmd(
                engine, auth, transport, context,
                0, MAX_REPETITIONS,
                ObjectType(ObjectIdentity(current)),
            )
            if err_ind or err_stat or not var_binds:
                break

            end = False
            for vb in var_binds:
                oid_str = str(vb[0])
                if not oid_str.startswith(prefix):
                    end = True
                    break
                results.append((oid_str, str(vb[1])))
                current = oid_str
                if len(results) >= MAX_RESULTS:
                    end = True
                    break
            if end:
                break
    except Exception as e:
        print(f"  Error en walk: {e}")
    return results


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Valida OIDs SNMP de radiofrecuencia en equipos Ubiquiti airMAX"
    )
    parser.add_argument("ip", help="IP del equipo")
    parser.add_argument("-c", "--community", default="public",
                        help="Community SNMPv1/v2c (default: public)")
    parser.add_argument("-v", "--version", default="2c", choices=["1", "2c", "3"],
                        help="Versión SNMP (default: 2c)")
    parser.add_argument("-u", "--user", default="", help="Usuario SNMPv3")
    parser.add_argument("-a", "--auth", default="", help="Auth key SNMPv3")
    parser.add_argument("-p", "--priv", default="", help="Priv key SNMPv3")
    parser.add_argument("--oid", action="append",
                        help="OID específico a probar (repetible)")
    parser.add_argument("--walk", action="store_true",
                        help="Ejecutar SNMP walk sobre subárboles conocidos")
    parser.add_argument("--json", dest="json_out", default="",
                        help="Guardar reporte JSON")
    args = parser.parse_args()

    print()
    print("=" * 70)
    print(f"  Validación de OIDs de radiofrecuencia")
    print(f"  Equipo:    {args.ip}")
    print(f"  SNMP:      v{args.version}")
    print(f"  Community: {'*' * len(args.community) if args.version != '3' else '(v3)'}")
    print("=" * 70)
    print()

    auth = _build_auth(args)

    # --- Construir lista de OIDs a probar ---
    oids_to_test = (
        [{"key": f"custom_{i}", "oid": o, "desc": "OID personalizado", "rango": "—"}
         for i, o in enumerate(args.oid)]
        if args.oid else CANDIDATE_OIDS
    )

    # --- Probar cada OID ---
    print("=== Resultados por OID ===\n")
    results = []
    for item in oids_to_test:
        t0 = time.time()
        try:
            values = asyncio.run(_snmp_get(auth, args.ip, [item["oid"]]))
            raw = values[0] if values else None
            ms = int((time.time() - t0) * 1000)

            if raw is None or str(raw) in ("No Such Object currently exists at this OID",
                                           "No Such Instance currently exists at this OID"):
                results.append({**item, "ok": False, "value": None,
                                "raw": None, "error": "sin respuesta", "ms": ms})
                print(f"  ✗ {item['key']:<22} {item['desc']:<28} sin respuesta ({ms} ms)")
                continue

            try:
                parsed = int(raw)
                ok = True
            except (ValueError, TypeError):
                parsed = None
                ok = False

            results.append({**item, "ok": ok, "value": parsed,
                            "raw": str(raw), "error": None if ok else "no convertible",
                            "ms": ms})
            if ok:
                print(f"  ✓ {item['key']:<22} {item['desc']:<28} = {parsed}  "
                      f"(rango: {item['rango']}, {ms} ms)")
            else:
                print(f"  ✗ {item['key']:<22} {item['desc']:<28} "
                      f"valor no numérico: {raw}")
        except Exception as e:
            print(f"  ✗ {item['key']:<22} {item['desc']:<28} ERROR: {e}")
            results.append({**item, "ok": False, "value": None, "raw": None,
                            "error": str(e), "ms": 0})

    # --- SNMP walk opcional ---
    walk_results = {}
    if args.walk:
        print("\n=== SNMP Walk (subárboles conocidos) ===\n")
        for name, base_oid in WALK_TREES.items():
            print(f"  Walking {name} ({base_oid})... ", end="", flush=True)
            pairs = asyncio.run(_snmp_walk(auth, args.ip, base_oid))
            print(f"{len(pairs)} OIDs")
            walk_results[name] = [
                {"oid": oid, "value": val} for oid, val in pairs
            ]
            # Mostrar primeros 10
            for oid, val in pairs[:10]:
                print(f"    {oid} = {val}")
            if len(pairs) > 10:
                print(f"    ... y {len(pairs) - 10} más")

    # --- Sugerencia ---
    print("\n=== Sugerencia de radio_oids ===\n")
    ok_items = [r for r in results if r["ok"] and not r["key"].endswith("_alt")]
    if not ok_items:
        print("  ⚠ Ningún OID respondió. Verifica:")
        print("    - IP, community y conectividad (ping)")
        print("    - SNMP habilitado en el equipo")
        print("    - Puerto 161/UDP no bloqueado")
        sys.exit(1)

    suggestion = {}
    for r in ok_items:
        key = r["key"]
        for suffix in ("_alt", "_m"):
            if key.endswith(suffix):
                key = key[: -len(suffix)]
                break
        suggestion[key] = r["oid"]

    print("  Copia este JSON en el campo 'OIDs de radiofrecuencia'")
    print("  del modelo en el CRUD:\n")
    print(json.dumps(suggestion, indent=4, ensure_ascii=False))
    print()
    print(f"  {len(ok_items)}/{len(results)} OIDs válidos.\n")

    # --- Guardar JSON ---
    if args.json_out:
        report = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "device": {"ip": args.ip, "snmp_version": args.version},
            "results": results,
            "walk": walk_results,
        }
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        print(f"✓ Reporte guardado en: {args.json_out}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelado por el usuario.")
        sys.exit(130)