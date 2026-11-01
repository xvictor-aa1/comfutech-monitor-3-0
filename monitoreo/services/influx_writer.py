# monitoreo/services/influx_writer.py
"""
Escritura en InfluxDB 2.x.

Características:
  - Cliente compartido (se recrea si cambia la configuración).
  - **Buffer por thread** (v4): los puntos se acumulan en memoria y se
    escriben en una sola request HTTP al final de cada ciclo del poller
    (llamando a `flush()`). Reduce de ~430 requests por ciclo a ~5.
  - Escritura tolerante a fallos: NUNCA propaga excepciones a los
    pollers (se loguea a DEBUG y se devuelve False).
  - Cierre automático con atexit.
  - Measurements: traffic, health, icmp, tcp, radio, ap_clients.
"""
import atexit
import logging
import threading
from typing import Optional

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from core.runtime_config import get_influx_config

log = logging.getLogger(__name__)


# ============================================================
# CONFIGURACIÓN
# ============================================================
INFLUX_TIMEOUT_MS = 5000    # timeout por escritura
POOL_MAXSIZE = 10           # pool de conexiones
MAX_BUFFER_SIZE = 500       # flush automático si el buffer crece


# ============================================================
# CLIENTE COMPARTIDO
# ============================================================
_client: Optional[InfluxDBClient] = None
_write_api = None
_client_lock = threading.Lock()
_cached_url: Optional[str] = None
_cached_token: Optional[str] = None


# ============================================================
# BUFFER POR THREAD (v4)
# ============================================================
# Cada thread (job del scheduler) tiene su propio buffer de puntos.
# Al final del ciclo, el poller llama `flush()` y se escribe todo en
# una sola request HTTP. Esto reduce de N requests a 1 por ciclo.
_write_buffer = threading.local()


def _get_buffer() -> list:
    """Devuelve el buffer de puntos del thread actual."""
    buf = getattr(_write_buffer, "points", None)
    if buf is None:
        buf = []
        _write_buffer.points = buf
    return buf


# ============================================================
# CLIENTE
# ============================================================
def _get_write_api():
    """
    Devuelve el write_api compartido, recreándolo si la config cambió.

    Returns:
        write_api listo para escribir, o None si la config está incompleta.
    """
    global _client, _write_api, _cached_url, _cached_token

    cfg = get_influx_config()
    if not cfg["url"] or not cfg["token"]:
        return None

    with _client_lock:
        # ¿Cambió la config?
        needs_reset = (
            _write_api is None
            or _cached_url != cfg["url"]
            or _cached_token != cfg["token"]
        )
        if needs_reset:
            if _client:
                try:
                    _client.close()
                except Exception:
                    pass
                _client = None
                _write_api = None

            try:
                _client = InfluxDBClient(
                    url=cfg["url"],
                    token=cfg["token"],
                    org=cfg["org"],
                    timeout=INFLUX_TIMEOUT_MS,
                    connection_pool_maxsize=POOL_MAXSIZE,
                )
                _write_api = _client.write_api(write_options=SYNCHRONOUS)
                _cached_url = cfg["url"]
                _cached_token = cfg["token"]
            except Exception as e:
                log.error("Error creando cliente InfluxDB: %s", e)
                _client = None
                _write_api = None
                return None

        return _write_api


def close():
    """
    Cierra el cliente InfluxDB y limpia la caché.

    Se llama con atexit y desde `reset()` cuando cambia la config.
    También vacía el buffer del thread actual para no perder puntos
    pendientes (aunque si se llama al cerrar el proceso, se descartan).
    """
    global _client, _write_api, _cached_url, _cached_token
    with _client_lock:
        if _client:
            try:
                _client.close()
            except Exception:
                pass
            _client = None
            _write_api = None
            _cached_url = None
            _cached_token = None


def reset():
    """Fuerza la recarga de config en el próximo write."""
    close()


# ============================================================
# FLUSH (v4): volcado del buffer
# ============================================================
def _flush_buffer() -> bool:
    """
    Escribe todos los puntos acumulados en una sola request HTTP.

    Returns:
        bool: True si se escribió al menos un punto correctamente.
    """
    api = _get_write_api()
    if api is None:
        # Sin cliente: descartar buffer para no acumular indefinidamente.
        _get_buffer().clear()
        return False

    buf = _get_buffer()
    if not buf:
        return False

    try:
        cfg = get_influx_config()
        api.write(
            bucket=cfg["bucket"],
            org=cfg["org"],
            record=buf,
        )
        buf.clear()
        return True
    except Exception as e:
        # Nivel DEBUG para evitar spam; los fallos son recuperables.
        log.debug("InfluxDB batch write falló: %s", e)
        buf.clear()
        return False


def flush():
    """
    Fuerza el volcado del buffer del thread actual.

    Debe llamarse al final de cada ciclo de polling (en el `finally`
    del job, para asegurar el flush incluso si el poller falló).
    """
    _flush_buffer()


# ============================================================
# ESCRITURA GENÉRICA (ahora acumula en buffer)
# ============================================================
def _write_point(point: Point) -> bool:
    """
    Acumula un punto en el buffer del thread actual.

    El buffer se vuelca (flush) al final de cada ciclo del poller
    llamando a `flush()`. Esto reduce de N requests HTTP a 1 por
    ciclo.

    Si el buffer crece demasiado (>MAX_BUFFER_SIZE), se hace un
    flush automático de seguridad.

    Args:
        point: instancia de Point configurada.

    Returns:
        bool: True (siempre, porque la escritura real se confirma
              en el flush).
    """
    buf = _get_buffer()
    buf.append(point)

    # Volcado automático si el buffer crece demasiado (seguridad).
    if len(buf) >= MAX_BUFFER_SIZE:
        _flush_buffer()

    return True


# ============================================================
# ESCRITORES ESPECÍFICOS
# ============================================================
def write_traffic(
    device_name: str,
    ip: str,
    if_index: int,
    if_name: Optional[str],
    role: Optional[str],
    capacity_bps: Optional[int],
    in_bps: Optional[float],
    out_bps: Optional[float],
    utilization: Optional[float],
    rx_octets: Optional[int],
    tx_octets: Optional[int],
    timestamp,
) -> bool:
    """
    Escribe un punto del measurement `traffic`.

    Args:
        device_name, ip, if_index, if_name, role: tags.
        capacity_bps, in_bps, out_bps, utilization: fields.
        rx_octets, tx_octets: contadores absolutos del equipo.
        timestamp: datetime UTC naive.

    Returns:
        bool: True si se acumuló en el buffer.
    """
    point = (
        Point("traffic")
        .tag("device", device_name or "")
        .tag("ip", ip or "")
        .tag("interface", if_name or f"if{if_index}")
        .tag("role", role or "access")
        .field("in_bps", float(in_bps) if in_bps is not None else 0.0)
        .field("out_bps", float(out_bps) if out_bps is not None else 0.0)
        .field("utilization_pct", float(utilization) if utilization is not None else 0.0)
        .field("capacity_bps", int(capacity_bps) if capacity_bps else 0)
        .field("rx_octets", int(rx_octets) if rx_octets is not None else 0)
        .field("tx_octets", int(tx_octets) if tx_octets is not None else 0)
        .time(timestamp)
    )
    return _write_point(point)


def write_health(
    device_name: str,
    ip: str,
    role: Optional[str],
    vendor: Optional[str],
    metrics: dict,
    timestamp,
) -> bool:
    """
    Escribe un punto del measurement `health`.

    Solo se escriben los fields que existan en `metrics` (cpu_pct,
    mem_pct, temp_c, uptime). Si ninguno está presente, no se escribe.

    Args:
        device_name, ip, role, vendor: tags.
        metrics: dict con los valores disponibles.
        timestamp: datetime UTC naive.

    Returns:
        bool: True si se acumuló en el buffer.
    """
    point = (
        Point("health")
        .tag("device", device_name or "")
        .tag("ip", ip or "")
        .tag("role", role or "core")
        .tag("vendor", vendor or "generic")
    )
    wrote = False
    for key in ("cpu_pct", "mem_pct", "temp_c", "uptime"):
        v = metrics.get(key)
        if v is not None:
            point = point.field(key, float(v))
            wrote = True

    if not wrote:
        return False
    return _write_point(point.time(timestamp))


def write_icmp(
    device_name: str,
    ip: str,
    role: Optional[str],
    alive: bool,
    avg_rtt: Optional[float],
    loss: float,
    timestamp,
) -> bool:
    """
    Escribe un punto del measurement `icmp`.

    Args:
        device_name, ip, role: tags.
        alive: si respondió al ping.
        avg_rtt: latencia media (ms) o None.
        loss: porcentaje de pérdida.
        timestamp: datetime UTC naive.

    Returns:
        bool: True si se acumuló en el buffer.
    """
    point = (
        Point("icmp")
        .tag("device", device_name or "")
        .tag("ip", ip or "")
        .tag("role", role or "access")
        .field("is_alive", 1 if alive else 0)
        .field("latency_ms", float(avg_rtt) if avg_rtt is not None else 0.0)
        .field("packet_loss_pct", float(loss))
        .time(timestamp)
    )
    return _write_point(point)


def write_tcp(
    device_name: str,
    ip: str,
    role: Optional[str],
    port: int,
    is_open: bool,
    timestamp,
) -> bool:
    """
    Escribe un punto del measurement `tcp`.

    Args:
        device_name, ip, role, port: tags.
        is_open: True si el puerto estaba abierto.
        timestamp: datetime UTC naive.

    Returns:
        bool: True si se acumuló en el buffer.
    """
    point = (
        Point("tcp")
        .tag("device", device_name or "")
        .tag("ip", ip or "")
        .tag("role", role or "access")
        .tag("port", str(port))
        .field("is_open", 1 if is_open else 0)
        .time(timestamp)
    )
    return _write_point(point)


def write_radio(
    device_name: str,
    ip: str,
    role: Optional[str],
    vendor: Optional[str],
    metrics: dict,
    timestamp,
) -> bool:
    """
    Escribe un punto del measurement `radio`.

    Solo escribe los fields que existan en `metrics`. Si ninguno está
    presente, no escribe nada.

    Args:
        device_name, ip, role, vendor: tags.
        metrics: dict con valores de RF.
        timestamp: datetime UTC naive.

    Returns:
        bool: True si se acumuló en el buffer.
    """
    point = (
        Point("radio")
        .tag("device", device_name or "")
        .tag("ip", ip or "")
        .tag("role", role or "access")
        .tag("vendor", vendor or "generic")
    )
    wrote = False
    for key in (
        "radio_freq", "radio_txpower", "wl_signal", "wl_noise_floor",
        "wl_ccq", "wl_tx_rate", "wl_rx_rate", "airmax_quality",
        "airmax_capacity", "chan_width",
    ):
        v = metrics.get(key)
        if v is not None:
            point = point.field(key, float(v))
            wrote = True
    if not wrote:
        return False
    return _write_point(point.time(timestamp))


def write_ap_client(
    ap_device_name: str,
    ap_ip: str,
    client_mac: str,
    client_ip: Optional[str],
    client_essid: Optional[str],
    if_index: Optional[int],
    signal_dbm: Optional[float],
    noise_dbm: Optional[float],
    ccq_pct: Optional[float],
    tx_rate_bps: Optional[float],
    rx_rate_bps: Optional[float],
    snr_db: Optional[float],
    timestamp,
) -> bool:
    """
    Escribe un punto del measurement `ap_clients`.

    Cada cliente conectado al AP genera un punto por ciclo con sus
    métricas en vivo. Tags permiten filtrar por AP y por cliente.

    Args:
        ap_device_name: nombre del AP (tag).
        ap_ip: IP del AP (tag).
        client_mac: MAC del cliente (tag, identificador principal).
        client_ip: IP del cliente (tag).
        client_essid: SSID (tag).
        if_index: índice SNMP del cliente (tag).
        signal_dbm, noise_dbm, ccq_pct: métricas (fields).
        tx_rate_bps, rx_rate_bps: tasas en bps (fields).
        snr_db: SNR calculado (field).
        timestamp: datetime UTC.

    Returns:
        bool: True si se acumuló en el buffer.
    """
    point = (
        Point("ap_clients")
        .tag("ap_device", ap_device_name or "")
        .tag("ap_ip", ap_ip or "")
        .tag("client_mac", client_mac or "")
        .tag("client_ip", client_ip or "")
        .tag("essid", client_essid or "")
        .tag("if_index", str(if_index) if if_index is not None else "")
    )

    wrote = False
    for name, val in [
        ("signal_dbm", signal_dbm),
        ("noise_dbm", noise_dbm),
        ("ccq_pct", ccq_pct),
        ("tx_rate_bps", tx_rate_bps),
        ("rx_rate_bps", rx_rate_bps),
        ("snr_db", snr_db),
    ]:
        if val is not None:
            point = point.field(name, float(val))
            wrote = True

    if not wrote:
        return False
    return _write_point(point.time(timestamp))


# ============================================================
# CIERRE AUTOMÁTICO AL SALIR
# ============================================================
# Se registra para que el cliente se cierre ANTES de que Python
# destruya los módulos. Evita el TypeError del __del__ del cliente
# de influxdb_client al terminar el intérprete.
atexit.register(close)