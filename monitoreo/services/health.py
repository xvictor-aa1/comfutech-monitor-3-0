# monitoreo/services/health.py
"""
Poller de Core Health: CPU, memoria, temperatura y uptime.

Optimizaciones:
  - Se omite el polling completo si el equipo no tiene NINGUNA métrica
    de chasis disponible (según su modelo o fabricante).
  - Se leen los OIDs resueltos una sola vez.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from inventario.models import Device
from . import alerts, influx_writer
from .snmp_client import snmp_get_multiple, to_float
from .chassis_oids import (
    MIKROTIK_CPU_OIDS,
    get_available_health_metrics,
    get_resolved_oids,
)

log = logging.getLogger(__name__)


# ============================================================
# HELPERS
# ============================================================
def _utcnow() -> datetime:
    """Devuelve la hora actual en UTC como datetime naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================================================
# LECTURA DE MÉTRICAS
# ============================================================
def _get_chassis_metrics(device) -> Dict[str, Optional[float]]:
    """
    Consulta los OIDs de chasis del equipo y devuelve un dict con los
    valores procesados (cpu_pct, mem_pct, temp_c, uptime).

    Args:
        device: instancia de Device.

    Returns:
        dict: valores procesados. Puede faltar alguno si el OID no
              respondió o el modelo no lo tiene.
    """
    oids_map, vendor = get_resolved_oids(device)

    metric_names = list(oids_map.keys())
    oid_list = list(oids_map.values())

    values = snmp_get_multiple(device, oid_list)

    result: Dict[str, Optional[float]] = {}
    for name, val in zip(metric_names, values):
        result[name] = to_float(val)

    # --- CPU MikroTik: promedio multi-core ---
    if vendor == "mikrotik":
        cpu_vals = snmp_get_multiple(device, MIKROTIK_CPU_OIDS)
        cpu_nums = [to_float(v) for v in cpu_vals if v is not None]
        if cpu_nums:
            result["cpu_pct"] = sum(cpu_nums) / len(cpu_nums)
        else:
            # Fallback: si el OID propietario devuelve >100, se divide
            cpu = result.get("cpu_pct")
            if cpu is not None and cpu > 100:
                result["cpu_pct"] = cpu / 100.0
        result.pop("mem_free", None)

    # --- Memoria: derivar mem_pct si no viene directo ---
    if result.get("mem_pct") is None:
        used = result.get("mem_used")
        size = result.get("mem_size")
        free = result.get("mem_free")
        total = result.get("mem_total")

        if used is not None and size and size > 0:
            # Caso clásico: mem_used + mem_size
            result["mem_pct"] = (used / size) * 100.0
        elif total is not None and free is not None and total > 0:
            # Caso Ubiquiti: mem_total + mem_free → used = total - free
            result["mem_pct"] = ((total - free) / total) * 100.0
        elif used is not None and free is not None and (used + free) > 0:
            # Fallback: mem_used + mem_free (cuando used es realmente "usado")
            result["mem_pct"] = (used / (used + free)) * 100.0

    # --- Uptime: TimeTicks (centésimas de segundo) → segundos ---
    if result.get("uptime") is not None:
        result["uptime"] = result["uptime"] / 100.0

    return result


# ============================================================
# CICLO COMPLETO
# ============================================================
def poll_health() -> dict:
    """
    Ciclo de polling de chasis para todos los equipos core/distribution.

    Omite equipos cuyo modelo/fabricante no tengan métricas disponibles.

    Returns:
        dict: estadísticas del ciclo (devices, errors, alerts, skipped, duration_s).
    """
    start = time.time()
    stats = {
        "devices": 0,
        "errors": 0,
        "alerts": 0,
        "skipped": 0,
        "duration_s": 0.0,
    }

    # Antes filtraba por device_role in ("core", "distribution").
    # Ahora filtra solo por active=True y deja que
    # get_available_health_metrics() decida si hay OIDs disponibles.
    devices = Device.objects.filter(
        active=True
    ).select_related("device_model")

    now = _utcnow()

    for device in devices:
        # ¿Tiene métricas disponibles? Si no, saltar
        available = get_available_health_metrics(device)
        if not available:
            log.debug(
                "[%s] Sin OIDs de chasis disponibles para su modelo '%s' "
                "(vendor=%s). Se omite el polling.",
                device.name,
                device.device_model.name if device.device_model else "—",
                device.vendor,
            )
            stats["skipped"] += 1
            continue

        stats["devices"] += 1

        try:
            metrics = _get_chassis_metrics(device)
        except Exception as e:
            log.exception("Error polling chasis de %s: %s", device.name, e)
            stats["errors"] += 1
            continue

        # Escribir a InfluxDB
        try:
            influx_writer.write_health(
                device_name=device.name,
                ip=device.ip,
                role=device.device_role,
                vendor=device.vendor,
                metrics=metrics,
                timestamp=now,
            )
        except Exception as e:
            log.error("Error escribiendo health en InfluxDB: %s", e)

        # Evaluar alertas
        try:
            alerts.evaluate_metrics(device, {
                "cpu_pct": metrics.get("cpu_pct"),
                "mem_pct": metrics.get("mem_pct"),
                "temp_c": metrics.get("temp_c"),
            })
        except Exception as e:
            log.exception("Error evaluando alertas para %s: %s", device.name, e)

        log.info(
            "[%s] %s [%s] - CPU=%s%% MEM=%s%% TEMP=%s°C UPTIME=%s h",
            device.name, device.ip, device.device_role,
            f"{metrics['cpu_pct']:.1f}" if metrics.get("cpu_pct") is not None else "N/A",
            f"{metrics['mem_pct']:.1f}" if metrics.get("mem_pct") is not None else "N/A",
            f"{metrics['temp_c']:.1f}" if metrics.get("temp_c") is not None else "N/A",
            f"{metrics['uptime']/3600:.1f}" if metrics.get("uptime") else "N/A",
        )

    stats["duration_s"] = round(time.time() - start, 2)
    return stats