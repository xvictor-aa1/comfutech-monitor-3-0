# monitoreo/services/traffic.py
"""
Poller SNMP de tráfico por interfaz.

Características:
  - Contadores de 64 bits (ifHCInOctets / ifHCOutOctets) con fallback
    a 32 bits.
  - Detección de counter reset (reboot del dispositivo) y wrap (32-bit).
  - Cache de contadores previos en memoria por (device, if_index).
  - Cálculo de utilización con sanity check (>500% se descarta).
  - Solo procesa interfaces con `monitored=True` y `oper_status=True`.
  - La evaluación de alertas se realiza una sola vez por device y
    ciclo, enviando el máximo de utilización, in_bps y out_bps entre
    todas las interfaces monitoreadas.
  - Limpieza periódica de contadores huérfanos mediante
    `cleanup_stale_counters()`, invocada desde el heartbeat del
    scheduler.
"""
import logging
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, Optional, Tuple

from inventario.models import Device
from . import alerts, influx_writer
from .snmp_client import snmp_get_multiple, to_int

log = logging.getLogger(__name__)


# ============================================================
# ESTADO GLOBAL
# ============================================================
# Cache de contadores: {(device_id, if_index): (in_octets, out_octets, ts)}
_prev_counters: Dict[Tuple[int, int], Tuple[int, int, datetime]] = {}
_prev_lock = Lock()

# Set de interfaces ya advertidas por "utilización absurda"
_warned_absurd_util = set()


# ============================================================
# HELPERS
# ============================================================
def _utcnow() -> datetime:
    """Hora actual en UTC como datetime naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_interface_counters(device, if_index: int) -> Tuple[Optional[int], Optional[int]]:
    """
    Lee los contadores de una interfaz (in_octets, out_octets).

    Intenta primero contadores de 64 bits (HC) y hace fallback a 32
    bits si no hay respuesta.

    Args:
        device: instancia de Device.
        if_index: índice SNMP de la interfaz.

    Returns:
        tuple: (in_octets, out_octets), cualquiera puede ser None.
    """
    # --- Contadores de 64 bits ---
    oids_64 = [
        f"1.3.6.1.2.1.31.1.1.1.6.{if_index}",   # ifHCInOctets
        f"1.3.6.1.2.1.31.1.1.1.10.{if_index}",  # ifHCOutOctets
    ]
    values = snmp_get_multiple(device, oids_64)
    in64, out64 = to_int(values[0]), to_int(values[1])

    if in64 is not None and out64 is not None:
        return in64, out64

    # --- Fallback a 32 bits ---
    oids_32 = [
        f"1.3.6.1.2.1.2.2.1.10.{if_index}",   # ifInOctets
        f"1.3.6.1.2.1.2.2.1.16.{if_index}",   # ifOutOctets
    ]
    values = snmp_get_multiple(device, oids_32)
    return to_int(values[0]), to_int(values[1])


def _delta_with_reset_detection(
    prev: Optional[int],
    curr: Optional[int],
    bits: int = 64,
) -> Optional[int]:
    """
    Calcula el delta entre dos contadores detectando reset y wrap.

    Lógica:
      - Si prev o curr son None → None.
      - Si curr < prev:
          · Para 64 bits: es un reset (reboot). Delta = curr.
          · Para 32 bits: puede ser wrap o reset. Se asume wrap
            (más común) → delta = curr + (2^32 - prev).
      - Resto: delta = curr - prev.

    Args:
        prev: valor anterior.
        curr: valor actual.
        bits: 64 (contadores HC) o 32 (contadores clásicos).

    Returns:
        int con el delta positivo, o None.
    """
    if prev is None or curr is None:
        return None

    if curr >= prev:
        return curr - prev

    # curr < prev
    if bits == 64:
        # Contadores de 64 bits: imposible wrap práctico → reset
        return curr
    # Contadores de 32 bits: asumir wrap
    return curr + (2 ** 32 - prev)


def _calculate_bps(
    prev_in: Optional[int],
    prev_out: Optional[int],
    curr_in: Optional[int],
    curr_out: Optional[int],
    elapsed: float,
    bits: int = 64,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Calcula los bps de entrada y salida a partir de los deltas.

    Args:
        prev_in, prev_out, curr_in, curr_out: contadores.
        elapsed: segundos transcurridos.
        bits: 64 o 32 según el tipo de contador.

    Returns:
        tuple: (in_bps, out_bps).
    """
    if elapsed <= 0:
        return None, None

    d_in = _delta_with_reset_detection(prev_in, curr_in, bits=bits)
    d_out = _delta_with_reset_detection(prev_out, curr_out, bits=bits)

    in_bps = (d_in * 8) / elapsed if d_in is not None else None
    out_bps = (d_out * 8) / elapsed if d_out is not None else None
    return in_bps, out_bps


# ============================================================
# LIMPIEZA DE CONTADORES HUÉRFANOS
# ============================================================
def cleanup_stale_counters(max_age_sec: int = 86400) -> int:
    """
    Elimina entradas de `_prev_counters` con más de `max_age_sec`
    sin actualizarse.

    Se llama periódicamente desde el heartbeat del scheduler para
    liberar memoria cuando se eliminan equipos o interfaces.

    Args:
        max_age_sec: antigüedad máxima en segundos (default 24h).

    Returns:
        int: número de entradas eliminadas.
    """
    now = _utcnow()
    removed = 0
    with _prev_lock:
        stale_keys = [
            k for k, (_, _, ts) in _prev_counters.items()
            if (now - ts).total_seconds() > max_age_sec
        ]
        for k in stale_keys:
            del _prev_counters[k]
            removed += 1
    if removed:
        log.debug("Limpiados %d contadores de tráfico huérfanos.", removed)
    return removed


# ============================================================
# CICLO COMPLETO
# ============================================================
def poll_traffic() -> dict:
    """
    Ciclo de polling de tráfico SNMP.

    Itera sobre todas las interfaces con `monitored=True` y
    `oper_status=True`, lee los contadores, calcula bps y utilización,
    escribe a InfluxDB (buffer) y evalúa alertas una vez por device
    con el máximo de cada métrica entre sus interfaces.

    Returns:
        dict: {devices, interfaces, alerts, errors, duration_s}
    """
    start = time.time()
    stats = {"devices": 0, "interfaces": 0, "alerts": 0, "errors": 0}

    devices = (
        Device.objects
        .filter(active=True)
        .prefetch_related("interfaces")
    )
    now = _utcnow()

    for device in devices:
        # Filtrar interfaces monitoreadas y operativas.
        interfaces = [
            i for i in device.interfaces.all()
            if i.monitored and i.oper_status
        ]
        if not interfaces:
            continue

        stats["devices"] += 1

        # Acumuladores para el motor de alertas: máximo de cada métrica
        # entre todas las interfaces monitoreadas del equipo.
        max_util: Optional[float] = None
        max_in_bps: Optional[float] = None
        max_out_bps: Optional[float] = None

        for iface in interfaces:
            try:
                curr_in, curr_out = _get_interface_counters(device, iface.if_index)

                if curr_in is None or curr_out is None:
                    log.debug(
                        "[%s] Sin respuesta SNMP en if%d",
                        device.name, iface.if_index,
                    )
                    stats["errors"] += 1
                    continue

                # Leer contadores previos del cache.
                cache_key = (device.id, iface.if_index)
                with _prev_lock:
                    prev = _prev_counters.get(cache_key)

                if prev:
                    prev_in, prev_out, prev_time = prev
                    elapsed = (now - prev_time).total_seconds()
                else:
                    prev_in = prev_out = None
                    elapsed = 60.0  # asumir ciclo estándar en el primer intento

                # Calcular bps.
                in_bps, out_bps = _calculate_bps(
                    prev_in, prev_out, curr_in, curr_out, elapsed, bits=64,
                )

                # Actualizar cache.
                with _prev_lock:
                    _prev_counters[cache_key] = (curr_in, curr_out, now)

                # Calcular utilización.
                util = None
                if iface.if_speed_bps and iface.if_speed_bps > 0:
                    candidates = []
                    if in_bps is not None:
                        candidates.append((in_bps / iface.if_speed_bps) * 100)
                    if out_bps is not None:
                        candidates.append((out_bps / iface.if_speed_bps) * 100)
                    if candidates:
                        util = max(candidates)

                    # Sanity check: advertir una sola vez por interfaz.
                    if util is not None and util > 500.0:
                        if iface.id not in _warned_absurd_util:
                            log.warning(
                                "[%s] if%d: utilización absurda (%.1f%%) — "
                                "verifica if_speed_bps en la BD (%s bps).",
                                device.name, iface.if_index, util,
                                iface.if_speed_bps,
                            )
                            _warned_absurd_util.add(iface.id)
                        util = None

                # Acumular máximos para el motor de alertas.
                if util is not None:
                    if max_util is None or util > max_util:
                        max_util = util
                if in_bps is not None:
                    if max_in_bps is None or in_bps > max_in_bps:
                        max_in_bps = in_bps
                if out_bps is not None:
                    if max_out_bps is None or out_bps > max_out_bps:
                        max_out_bps = out_bps

                # Escribir a InfluxDB (acumula en buffer; se envía al final).
                if in_bps is not None or out_bps is not None:
                    influx_writer.write_traffic(
                        device_name=device.name,
                        ip=device.ip,
                        if_index=iface.if_index,
                        if_name=iface.if_name,
                        role=device.device_role,
                        capacity_bps=iface.if_speed_bps,
                        in_bps=in_bps,
                        out_bps=out_bps,
                        utilization=util,
                        rx_octets=curr_in,
                        tx_octets=curr_out,
                        timestamp=now,
                    )
                    stats["interfaces"] += 1

                log.info(
                    "%s if%d [%s]: cap=%s Mbps in=%.2f out=%.2f util=%s%%",
                    device.name, iface.if_index, device.device_role,
                    f"{iface.speed_mbps}" if iface.speed_mbps else "N/A",
                    (in_bps / 1e6) if in_bps else 0,
                    (out_bps / 1e6) if out_bps else 0,
                    f"{util:.1f}" if util is not None else "N/A",
                )

            except Exception as e:
                log.exception(
                    "[%s] Error procesando if%d: %s",
                    device.name, iface.if_index, e,
                )
                stats["errors"] += 1

        # Evaluar alertas una sola vez por device y ciclo, con las
        # 3 métricas de tráfico (máximo entre interfaces).
        if max_util is not None or max_in_bps is not None or max_out_bps is not None:
            try:
                alerts.evaluate_metrics(device, {
                    "utilization_pct": max_util,
                    "in_bps": max_in_bps,
                    "out_bps": max_out_bps,
                })
                stats["alerts"] += 1
            except Exception as e:
                log.error(
                    "[%s] Error evaluando alertas de tráfico: %s",
                    device.name, e,
                )

    stats["duration_s"] = round(time.time() - start, 2)
    return stats