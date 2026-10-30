# monitoreo/services/influx_reader.py
"""
Lectura de las últimas métricas desde InfluxDB.

Optimizaciones:
  - Un ÚNICO cliente InfluxDB compartido.
  - Caché en memoria (TTL configurable) para el snapshot completo.
  - Errores silenciosos: si InfluxDB falla, devuelve dicts vacíos
    en lugar de lanzar excepción.
  - Timeout holgado (10s) por si InfluxDB está bajo carga, esto para
    que aunque haya 10 clientes remotos consultando al mismo tiempo,
    solo se hacen 4 queries reales por cada TTL al servidor InfluxDB.

Measurements consultados: icmp, traffic, health, tcp, radio.
"""
import atexit
import logging
import threading
import time
from typing import Optional

from influxdb_client import InfluxDBClient

from core.runtime_config import get_influx_config

log = logging.getLogger(__name__)

# Rango de tiempo hacia atrás para "última métrica"
LOOKBACK_RANGE = "-1h"

# TTL de la caché del snapshot (segundos)
CACHE_SECONDS = 5

# Timeout de cada consulta a InfluxDB
INFLUX_TIMEOUT_MS = 10000

# Pool de conexiones
POOL_MAXSIZE = 20


# ============================================================
# ESTADO GLOBAL
# ============================================================
_client: Optional[InfluxDBClient] = None
_client_lock = threading.Lock()
_cached_url: Optional[str] = None
_cached_token: Optional[str] = None

_snapshot_cache: dict = {}
_snapshot_cache_time: float = 0.0
_snapshot_lock = threading.Lock()


# ============================================================
# GESTIÓN DEL CLIENTE
# ============================================================
def _get_client() -> Optional[InfluxDBClient]:
    """
    Devuelve el cliente InfluxDB compartido, recreándolo si cambió
    la configuración (URL o token).

    Returns:
        InfluxDBClient o None si la config está incompleta.
    """
    global _client, _cached_url, _cached_token

    cfg = get_influx_config()
    if not cfg["url"] or not cfg["token"]:
        return None

    with _client_lock:
        # Si cambió la config, cerrar el cliente actual
        if _client and (_cached_url != cfg["url"] or _cached_token != cfg["token"]):
            try:
                _client.close()
            except Exception:
                pass
            _client = None

        # Crear si no existe
        if _client is None:
            _client = InfluxDBClient(
                url=cfg["url"],
                token=cfg["token"],
                org=cfg["org"],
                timeout=INFLUX_TIMEOUT_MS,
                connection_pool_maxsize=POOL_MAXSIZE,
            )
            _cached_url = cfg["url"]
            _cached_token = cfg["token"]

        return _client


def close():
    """
    Cierra el cliente InfluxDB compartido.

    Se llama al salir del proceso (atexit) y cuando la config cambia.
    """
    global _client, _cached_url, _cached_token
    with _client_lock:
        if _client:
            try:
                _client.close()
            except Exception:
                pass
            _client = None
            _cached_url = None
            _cached_token = None


def invalidate_cache():
    """
    Invalida la caché del snapshot.

    Se llama cuando el usuario guarda la configuración de InfluxDB
    para forzar la próxima consulta a traer datos frescos.
    """
    global _snapshot_cache, _snapshot_cache_time
    with _snapshot_lock:
        _snapshot_cache = {}
        _snapshot_cache_time = 0.0
    log.info("Caché de InfluxDB invalidada.")


# ============================================================
# QUERIES POR MEASUREMENT
# ============================================================
def _query_last_icmp(client, bucket: str) -> dict:
    """
    Últimos valores ICMP por dispositivo.

    Returns:
        dict: {device_name: {alive, rtt, loss, ts}}
    """
    try:
        qapi = client.query_api()
        flux = f'''
        from(bucket: "{bucket}")
          |> range(start: {LOOKBACK_RANGE})
          |> filter(fn: (r) => r._measurement == "icmp")
          |> filter(fn: (r) => r._field == "is_alive"
                              or r._field == "latency_ms"
                              or r._field == "packet_loss_pct")
          |> last()
        '''
        records = []
        for table in qapi.query(flux):
            records.extend(table.records)

        result = {}
        for r in records:
            device = r.values.get("device")
            field = r.get_field()
            value = r.get_value()
            ts = r.get_time()

            if device not in result:
                result[device] = {"ts": ts}
            result[device][field] = value
            if ts and (not result[device].get("ts") or ts > result[device]["ts"]):
                result[device]["ts"] = ts

        for d in result:
            r = result[d]
            r["alive"] = bool(r.get("is_alive", 0))
            r["rtt"] = r.get("latency_ms")
            r["loss"] = r.get("packet_loss_pct")
            r.pop("is_alive", None)
            r.pop("latency_ms", None)
            r.pop("packet_loss_pct", None)

        return result
    except Exception as e:
        log.warning("Error consultando ICMP en InfluxDB: %s", e)
        return {}


def _query_last_traffic(client, bucket: str) -> dict:
    """
    Últimos valores de tráfico por dispositivo/interfaz.

    Returns:
        dict: {device_name: [{interface, in_bps, out_bps, utilization_pct,
                              capacity_bps, ts}, ...]}
    """
    try:
        qapi = client.query_api()
        flux = f'''
        from(bucket: "{bucket}")
          |> range(start: {LOOKBACK_RANGE})
          |> filter(fn: (r) => r._measurement == "traffic")
          |> filter(fn: (r) => r._field == "in_bps"
                              or r._field == "out_bps"
                              or r._field == "utilization_pct"
                              or r._field == "capacity_bps")
          |> last()
        '''
        records = []
        for table in qapi.query(flux):
            records.extend(table.records)

        result = {}
        for r in records:
            device = r.values.get("device")
            interface = r.values.get("interface")
            field = r.get_field()
            value = r.get_value()
            ts = r.get_time()

            if device not in result:
                result[device] = {}
            if interface not in result[device]:
                result[device][interface] = {"interface": interface, "ts": ts}
            result[device][interface][field] = value
            if ts and (not result[device][interface].get("ts")
                       or ts > result[device][interface]["ts"]):
                result[device][interface]["ts"] = ts

        for device in result:
            result[device] = list(result[device].values())

        return result
    except Exception as e:
        log.warning("Error consultando traffic en InfluxDB: %s", e)
        return {}


def _query_last_health(client, bucket: str) -> dict:
    """
    Últimos valores de chasis por dispositivo.

    Returns:
        dict: {device_name: {cpu, mem, temp, uptime, ts}}
    """
    try:
        qapi = client.query_api()
        flux = f'''
        from(bucket: "{bucket}")
          |> range(start: {LOOKBACK_RANGE})
          |> filter(fn: (r) => r._measurement == "health")
          |> filter(fn: (r) => r._field == "cpu_pct"
                              or r._field == "mem_pct"
                              or r._field == "temp_c"
                              or r._field == "uptime")
          |> last()
        '''
        records = []
        for table in qapi.query(flux):
            records.extend(table.records)

        result = {}
        for r in records:
            device = r.values.get("device")
            field = r.get_field()
            value = r.get_value()
            ts = r.get_time()

            if device not in result:
                result[device] = {"ts": ts}
            result[device][field] = value
            if ts and (not result[device].get("ts") or ts > result[device]["ts"]):
                result[device]["ts"] = ts

        for d in result:
            r = result[d]
            r["cpu"] = r.pop("cpu_pct", None)
            r["mem"] = r.pop("mem_pct", None)
            r["temp"] = r.pop("temp_c", None)
            r["uptime"] = r.pop("uptime", None)

        return result
    except Exception as e:
        log.warning("Error consultando health en InfluxDB: %s", e)
        return {}


def _query_last_tcp(client, bucket: str) -> dict:
    """
    Últimos valores de puertos TCP por dispositivo.

    Returns:
        dict: {device_name: [{port, is_open, ts}, ...]}
    """
    try:
        qapi = client.query_api()
        flux = f'''
        from(bucket: "{bucket}")
          |> range(start: {LOOKBACK_RANGE})
          |> filter(fn: (r) => r._measurement == "tcp")
          |> filter(fn: (r) => r._field == "is_open")
          |> last()
        '''
        records = []
        for table in qapi.query(flux):
            records.extend(table.records)

        result = {}
        for r in records:
            device = r.values.get("device")
            port = r.values.get("port")
            value = r.get_value()
            ts = r.get_time()

            if device not in result:
                result[device] = []
            result[device].append({
                "port": port,
                "is_open": bool(value),
                "ts": ts,
            })

        return result
    except Exception as e:
        log.warning("Error consultando tcp en InfluxDB: %s", e)
        return {}


def _query_last_radio(client, bucket: str) -> dict:
    """
    Últimos valores de radiofrecuencia por dispositivo.

    Returns:
        dict: {device_name: {radio_freq, radio_txpower, wl_signal,
                              wl_noise_floor, wl_ccq, wl_tx_rate,
                              wl_rx_rate, airmax_quality, airmax_capacity,
                              chan_width, ts}}
    """
    try:
        qapi = client.query_api()
        flux = f'''
        from(bucket: "{bucket}")
          |> range(start: {LOOKBACK_RANGE})
          |> filter(fn: (r) => r._measurement == "radio")
          |> filter(fn: (r) => r._field == "radio_freq"
                              or r._field == "radio_txpower"
                              or r._field == "wl_signal"
                              or r._field == "wl_noise_floor"
                              or r._field == "wl_ccq"
                              or r._field == "wl_tx_rate"
                              or r._field == "wl_rx_rate"
                              or r._field == "airmax_quality"
                              or r._field == "airmax_capacity"
                              or r._field == "chan_width")
          |> last()
        '''
        records = []
        for table in qapi.query(flux):
            records.extend(table.records)

        result = {}
        for r in records:
            device = r.values.get("device")
            field = r.get_field()
            value = r.get_value()
            ts = r.get_time()
            if device not in result:
                result[device] = {"ts": ts}
            result[device][field] = value
            if ts and (not result[device].get("ts") or ts > result[device]["ts"]):
                result[device]["ts"] = ts
        return result
    except Exception as e:
        log.warning("Error consultando radio en InfluxDB: %s", e)
        return {}


def _query_last_ap_clients(client, bucket: str) -> dict:
    """
    Últimos valores de clientes AP por dispositivo AP.

    Returns:
        dict: {ap_device_name: [{
            client_mac, client_ip, essid, if_index,
            signal_dbm, noise_dbm, ccq_pct,
            tx_rate_bps, rx_rate_bps, snr_db, ts
        }, ...]}
    """
    try:
        qapi = client.query_api()
        flux = f'''
        from(bucket: "{bucket}")
          |> range(start: {LOOKBACK_RANGE})
          |> filter(fn: (r) => r._measurement == "ap_clients")
          |> filter(fn: (r) => r._field == "signal_dbm"
                              or r._field == "noise_dbm"
                              or r._field == "ccq_pct"
                              or r._field == "tx_rate_bps"
                              or r._field == "rx_rate_bps"
                              or r._field == "snr_db")
          |> last()
        '''
        records = []
        for table in qapi.query(flux):
            records.extend(table.records)

        result = {}
        for r in records:
            ap = r.values.get("ap_device")
            mac = r.values.get("client_mac")
            if not ap or not mac:
                continue
            key = (ap, mac)
            field = r.get_field()
            value = r.get_value()
            ts = r.get_time()

            if ap not in result:
                result[ap] = {}
            if mac not in result[ap]:
                result[ap][mac] = {
                    "client_mac": mac,
                    "client_ip": r.values.get("client_ip", ""),
                    "essid": r.values.get("essid", ""),
                    "if_index": r.values.get("if_index"),
                    "ts": ts,
                }
            result[ap][mac][field] = value
            if ts and (not result[ap][mac].get("ts") or ts > result[ap][mac]["ts"]):
                result[ap][mac]["ts"] = ts

        # Convertir a lista por AP
        for ap in result:
            result[ap] = list(result[ap].values())

        return result
    except Exception as e:
        log.warning("Error consultando ap_clients en InfluxDB: %s", e)
        return {}


# ============================================================
# SNAPSHOT CON CACHÉ
# ============================================================
def get_live_snapshot() -> dict:
    """
    Devuelve todas las últimas métricas consolidadas.

    Usa caché de CACHE_SECONDS segundos para evitar saturar InfluxDB
    cuando hay múltiples clientes remotos haciendo polling.

    Si InfluxDB falla o no está configurado, devuelve dicts vacíos.

    Returns:
        dict: {"icmp": {}, "traffic": {}, "health": {}, "tcp": {}}
    """
    global _snapshot_cache, _snapshot_cache_time

    # ¿Caché válida?
    now = time.time()

    with _snapshot_lock:
        if _snapshot_cache and (now - _snapshot_cache_time) < CACHE_SECONDS:
            return _snapshot_cache


    client = _get_client()
    if client is None:
        empty = {
            "icmp": {}, "traffic": {}, "health": {},
            "tcp": {}, "radio": {}, "ap_clients": {},
        }
        with _snapshot_lock:
            _snapshot_cache = empty
            _snapshot_cache_time = now
        return empty

    cfg = get_influx_config()
    bucket = cfg["bucket"]

    snapshot = {
        "icmp":    _query_last_icmp(client, bucket),
        "traffic": _query_last_traffic(client, bucket),
        "health":  _query_last_health(client, bucket),
        "tcp":     _query_last_tcp(client, bucket),
        "radio":   _query_last_radio(client, bucket),
        "ap_clients": _query_last_ap_clients(client, bucket),
    }

    with _snapshot_lock:
        _snapshot_cache = snapshot
        _snapshot_cache_time = now
    return snapshot


def get_sparkline_series(
    device_name: str,
    metric: str,
    interface_name: Optional[str] = None,
    minutes: int = 10,
) -> list:
    """
    Devuelve una serie temporal de los últimos N minutos.

    Optimizada para sparklines de dashboard: agrupa con
    aggregateWindow(every: 30s) para reducir puntos (20 puntos
    para 10 minutos), y devuelve solo _time y _value.

    Args:
        device_name: nombre del device (tag en InfluxDB).
        metric: "traffic_in" | "traffic_out" | "signal" | "ccq"
                | "cpu" | "mem" | "latency".
        interface_name: nombre de la interfaz (para traffic_*).
        minutes: ventana temporal (5-60 min).

    Returns:
        list: [{t: iso_timestamp, v: value}, ...] ordenado ascendente.
    """
    client = _get_client()
    if client is None:
        return []

    cfg = get_influx_config()
    bucket = cfg["bucket"]

    # ------------------------------------------------------------
    # Configuración por métrica
    # ------------------------------------------------------------
    config = {
        "traffic_in":  ("traffic", "in_bps"),
        "traffic_out": ("traffic", "out_bps"),
        "signal":      ("radio",   "wl_signal"),
        "ccq":         ("radio",   "wl_ccq"),
        "cpu":         ("health",  "cpu_pct"),
        "mem":         ("health",  "mem_pct"),
        "temp":        ("health",  "temp_c"),
        "latency":     ("icmp",    "latency_ms"),
        "packet_loss": ("icmp",    "packet_loss_pct"),
    }

    if metric not in config:
        return []

    measurement, field = config[metric]

    # Filtro adicional por interfaz (solo para traffic_*)
    extra_filter = ""
    if interface_name and metric.startswith("traffic_"):
        safe_iface = interface_name.replace('"', '\\"')
        extra_filter = f'|> filter(fn: (r) => r.interface == "{safe_iface}")'

    # Sanear nombre del device
    safe_device = device_name.replace('"', '\\"')

    # Clamp minutos entre 5 y 60
    minutes = max(5, min(60, int(minutes)))

    try:
        qapi = client.query_api()
        flux = f'''
        from(bucket: "{bucket}")
          |> range(start: -{minutes}m)
          |> filter(fn: (r) => r._measurement == "{measurement}")
          |> filter(fn: (r) => r._field == "{field}")
          |> filter(fn: (r) => r.device == "{safe_device}")
          {extra_filter}
          |> aggregateWindow(every: 30s, fn: mean, createEmpty: false)
          |> keep(columns: ["_time", "_value"])
          |> sort(columns: ["_time"])
        '''
        records = []
        for table in qapi.query(flux):
            for r in table.records:
                try:
                    records.append({
                        "t": r.get_time().isoformat(),
                        "v": float(r.get_value()),
                    })
                except (ValueError, TypeError):
                    continue
        return records
    except Exception as e:
        log.debug("Error consultando sparkline (%s/%s): %s", device_name, metric, e)
        return []


# ============================================================
# CIERRE AL SALIR
# ============================================================
atexit.register(close)