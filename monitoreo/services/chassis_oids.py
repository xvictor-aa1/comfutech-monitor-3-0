# monitoreo/services/chassis_oids.py
"""
Diccionario de OIDs de chasis y de radiofrecuencia por fabricante.

Responsabilidades:
  - Definir los OIDs por defecto de chasis de cada fabricante.
  - Definir los OIDs por defecto de RF de cada fabricante.
  - Exponer helpers para resolver los OIDs efectivos de un equipo,
    priorizando los del modelo sobre los del fabricante.
"""

# ============================================================
# OIDs DE CHASIS POR FABRICANTE
# ============================================================
CHASSIS_OIDS = {
    "cisco": {
        "cpu_pct":  "1.3.6.1.4.1.9.9.109.1.1.1.1.5.1",
        "mem_pct":  "1.3.6.1.4.1.9.9.48.1.1.1.5.1",
        "mem_free": "1.3.6.1.4.1.9.9.48.1.1.1.6.1",
        "temp_c":   "1.3.6.1.4.1.9.9.13.1.3.1.3.1",
    },
    "mikrotik": {
        # CPU: fallback propietario (MikroTik RouterOS 7 suele usar multi-core
        # a través de MIKROTIK_CPU_OIDS, pero se mantiene como red de seguridad).
        "cpu_pct":  "1.3.6.1.4.1.14988.1.1.3.10.0",
        # Memoria: OIDs estándar HOST-RESOURCES.
        "mem_used": "1.3.6.1.2.1.25.2.3.1.6.65536",
        "mem_size": "1.3.6.1.2.1.25.2.3.1.5.65536",
        # Temperatura: índice 1 del health.
        "temp_c":   "1.3.6.1.4.1.14988.1.1.3.100.1.3.14",
        "uptime":   "1.3.6.1.2.1.1.3.0",
    },
    "huawei": {
        "cpu_pct":  "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5.1",
        "mem_pct":  "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7.1",
        "temp_c":   "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11.1",
    },
    "ubiquiti": {
        # airOS 8.x usa FROGFOOT-RESOURCES-MIB (enterprise 10002) para
        # CPU y memoria. Confirmado en airOS 8.7.25 (WA) del LiteAP GPS.
        # Nota: NO hay OID de temperatura disponible (devuelve 0).
        "cpu_pct":   "1.3.6.1.4.1.10002.1.1.1.4.2.1.3.2",    # 5-min load avg
        "mem_total": "1.3.6.1.4.1.10002.1.1.1.1.1.0",        # memoria total (KB)
        "mem_free":  "1.3.6.1.4.1.10002.1.1.1.1.2.0",        # memoria libre (KB)
        "uptime":    "1.3.6.1.2.1.1.3.0",
    },
    "cambium": {
        # Cambium expone CPU pero no memoria/temperatura de forma consistente.
        "cpu_pct":  "1.3.6.1.4.1.17713.21.2.1.64.0",
    },
    "generic": {
        # Solo memoria genérica (HOST-RESOURCES).
        "mem_used": "1.3.6.1.2.1.25.2.3.1.6.1",
        "mem_size": "1.3.6.1.2.1.25.2.3.1.5.1",
    },
}

# OIDs multi-core específicos de MikroTik RouterOS 7
MIKROTIK_CPU_OIDS = [
    "1.3.6.1.2.1.25.3.3.1.2.1",
    "1.3.6.1.2.1.25.3.3.1.2.2",
    "1.3.6.1.2.1.25.3.3.1.2.3",
    "1.3.6.1.2.1.25.3.3.1.2.4",
]

# OIDs comunes a todos los fabricantes
COMMON_OIDS = {
    "uptime": "1.3.6.1.2.1.1.3.0",
}

# ============================================================
# OIDs DE RADIOFRECUENCIA POR FABRICANTE (FALLBACK)
# ============================================================
# Solo se aplican a modelos marcados como `is_wireless_link=True`.
# Los valores exactos pueden variar por firmware; verifica con
# snmpwalk antes de confiar en ellos en producción.
RADIO_OIDS = {
    "ubiquiti": {
        # airMAX AC (AirOS 8) — la mayoría de los LiteAP / LiteBeam
        "radio_freq":      "1.3.6.1.4.1.41112.1.4.1.1.4.1",
        "radio_txpower":   "1.3.6.1.4.1.41112.1.4.1.1.6.1",
        "wl_signal":       "1.3.6.1.4.1.41112.1.4.5.1.5.1",
        "wl_noise_floor":  "1.3.6.1.4.1.41112.1.4.5.1.8.1",
        "wl_ccq":          "1.3.6.1.4.1.41112.1.4.5.1.7.1",
        "wl_tx_rate":      "1.3.6.1.4.1.41112.1.4.5.1.9.1",
        "wl_rx_rate":      "1.3.6.1.4.1.41112.1.4.5.1.10.1",
        "airmax_quality":  "1.3.6.1.4.1.41112.1.4.6.1.4.1",
        "airmax_capacity": "1.3.6.1.4.1.41112.1.4.6.1.5.1",
        "chan_width":      "1.3.6.1.4.1.41112.1.4.5.1.14.1",
    },
    "cambium": {
        "radio_freq":      "1.3.6.1.4.1.17713.21.1.2.1.0",
        "wl_signal":       "1.3.6.1.4.1.17713.21.1.2.6.0",
        "wl_noise_floor":  "1.3.6.1.4.1.17713.21.1.2.7.0",
        "wl_ccq":          "1.3.6.1.4.1.17713.21.1.2.8.0",
    },
    "mimosa": {
        "radio_freq":      "1.3.6.1.4.1.43356.2.1.2.1.1.0",
        "wl_signal":       "1.3.6.1.4.1.43356.2.1.2.7.0",
        "wl_noise_floor":  "1.3.6.1.4.1.43356.2.1.2.8.0",
    },
}


# ============================================================
# HELPERS DE CHASIS
# ============================================================
def get_resolved_oids(device) -> tuple:
    """
    Devuelve los OIDs de chasis efectivos de un equipo y su vendor.

    Prioridad:
      1. OIDs del modelo (`device.device_model.oids`).
      2. OIDs por defecto del fabricante (`CHASSIS_OIDS[vendor]`).

    Args:
        device: instancia de `inventario.models.Device`.

    Returns:
        tuple: (oids_map: dict, vendor: str en minúsculas).
    """
    vendor = (device.vendor or "generic").lower()

    # Priorizar OIDs del modelo si están definidos y no vacíos
    if device.device_model and device.device_model.oids:
        oids_map = dict(device.device_model.oids)
    else:
        oids_map = dict(CHASSIS_OIDS.get(vendor, CHASSIS_OIDS["generic"]))

    # Asegurar que uptime siempre esté presente
    if "uptime" not in oids_map:
        oids_map["uptime"] = COMMON_OIDS["uptime"]

    # Eliminar entradas vacías (None o "")
    oids_map = {k: v for k, v in oids_map.items() if v}

    return oids_map, vendor


def get_available_health_metrics(device) -> list:
    """
    Devuelve las métricas de chasis disponibles para un equipo.

    La disponibilidad se determina por la PRESENCIA de OIDs en el modelo
    o en los defaults del fabricante, NO por el rol del equipo. Esto
    permite que cualquier equipo (incluyendo radio-enlaces) tenga
    monitoreo de CPU/mem/temp si su modelo define los OIDs.

    Args:
        device: instancia de `inventario.models.Device`.

    Returns:
        list: subconjunto de {"cpu_pct", "mem_pct", "temp_c"}.
              Lista vacía si no hay ningún OID definido.
    """
    oids_map, vendor = get_resolved_oids(device)
    available = []

    # --- CPU ---
    # MikroTik: CPU siempre disponible vía MIKROTIK_CPU_OIDS (multi-core)
    if vendor == "mikrotik":
        available.append("cpu_pct")
    elif oids_map.get("cpu_pct"):
        available.append("cpu_pct")

    # --- Memoria ---
    # Se puede calcular si hay mem_pct directo, o mem_used + mem_size/free
    has_mem_pct = bool(oids_map.get("mem_pct"))
    has_mem_used = bool(oids_map.get("mem_used"))
    has_mem_size = bool(oids_map.get("mem_size"))
    has_mem_free = bool(oids_map.get("mem_free"))
    has_mem_total = bool(oids_map.get("mem_total"))

    # Disponible si: mem_pct directo, mem_used+mem_size, mem_total+mem_free,
    # o mem_used+mem_free (fallback).
    if (has_mem_pct
            or (has_mem_used and has_mem_size)
            or (has_mem_total and has_mem_free)
            or (has_mem_used and has_mem_free)):
        available.append("mem_pct")

    # --- Temperatura ---
    if oids_map.get("temp_c"):
        available.append("temp_c")

    return available


def has_meaningful_health_metrics(device) -> bool:
    """
    True si el equipo tiene al menos una métrica de chasis disponible.

    Args:
        device: instancia de `inventario.models.Device`.

    Returns:
        bool: True si hay al menos cpu/mem/temp disponible.
    """
    return len(get_available_health_metrics(device)) > 0


# ============================================================
# HELPERS DE RADIOFRECUENCIA
# ============================================================
def get_radio_oids(device) -> dict:
    """
    Devuelve los OIDs de RF efectivos de un equipo.

    Prioridad:
      1. OIDs del modelo (`device.device_model.radio_oids`).
      2. OIDs por defecto del fabricante (`RADIO_OIDS[vendor]`).

    Args:
        device: instancia de `inventario.models.Device`.

    Returns:
        dict: {clave: oid}. Vacío si el modelo no es wireless.
    """
    if not device.device_model or not device.device_model.is_wireless_link:
        return {}

    if device.device_model.radio_oids:
        return dict(device.device_model.radio_oids)

    vendor = (device.vendor or "").lower()
    return dict(RADIO_OIDS.get(vendor, {}))


def get_available_radio_metrics(device) -> list:
    """
    Devuelve las métricas de RF que se pueden consultar en un equipo.

    Args:
        device: instancia de `inventario.models.Device`.

    Returns:
        list: claves de métricas disponibles (puede ser vacía).
    """
    return list(get_radio_oids(device).keys())


def has_meaningful_radio_metrics(device) -> bool:
    """
    True si el equipo tiene al menos una métrica de RF disponible.

    Args:
        device: instancia de `inventario.models.Device`.

    Returns:
        bool
    """
    return len(get_available_radio_metrics(device)) > 0