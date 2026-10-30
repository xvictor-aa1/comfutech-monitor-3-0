# monitoreo/services/icmp_tcp.py
"""
Poller ICMP (ping) y TCP (puertos) paralelizado.

Características:
  - Ping con parsing multi-encoding (utf-8, cp1252, cp850, latin-1).
  - Cálculo de latencia media y pérdida de paquetes.
  - Chequeo TCP de puertos configurables por equipo.
  - Paralelización con ThreadPoolExecutor (20 workers por defecto).
  - Timeout por thread y manejo de excepciones por dispositivo.
"""
import concurrent.futures
import logging
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from django.db import close_old_connections

from inventario.models import Device
from . import alerts, influx_writer

log = logging.getLogger(__name__)


# ============================================================
# CONFIGURACIÓN
# ============================================================
PING_COUNT = 1
PING_TIMEOUT_MS = 1000
TCP_TIMEOUT_SEC = 1
MAX_WORKERS = 20

# Regex para extraer el RTT del output del ping (inglés y español)
_PING_RTT_RE = re.compile(
    r"(?:tiempo|time)\s*[=<]\s*(\d+(?:[.,]\d+)?)\s*ms",
    re.IGNORECASE,
)

# Flags para no abrir ventana de consola en Windows
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# ============================================================
# HELPERS
# ============================================================
def _utcnow() -> datetime:
    """Hora actual en UTC como datetime naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _decode_output(raw: bytes) -> str:
    """
    Decodifica la salida del ping probando múltiples encodings.

    Windows en español suele devolver cp850 o cp1252, mientras que en
    inglés usa utf-8 o latin-1.

    Args:
        raw: bytes de stdout.

    Returns:
        str: texto decodificado.
    """
    if not raw:
        return ""
    for enc in ("utf-8", "cp1252", "cp850", "latin-1"):
        try:
            text = raw.decode(enc, errors="strict")
            if text:
                return text
        except (UnicodeDecodeError, LookupError):
            continue
    # Fallback: latin-1 nunca falla
    return raw.decode("latin-1", errors="ignore")


# ============================================================
# ICMP (PING)
# ============================================================
def _icmp_probe(
    ip: str,
    count: int = PING_COUNT,
    timeout_ms: int = PING_TIMEOUT_MS,
) -> Tuple[bool, Optional[float], float]:
    """
    Ejecuta ping ICMP del sistema operativo y calcula métricas.

    Args:
        ip: IP del equipo.
        count: número de intentos.
        timeout_ms: timeout por intento (ms).

    Returns:
        tuple: (is_alive, avg_rtt_ms, packet_loss_pct).
    """
    if sys.platform == "win32":
        base_cmd = ["ping", "-n", "1", "-w", str(timeout_ms)]
    else:
        base_cmd = ["ping", "-c", "1", "-W", str(int(timeout_ms / 1000) or 1)]

    pings_ok = 0
    rtts: List[float] = []

    for _ in range(count):
        try:
            r = subprocess.run(
                base_cmd + [ip],
                capture_output=True,
                timeout=(timeout_ms / 1000.0) + 2,
                creationflags=_CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            log.debug("Timeout ping %s", ip)
            continue
        except Exception as e:
            log.debug("Error ping %s: %s", ip, e)
            continue

        if r.returncode == 0:
            pings_ok += 1
            text = _decode_output(r.stdout or b"")
            m = _PING_RTT_RE.search(text)
            if m:
                try:
                    rtts.append(float(m.group(1).replace(",", ".")))
                except ValueError:
                    pass
            elif "ms" in text.lower():
                # Algunas veces el output es "<1ms" (no matchea la regex)
                rtts.append(0.5)

    packet_loss = ((count - pings_ok) / count) * 100 if count > 0 else 100.0
    avg_rtt = (sum(rtts) / len(rtts)) if rtts else None
    is_alive = pings_ok > 0
    return is_alive, avg_rtt, packet_loss


# ============================================================
# TCP
# ============================================================
def _tcp_check(ip: str, port: int, timeout: float = TCP_TIMEOUT_SEC) -> bool:
    """
    Intenta abrir una conexión TCP al puerto indicado.

    Args:
        ip: IP del equipo.
        port: puerto TCP.
        timeout: segundos de espera.

    Returns:
        bool: True si el puerto está abierto (conexión exitosa).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((ip, port)) == 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def _parse_tcp_ports(raw: Optional[str]) -> List[int]:
    """
    Convierte la cadena "161,22,80" en una lista de enteros.

    Args:
        raw: string con puertos separados por coma.

    Returns:
        list: lista de puertos (161 por defecto si no hay ninguno válido).
    """
    if not raw:
        return [161]
    ports = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ports.append(int(chunk))
        except ValueError:
            continue
    return ports or [161]


# ============================================================
# THREAD WORKER
# ============================================================
def _probe_one_device(device) -> Optional[dict]:
    """
    Realiza el probe ICMP + TCP de un solo equipo.

    Se ejecuta en un thread del pool. Cierra conexiones DB del thread
    para evitar problemas con el ORM.

    Args:
        device: instancia de Device.

    Returns:
        dict con el resultado o None si falló completamente.
    """
    close_old_connections()

    try:
        alive, rtt, loss = _icmp_probe(device.ip)
    except Exception as e:
        log.exception("Error ICMP a %s: %s", device.name, e)
        return None

    tcp_results: List[Tuple[int, bool]] = []
    if alive:
        for port in _parse_tcp_ports(device.tcp_ports):
            tcp_results.append((port, _tcp_check(device.ip, port)))

    return {
        "device_id": device.id,
        "name": device.name,
        "ip": device.ip,
        "role": device.device_role,
        "alive": alive,
        "rtt": rtt,
        "loss": loss,
        "tcp": tcp_results,
    }


# ============================================================
# CICLO COMPLETO
# ============================================================
def poll_icmp_tcp(max_workers: int = MAX_WORKERS) -> dict:
    """
    Ciclo ICMP/TCP paralelizado.

    Args:
        max_workers: número máximo de threads concurrentes.

    Returns:
        dict: {devices, alive, down, errors, duration_s}
    """
    start = time.time()
    stats = {"devices": 0, "alive": 0, "down": 0, "errors": 0}

    devices = list(Device.objects.filter(active=True))
    stats["devices"] = len(devices)

    if not devices:
        stats["duration_s"] = round(time.time() - start, 2)
        return stats

    now = _utcnow()
    results: List[dict] = []

    # --- 1. Probes en paralelo ---
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_probe_one_device, d): d for d in devices}
        for fut in concurrent.futures.as_completed(futures):
            try:
                r = fut.result(timeout=30)
                if r:
                    results.append(r)
                else:
                    stats["errors"] += 1
            except concurrent.futures.TimeoutError:
                stats["errors"] += 1
                log.error("Timeout en thread ICMP")
            except Exception as e:
                stats["errors"] += 1
                log.error("Fallo en thread ICMP: %s", e)

    # --- 2. Persistir resultados (secuencial, evita contención en BD) ---
    for r in results:
        try:
            device = Device.objects.get(pk=r["device_id"])
        except Device.DoesNotExist:
            continue

        try:
            influx_writer.write_icmp(
                device_name=device.name,
                ip=device.ip,
                role=device.device_role,
                alive=r["alive"],
                avg_rtt=r["rtt"],
                loss=r["loss"],
                timestamp=now,
            )
        except Exception as e:
            log.error("Error escribiendo ICMP en InfluxDB: %s", e)

        # --- Caído ---
        if not r["alive"]:
            stats["down"] += 1
            log.warning("[%s] %s sin respuesta ICMP", r["name"], r["ip"])
            try:
                alerts.evaluate_metrics(device, {"device_down": 0})
            except Exception as e:
                log.error("[%s] Error evaluando alertas: %s", r["name"], e)
            continue

        # --- Vivo ---
        stats["alive"] += 1
        try:
            alerts.evaluate_metrics(device, {
                "device_down": 1,
                "latency_ms": r["rtt"],
                "packet_loss_pct": r["loss"],
            })
        except Exception as e:
            log.error("[%s] Error evaluando alertas: %s", r["name"], e)

        # --- TCP ---
        opened = []
        for port, is_open in r["tcp"]:
            try:
                influx_writer.write_tcp(
                    device_name=device.name,
                    ip=device.ip,
                    role=device.device_role,
                    port=port,
                    is_open=is_open,
                    timestamp=now,
                )
            except Exception as e:
                log.error("Error escribiendo TCP en InfluxDB: %s", e)
            if is_open:
                opened.append(port)

        log.info(
            "[%s] %s - alive=True rtt=%s loss=%.0f%% tcp=%s",
            r["name"], r["ip"],
            f"{r['rtt']:.1f}ms" if r["rtt"] else "N/A",
            r["loss"], opened or "ninguno",
        )

    stats["duration_s"] = round(time.time() - start, 2)
    return stats