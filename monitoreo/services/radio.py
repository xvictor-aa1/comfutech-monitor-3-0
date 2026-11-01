# monitoreo/services/radio.py
"""
Poller de radiofrecuencia (RF) para equipos de radio-enlace.

Solo procesa equipos cuyo `device_model.is_wireless_link == True`.
Lee los OIDs de `device_model.radio_oids` (o el fallback por fabricante
en `chassis_oids.RADIO_OIDS`), escribe a InfluxDB en el measurement
`radio` y evalúa alertas.

Métricas típicas:
  - radio_freq      Frecuencia de operación (MHz)
  - radio_txpower   Potencia de TX (dBm)
  - wl_signal       Nivel de señal (dBm)
  - wl_noise_floor  Piso de ruido (dBm)
  - wl_ccq          Calidad de enlace (%)
  - wl_tx_rate      Tasa de TX (kbps)
  - wl_rx_rate      Tasa de RX (kbps)
  - airmax_quality  Calidad airMAX (%)
  - airmax_capacity Capacidad airMAX (%)
  - chan_width      Ancho de canal (MHz)
"""
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from inventario.models import Device
from . import alerts, influx_writer
from .snmp_client import snmp_get_multiple, to_float, to_int
from .chassis_oids import get_radio_oids

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Hora actual en UTC como datetime naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_radio_metrics(device) -> Dict[str, Optional[float]]:
    """
    Consulta los OIDs de RF del equipo y devuelve un dict con los
    valores procesados.

    Args:
        device: instancia de Device con device_model.is_wireless_link=True.

    Returns:
        dict: valores de RF. Las claves que no respondan serán None.
    """
    oids_map = get_radio_oids(device)
    if not oids_map:
        return {}

    metric_names = list(oids_map.keys())
    oid_list = list(oids_map.values())

    values = snmp_get_multiple(device, oid_list)

    result: Dict[str, Optional[float]] = {}
    for name, val in zip(metric_names, values):
        if name in ("radio_freq", "radio_txpower", "wl_signal",
                     "wl_noise_floor", "wl_ccq", "airmax_quality",
                     "airmax_capacity", "chan_width"):
            result[name] = to_float(val)
        elif name in ("wl_tx_rate", "wl_rx_rate"):
            # Las tasas pueden venir como Integer32 (kbps) o Gauge32.
            result[name] = to_float(val)

    return result


def poll_radio() -> dict:
    """
    Ciclo de polling de radiofrecuencia.

    Itera sobre todos los equipos activos cuyo modelo sea radio-enlace
    y que tengan OIDs de RF definidos (propios o por fabricante).

    Returns:
        dict: {devices, errors, alerts, skipped, duration_s}
    """
    start = time.time()
    stats = {"devices": 0, "errors": 0, "alerts": 0, "skipped": 0, "duration_s": 0.0}

    # Solo equipos activos con modelo wireless.
    devices = (
        Device.objects
        .filter(active=True, device_model__is_wireless_link=True)
        .select_related("device_model")
    )

    now = _utcnow()

    for device in devices:
        oids_map = get_radio_oids(device)
        if not oids_map:
            log.debug(
                "[%s] Sin OIDs de RF para su modelo '%s'. Se omite.",
                device.name,
                device.device_model.name if device.device_model else "—",
            )
            stats["skipped"] += 1
            continue

        stats["devices"] += 1

        try:
            metrics = _get_radio_metrics(device)
        except Exception as e:
            log.exception("Error polling RF de %s: %s", device.name, e)
            stats["errors"] += 1
            continue

        # Escribir a InfluxDB.
        try:
            influx_writer.write_radio(
                device_name=device.name,
                ip=device.ip,
                role=device.device_role,
                vendor=device.vendor,
                metrics=metrics,
                timestamp=now,
            )
        except Exception as e:
            log.error("Error escribiendo radio en InfluxDB: %s", e)

        # Evaluar alertas (métricas de RF).
        try:
            alerts.evaluate_metrics(device, {
                "wl_signal": metrics.get("wl_signal"),
                "wl_noise_floor": metrics.get("wl_noise_floor"),
                "wl_ccq": metrics.get("wl_ccq"),
                "wl_tx_rate": metrics.get("wl_tx_rate"),
                "wl_rx_rate": metrics.get("wl_rx_rate"),
                "airmax_quality": metrics.get("airmax_quality"),
                "airmax_capacity": metrics.get("airmax_capacity"),
                "radio_freq": metrics.get("radio_freq"),
                "radio_txpower": metrics.get("radio_txpower"),
                "chan_width": metrics.get("chan_width"),
            })
        except Exception as e:
            log.exception("Error evaluando alertas RF para %s: %s", device.name, e)

        log.info(
            "[%s] %s [%s] - Freq=%s MHz, TX=%s dBm, Signal=%s dBm, "
            "Noise=%s dBm, CCQ=%s%%, TXrate=%s kbps, RXrate=%s kbps",
            device.name, device.ip, device.device_role,
            f"{metrics['radio_freq']:.0f}" if metrics.get("radio_freq") is not None else "N/A",
            f"{metrics['radio_txpower']:.0f}" if metrics.get("radio_txpower") is not None else "N/A",
            f"{metrics['wl_signal']:.0f}" if metrics.get("wl_signal") is not None else "N/A",
            f"{metrics['wl_noise_floor']:.0f}" if metrics.get("wl_noise_floor") is not None else "N/A",
            f"{metrics['wl_ccq']:.0f}" if metrics.get("wl_ccq") is not None else "N/A",
            f"{metrics['wl_tx_rate']:.0f}" if metrics.get("wl_tx_rate") is not None else "N/A",
            f"{metrics['wl_rx_rate']:.0f}" if metrics.get("wl_rx_rate") is not None else "N/A",
        )

    stats["duration_s"] = round(time.time() - start, 2)
    return stats