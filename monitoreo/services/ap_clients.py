# monitoreo/services/ap_clients.py
"""
Servicio de clientes AP: discovery + polling de métricas.

Solo procesa equipos con device_model.is_wireless_link=True.
Los clientes se guardan en Device.ap_interfaces (config estática).
Las métricas en vivo se escriben a InfluxDB (measurement "ap_clients").

El walk SNMP se realiza sobre el subárbol completo de ubntWlStatTable
(1 sola consulta por AP), y luego se agrupan los valores por columna
e índice en Python.

Formato de ap_interfaces (JSONField en Device):
    [
      {
        "if_index": 1,
        "mac": "AA:BB:CC:DD:EE:01",
        "ip": "172.14.3.100",
        "essid": "comfutech-gps",
        "hostname": "",              # editable manualmente
        "first_seen": "2026-10-22T23:30:00+00:00",
        "last_seen":  "2026-10-23T10:00:00+00:00"
      },
      ...
    ]
"""
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from django.utils import timezone as dj_tz

from inventario.models import Device
from . import alerts, influx_writer
from .snmp_client import snmp_walk, to_int, to_str

log = logging.getLogger(__name__)


# ============================================================
# OIDs DE ubntWlStatTable
# ============================================================
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

# Subárbol completo de la tabla (contiene todas las columnas anteriores).
TABLE_BASE = "1.3.6.1.4.1.41112.1.4.5.1"


def _utcnow() -> datetime:
    """Hora actual en UTC (aware)."""
    return dj_tz.now()


def _format_mac(raw) -> str:
    """
    Convierte un valor SNMP OctetString a MAC "AA:BB:CC:DD:EE:FF".

    Args:
        raw: valor SNMP crudo (bytes, str, etc.).

    Returns:
        str: MAC formateada o "" si no se puede.
    """
    if raw is None:
        return ""
    s = to_str(raw)
    if not s:
        return ""
    s = s.replace("-", ":").replace(".", "")
    s = "".join(c for c in s if c.isalnum())
    if len(s) == 12:
        return ":".join(s[i:i+2].upper() for i in range(0, 12, 2))
    return s


# ============================================================
# WALK DE LA TABLA COMPLETA
# ============================================================
def _walk_all_columns(device) -> Dict[str, Dict[int, object]]:
    """
    Hace un único walk del subárbol ubntWlStatTable y agrupa los
    valores por columna e índice.

    Args:
        device: instancia de Device.

    Returns:
        dict: {col_name: {index: value}}.
    """
    # Mapa inverso: OID completo de columna → nombre corto.
    column_map = {oid: name for name, oid in AP_COLUMNS.items()}

    raw: Dict[str, Dict[int, object]] = {name: {} for name in AP_COLUMNS}

    try:
        pairs = snmp_walk(device, TABLE_BASE)
    except Exception as e:
        log.debug("[%s] Walk ubntWlStatTable falló: %s", device.name, e)
        return raw

    prefix = TABLE_BASE + "."
    for oid_str, val in pairs:
        if not oid_str.startswith(prefix):
            continue
        suffix = oid_str[len(prefix):]
        parts = suffix.split(".")
        if len(parts) < 2:
            continue
        try:
            col_num = int(parts[0])
            idx = int(parts[1])
        except (ValueError, IndexError):
            continue

        # El OID de la columna es TABLE_BASE + "." + col_num
        col_oid = f"{TABLE_BASE}.{col_num}"
        col_name = column_map.get(col_oid)
        if col_name:
            raw[col_name][idx] = val

    return raw


def _parse_clients(raw: Dict[str, Dict[int, object]]) -> List[dict]:
    """
    Convierte los valores crudos del walk en una lista de clientes.

    Args:
        raw: salida de _walk_all_columns.

    Returns:
        list: [{index, mac, essid, ip, signal, rssi, ccq,
                noise_floor, tx_rate, rx_rate}, ...]
    """
    all_indexes = set()
    for values in raw.values():
        all_indexes.update(values.keys())

    clients = []
    for idx in sorted(all_indexes):
        mac = _format_mac(raw["mac"].get(idx))
        if not mac:
            continue

        clients.append({
            "index": idx,
            "mac": mac,
            "essid": to_str(raw["essid"].get(idx)) or "",
            "ip": to_str(raw["ip"].get(idx)) or "",
            "signal": to_int(raw["signal"].get(idx)),
            "rssi": to_int(raw["rssi"].get(idx)),
            "ccq": to_int(raw["ccq"].get(idx)),
            "noise_floor": to_int(raw["noise_floor"].get(idx)),
            "tx_rate": to_int(raw["tx_rate"].get(idx)),
            "rx_rate": to_int(raw["rx_rate"].get(idx)),
        })
    return clients


# ============================================================
# DISCOVERY (pobla/actualiza ap_interfaces)
# ============================================================
def discover_ap_clients(device) -> dict:
    """
    Descubre los clientes conectados al AP y actualiza ap_interfaces.

    Reglas:
      - Si el cliente ya existe (por MAC), actualiza last_seen
        preservando first_seen y hostname.
      - Si es nuevo, lo añade con first_seen=last_seen=now.
      - Si estaba en ap_interfaces pero no apareció en el walk,
        se conserva (queda offline). Su last_seen NO se actualiza.

    Args:
        device: instancia de Device.

    Returns:
        dict: {success, clients_found, added, updated, total, error}.
    """
    result = {
        "success": False,
        "clients_found": 0,
        "added": 0,
        "updated": 0,
        "total": 0,
        "error": None,
    }

    if not device.device_model or not device.device_model.is_wireless_link:
        result["error"] = "El modelo no es wireless."
        return result

    try:
        raw = _walk_all_columns(device)
        clients = _parse_clients(raw)
        result["clients_found"] = len(clients)

        # Mapa de clientes existentes por MAC.
        existing = {
            c.get("mac", "").upper(): c
            for c in (device.ap_interfaces or [])
        }
        now_iso = _utcnow().isoformat()

        new_list = []
        for c in clients:
            mac = c["mac"].upper()
            if mac in existing:
                prev = existing[mac]
                # Preservar first_seen y hostname; actualizar el resto.
                prev["ip"] = c["ip"] or prev.get("ip", "")
                prev["essid"] = c["essid"] or prev.get("essid", "")
                prev["if_index"] = c["index"]
                prev["last_seen"] = now_iso
                new_list.append(prev)
                result["updated"] += 1
            else:
                new_list.append({
                    "if_index": c["index"],
                    "mac": mac,
                    "ip": c["ip"],
                    "essid": c["essid"],
                    "hostname": "",
                    "first_seen": now_iso,
                    "last_seen": now_iso,
                })
                result["added"] += 1

        # Añadir los que estaban pero no aparecieron (offline).
        seen_macs = {c["mac"].upper() for c in clients}
        for mac, prev in existing.items():
            if mac not in seen_macs:
                new_list.append(prev)

        device.ap_interfaces = new_list
        device.save(update_fields=["ap_interfaces", "updated_at"])
        result["total"] = len(new_list)
        result["success"] = True

        log.info(
            "[%s] Discovery AP: %d clientes (%d nuevos, %d actualizados, "
            "%d totales incluyendo offline)",
            device.name, result["clients_found"], result["added"],
            result["updated"], result["total"],
        )
    except Exception as e:
        log.exception("[%s] Error en discovery AP: %s", device.name, e)
        result["error"] = str(e)

    return result


# ============================================================
# POLLER (lee métricas y escribe a InfluxDB)
# ============================================================
def poll_ap_clients() -> dict:
    """
    Ciclo de polling de clientes AP.

    Para cada equipo wireless:
      1. Hace walk de ubntWlStatTable.
      2. Actualiza ap_interfaces (nuevos clientes).
      3. Escribe métricas a InfluxDB.
      4. Evalúa alertas de conteo de clientes AP.

    Returns:
        dict: {devices, clients, errors, skipped, duration_s}.
    """
    start = time.time()
    stats = {
        "devices": 0,
        "clients": 0,
        "errors": 0,
        "skipped": 0,
        "duration_s": 0.0,
    }

    devices = (
        Device.objects
        .filter(active=True, device_model__is_wireless_link=True)
        .select_related("device_model")
    )

    now = _utcnow()

    for device in devices:
        stats["devices"] += 1

        try:
            raw = _walk_all_columns(device)
            clients = _parse_clients(raw)
        except Exception as e:
            log.exception("[%s] Error en poll AP: %s", device.name, e)
            stats["errors"] += 1
            continue

        if not clients:
            log.debug("[%s] Sin clientes AP conectados.", device.name)
            stats["skipped"] += 1
            # Aun sin clientes, se evalúan alertas (para detectar "AP vacío").
            try:
                alerts.evaluate_metrics(device, {"ap_client_count": 0})
            except Exception as e:
                log.error("[%s] Error evaluando alertas AP: %s", device.name, e)
            continue

        # Actualizar ap_interfaces.
        try:
            _sync_ap_interfaces(device, clients)
        except Exception as e:
            log.error("[%s] Error actualizando ap_interfaces: %s", device.name, e)

        # Escribir métricas a InfluxDB.
        for c in clients:
            try:
                snr = None
                if c["signal"] is not None and c["noise_floor"] is not None:
                    snr = c["signal"] - c["noise_floor"]

                influx_writer.write_ap_client(
                    ap_device_name=device.name,
                    ap_ip=device.ip,
                    client_mac=c["mac"],
                    client_ip=c["ip"],
                    client_essid=c["essid"],
                    if_index=c["index"],
                    signal_dbm=c["signal"],
                    noise_dbm=c["noise_floor"],
                    ccq_pct=c["ccq"],
                    tx_rate_bps=c["tx_rate"],
                    rx_rate_bps=c["rx_rate"],
                    snr_db=snr,
                    timestamp=now,
                )
                stats["clients"] += 1
            except Exception as e:
                log.error(
                    "[%s/%s] Error escribiendo cliente a InfluxDB: %s",
                    device.name, c["mac"], e,
                )

        # Evaluar alertas con el conteo de clientes online.
        try:
            alerts.evaluate_metrics(device, {"ap_client_count": len(clients)})
        except Exception as e:
            log.error("[%s] Error evaluando alertas AP: %s", device.name, e)

        log.info(
            "[%s] AP clients: %d conectados",
            device.name, len(clients),
        )

    stats["duration_s"] = round(time.time() - start, 2)
    return stats


def _sync_ap_interfaces(device, clients: List[dict]):
    """
    Sincroniza ap_interfaces con los clientes del walk SIN borrar
    los que están offline (se conservan con su last_seen antiguo).

    Args:
        device: instancia de Device.
        clients: lista de clientes del walk actual.
    """
    existing = {
        c.get("mac", "").upper(): c
        for c in (device.ap_interfaces or [])
    }
    now_iso = _utcnow().isoformat()

    new_list = []
    for c in clients:
        mac = c["mac"].upper()
        if mac in existing:
            prev = existing[mac]
            prev["ip"] = c["ip"] or prev.get("ip", "")
            prev["essid"] = c["essid"] or prev.get("essid", "")
            prev["if_index"] = c["index"]
            prev["last_seen"] = now_iso
            new_list.append(prev)
        else:
            new_list.append({
                "if_index": c["index"],
                "mac": mac,
                "ip": c["ip"],
                "essid": c["essid"],
                "hostname": "",
                "first_seen": now_iso,
                "last_seen": now_iso,
            })

    # Preservar offline.
    seen_macs = {c["mac"].upper() for c in clients}
    for mac, prev in existing.items():
        if mac not in seen_macs:
            new_list.append(prev)

    device.ap_interfaces = new_list
    device.save(update_fields=["ap_interfaces", "updated_at"])