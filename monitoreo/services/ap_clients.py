# monitoreo/services/ap_clients.py
"""
Servicio de clientes AP: discovery + polling de métricas.

Solo procesa equipos con device_model.is_wireless_link=True.
Los clientes se guardan en Device.ap_interfaces (config estática).
Las métricas en vivo se escriben a InfluxDB (measurement "ap_clients").

El walk SNMP se realiza sobre el subárbol completo de `ubntStaTable`
(1 sola consulta por AP), que es la tabla real de estaciones
conectadas en AirOS 8.

Estructura del OID de `ubntStaTable`:
    1.3.6.1.4.1.41112.1.4.7.1.{columna}.1.{o1}.{o2}.{o3}.{o4}.{o5}.{o6}
                                └──┬──┘ │ └──────────┬──────────────┘
                                  col   entry    MAC (6 octetos)

La fila NO se indexa por un entero: se indexa por los 6 octetos de la
MAC del cliente. Dos clientes distintos con la misma MAC (imposible en
la práctica) compartirían fila.

Columnas capturadas (AirOS 8.7.x):
    1  → mac                MAC (OctetString de 6 bytes)
    2  → name               Nombre del dispositivo (OctetString, puede
                            tener espacios finales o estar en hex 0x...)
    3  → signal             Señal local (dBm, Integer32 negativo)
    4  → noise_floor        Piso de ruido (dBm, Integer32 negativo)
    5  → distance           Distancia (metros, Integer32)
    6  → ccq                Calidad de enlace (décimas de %: 333 = 33.3%)
    8  → airmax_quality     Calidad airMAX (puede ser 0 si airMAX está off)
    9  → airmax_capacity    Capacidad airMAX (puede ser 0)
    10 → ip                 Última IP conocida (IpAddress)
    11 → tx_rate            Tasa TX (bps, Integer32)
    12 → rx_rate            Tasa RX (bps, Integer32)

Columnas NO presentes en este firmware:
    7  → flag interno (siempre 2)
    13 → ?
    14 → ?
    15 → conn_time (NO existe en AirOS 8.7.25)

Formato de ap_interfaces (JSONField en Device):
    [
      {
        "mac": "AA:BB:CC:DD:EE:01",
        "name": "LiteBeam 5AC",         # nombre del dispositivo (SNMP)
        "ip": "172.14.3.100",
        "hostname": "",                  # editable manualmente
        "first_seen": "2026-10-22T23:30:00+00:00",
        "last_seen":  "2026-10-23T10:00:00+00:00"
      },
      ...
    ]
"""
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from django.utils import timezone as dj_tz

from inventario.models import Device
from . import alerts, influx_writer
from .snmp_client import snmp_walk, to_int

log = logging.getLogger(__name__)


# ============================================================
# OIDs DE ubntStaTable (Station List de AirOS 8)
# ============================================================
AP_COLUMNS = {
    "mac":             "1.3.6.1.4.1.41112.1.4.7.1.1.1",
    "name":            "1.3.6.1.4.1.41112.1.4.7.1.2.1",
    "signal":          "1.3.6.1.4.1.41112.1.4.7.1.3.1",
    "noise_floor":     "1.3.6.1.4.1.41112.1.4.7.1.4.1",
    "distance":        "1.3.6.1.4.1.41112.1.4.7.1.5.1",
    "ccq":             "1.3.6.1.4.1.41112.1.4.7.1.6.1",
    "airmax_quality":  "1.3.6.1.4.1.41112.1.4.7.1.8.1",
    "airmax_capacity": "1.3.6.1.4.1.41112.1.4.7.1.9.1",
    "ip":              "1.3.6.1.4.1.41112.1.4.7.1.10.1",
    "tx_rate":         "1.3.6.1.4.1.41112.1.4.7.1.11.1",
    "rx_rate":         "1.3.6.1.4.1.41112.1.4.7.1.12.1",
}

# Subárbol completo de la tabla de estaciones.
TABLE_BASE = "1.3.6.1.4.1.41112.1.4.7.1"


def _utcnow() -> datetime:
    """Hora actual en UTC (aware)."""
    return dj_tz.now()


# ============================================================
# DECODIFICADORES DE VALORES SNMP
# ============================================================
def _decode_name(val) -> str:
    """
    Decodifica el nombre del dispositivo (OctetString → str).

    Casos posibles:
      - Texto normal: b"LiteBeam 5AC" → "LiteBeam 5AC"
      - Texto con espacios finales: b"NERIO " → "NERIO"
      - Texto con tildes: pysnmp devuelve "0x524f444f..." → se decodifica
        como UTF-8 → "RODOLFO RODRÍGUEZ"
      - Vacío → ""

    Args:
        val: valor SNMP crudo (OctetString, bytes o str).

    Returns:
        str: nombre limpio (sin espacios finales).
    """
    if val is None:
        return ""

    # 1. Intentar obtener bytes crudos.
    raw_bytes = None
    if hasattr(val, "asOctets"):
        try:
            raw_bytes = val.asOctets()
        except Exception:
            pass
    elif isinstance(val, bytes):
        raw_bytes = val

    if raw_bytes is not None:
        try:
            return raw_bytes.decode("utf-8", errors="replace").strip()
        except Exception:
            try:
                return raw_bytes.decode("latin-1", errors="replace").strip()
            except Exception:
                return ""

    # 2. Si pysnmp devolvió "0x...", decodificar el hex.
    s = str(val).strip()
    if s.startswith("0x"):
        try:
            raw = bytes.fromhex(s[2:])
            return raw.decode("utf-8", errors="replace").strip()
        except Exception:
            pass
    return s


def _decode_ip(val) -> str:
    """
    Decodifica una dirección IP (IpAddress → "A.B.C.D").

    `prettyPrint()` de pysnmp devuelve "172.14.3.10" para IpAddress.
    Evita usar `asOctets()`, que devuelve los 4 bytes crudos y
    rompe la representación.

    Args:
        val: valor SNMP de tipo IpAddress.

    Returns:
        str: "A.B.C.D" o "" si es 0.0.0.0 / inválida.
    """
    if val is None:
        return ""

    try:
        pp = val.prettyPrint()
        if isinstance(pp, bytes):
            pp = pp.decode("utf-8", errors="ignore")
        s = str(pp).strip()
        if s and s != "0.0.0.0":
            return s
    except Exception:
        pass

    return ""


# ============================================================
# WALK DE LA TABLA COMPLETA
# ============================================================
def _walk_all_columns(device) -> Dict[str, Dict[str, object]]:
    """
    Hace un único walk del subárbol ubntStaTable y agrupa los
    valores por columna y MAC.

    La clave de cada fila es la MAC en formato canónico
    "AA:BB:CC:DD:EE:FF", extraída de los 6 octetos del OID.

    Args:
        device: instancia de Device.

    Returns:
        dict: {col_name: {mac_str: value}}.
    """
    # Mapa inverso: OID completo de columna → nombre corto.
    column_map = {oid: name for name, oid in AP_COLUMNS.items()}

    raw: Dict[str, Dict[str, object]] = {name: {} for name in AP_COLUMNS}

    try:
        pairs = snmp_walk(device, TABLE_BASE)
    except Exception as e:
        log.debug("[%s] Walk ubntStaTable falló: %s", device.name, e)
        return raw

    prefix = TABLE_BASE + "."
    for oid_str, val in pairs:
        if not oid_str.startswith(prefix):
            continue
        suffix = oid_str[len(prefix):]
        parts = suffix.split(".")
        # Estructura: {col}.1.{o1}.{o2}.{o3}.{o4}.{o5}.{o6}
        if len(parts) < 8:
            continue
        try:
            col_num = int(parts[0])
            # parts[1] = ".1" de la entry, se ignora.
            octets = [int(p) for p in parts[2:8]]
        except (ValueError, IndexError):
            continue

        # La fila se identifica por la MAC completa.
        mac_str = ":".join(f"{o:02X}" for o in octets)

        col_oid = f"{TABLE_BASE}.{col_num}.1"
        col_name = column_map.get(col_oid)
        if col_name:
            raw[col_name][mac_str] = val

    return raw


def _parse_clients(raw: Dict[str, Dict[str, object]]) -> List[dict]:
    """
    Convierte los valores crudos del walk en una lista de clientes.

    Aplica las conversiones de unidades:
      - CCQ: valor en décimas de % (ej. 333 → 33.3%).
      - TX/RX Rate: ya vienen en bps (ej. 39000000 = 39 Mbps).
      - Distance: en metros (ya viene como entero).

    Args:
        raw: salida de _walk_all_columns.

    Returns:
        list: [{mac, name, ip, signal, noise_floor, distance, ccq,
                airmax_quality, airmax_capacity, tx_rate, rx_rate}, ...]
    """
    # Unión de todas las MACs detectadas en cualquier columna.
    all_macs = set()
    for values in raw.values():
        all_macs.update(values.keys())

    clients = []
    for mac in sorted(all_macs):
        # --- CCQ: décimas de porcentaje → porcentaje.
        ccq_raw = to_int(raw["ccq"].get(mac))
        ccq = round(ccq_raw * 0.1, 1) if ccq_raw is not None else None

        # --- Tasas: ya están en bps.
        tx_rate = to_int(raw["tx_rate"].get(mac))
        rx_rate = to_int(raw["rx_rate"].get(mac))

        # --- Distancia: metros.
        distance = to_int(raw["distance"].get(mac))

        # --- airMAX: puede ser 0 si airMAX está deshabilitado.
        airmax_quality = to_int(raw["airmax_quality"].get(mac))
        airmax_capacity = to_int(raw["airmax_capacity"].get(mac))

        clients.append({
            "mac": mac,
            "name": _decode_name(raw["name"].get(mac)),
            "ip": _decode_ip(raw["ip"].get(mac)),
            "signal": to_int(raw["signal"].get(mac)),
            "noise_floor": to_int(raw["noise_floor"].get(mac)),
            "distance": distance,
            "ccq": ccq,
            "airmax_quality": airmax_quality,
            "airmax_capacity": airmax_capacity,
            "tx_rate": tx_rate,
            "rx_rate": rx_rate,
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
                prev["name"] = c["name"] or prev.get("name", "")
                prev["last_seen"] = now_iso
                new_list.append(prev)
                result["updated"] += 1
            else:
                new_list.append({
                    "mac": mac,
                    "name": c["name"],
                    "ip": c["ip"],
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
      1. Hace walk de ubntStaTable.
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
                    client_name=c["name"],
                    signal_dbm=c["signal"],
                    noise_dbm=c["noise_floor"],
                    ccq_pct=c["ccq"],
                    tx_rate_bps=c["tx_rate"],
                    rx_rate_bps=c["rx_rate"],
                    snr_db=snr,
                    distance_m=c["distance"],
                    airmax_quality=c["airmax_quality"],
                    airmax_capacity=c["airmax_capacity"],
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
            prev["name"] = c["name"] or prev.get("name", "")
            prev["last_seen"] = now_iso
            new_list.append(prev)
        else:
            new_list.append({
                "mac": mac,
                "name": c["name"],
                "ip": c["ip"],
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