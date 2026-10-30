# monitoreo/services/discovery.py
"""
Descubrimiento de interfaces SNMP para un equipo.

Características:
  - SNMP walk sobre IF-MIB (ifDescr, ifType, ifSpeed, ifHighSpeed, etc.).
  - Walk parcial: si un OID falla, se continúa con los demás.
  - On duplicate key update: preserva el flag `monitored`.
  - Detección de interfaces huérfanas para eliminarlas.
  - Speed: prioriza ifHighSpeed (Mbps) sobre ifSpeed (bps).
"""
import logging
import time
from typing import Dict, List, Optional

from django.db import transaction

from inventario.models import Device, Interface
from .snmp_client import snmp_walk, to_int, to_str

log = logging.getLogger(__name__)


# ============================================================
# OIDs DEL IF-MIB
# ============================================================
IFACE_OIDS = {
    "if_descr":      "1.3.6.1.2.1.2.2.1.2",
    "if_type":       "1.3.6.1.2.1.2.2.1.3",
    "if_speed":      "1.3.6.1.2.1.2.2.1.5",
    "if_admin":      "1.3.6.1.2.1.2.2.1.7",
    "if_oper":       "1.3.6.1.2.1.2.2.1.8",
    "if_name":       "1.3.6.1.2.1.31.1.1.1.1",
    "if_high_speed": "1.3.6.1.2.1.31.1.1.1.15",
    "if_alias":      "1.3.6.1.2.1.31.1.1.1.18",
}

# Mapeo IANAifType → nombre legible
IF_TYPE_MAP = {
    6:   "ethernet",
    7:   "ethernet-csmacd",
    23:  "ppp",
    24:  "softwareLoopback",
    53:  "propVirtual",
    54:  "propMultiplexor",
    71:  "ieee80211",
    131: "tunnel",
    135: "l2vlan",
    136: "l3ipvlan",
    161: "ieee8023adLag",
}


# ============================================================
# HELPERS
# ============================================================
def _extract_index(oid_str: str, base_oid: str) -> Optional[int]:
    """
    Extrae el ifIndex del sufijo de un OID de columna.

    Ejemplo: base_oid='1.3.6.1.2.1.2.2.1.2', oid_str='1.3.6.1.2.1.2.2.1.2.5'
             → devuelve 5.

    Args:
        oid_str: OID completo retornado por el walk.
        base_oid: OID de la columna.

    Returns:
        int con el ifIndex o None si el sufijo no es válido.
    """
    prefix = base_oid + "."
    if not oid_str.startswith(prefix):
        return None
    try:
        return int(oid_str[len(prefix):].split(".")[0])
    except (ValueError, IndexError):
        return None


def _walk_column(device, col_name: str, base_oid: str) -> Dict[int, object]:
    """
    Ejecuta el walk de una columna y devuelve un mapa {ifIndex: valor}.

    Si el walk falla por completo, devuelve un dict vacío (permite
    que el discovery continúe con las demás columnas).

    Args:
        device: instancia de Device.
        col_name: nombre de la columna (para logs).
        base_oid: OID base de la columna.

    Returns:
        dict: {ifIndex: valor}.
    """
    result: Dict[int, object] = {}
    try:
        pairs = snmp_walk(device, base_oid)
    except Exception as e:
        log.warning(
            "[%s] Walk falló para %s (%s): %s",
            device.name, col_name, base_oid, e,
        )
        return result

    for oid_str, val in pairs:
        idx = _extract_index(oid_str, base_oid)
        if idx is not None:
            result[idx] = val

    log.debug("[%s] %s: %d entradas", device.name, col_name, len(result))
    return result


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================
def discover_interfaces(device: Device) -> dict:
    """
    Descubre las interfaces de un equipo vía SNMP walk.

    Si el modelo del equipo tiene `has_interfaces=False`, se devuelve
    un resultado vacío inmediatamente (sin hacer walk SNMP).

    Pasos:
      1. Walk de cada columna IF-MIB.
      2. Unión de todos los ifIndex encontrados.
      3. Persistencia (upsert) preservando `monitored`.
      4. Eliminación de interfaces que ya no existen.

    Args:
        device: instancia de Device.

    Returns:
        dict con el resultado:
          {
            "success": bool,
            "interfaces_found": int,
            "interfaces_up": int,
            "created": int,
            "updated": int,
            "deleted": int,
            "error": str | None,
          }
    """
    result = {
        "success": False,
        "interfaces_found": 0,
        "interfaces_up": 0,
        "created": 0,
        "updated": 0,
        "deleted": 0,
        "error": None,
    }

    # --- Skip si el modelo no tiene interfaces ---
    if device.device_model and not device.device_model.has_interfaces:
        result["success"] = True
        result["error"] = None
        log.info(
            "[%s] Discovery omitido: el modelo '%s' no tiene interfaces SNMP.",
            device.name, device.device_model.name,
        )
        return result

    try:
        # --- 1. Walk de cada columna ---
        columns: Dict[str, Dict[int, object]] = {}
        for col_name, base_oid in IFACE_OIDS.items():
            columns[col_name] = _walk_column(device, col_name, base_oid)

        # --- 2. Unión de todos los ifIndex ---
        all_indexes = set()
        for col_map in columns.values():
            all_indexes.update(col_map.keys())

        if not all_indexes:
            result["error"] = "No se detectaron interfaces vía SNMP."
            return result

        # --- 3. Construir la lista de interfaces ---
        interfaces_data: List[dict] = []

        for idx in sorted(all_indexes):
            descr = columns["if_descr"].get(idx)
            name = columns["if_name"].get(idx) or descr
            alias = columns["if_alias"].get(idx)
            itype = to_int(columns["if_type"].get(idx))
            speed = to_int(columns["if_speed"].get(idx))
            hspeed = to_int(columns["if_high_speed"].get(idx))
            admin = to_int(columns["if_admin"].get(idx))
            oper = to_int(columns["if_oper"].get(idx))

            # Velocidad: priorizar ifHighSpeed (Mbps) sobre ifSpeed (bps)
            if hspeed and hspeed > 0:
                speed_bps = hspeed * 1_000_000
            elif speed and speed > 0:
                speed_bps = speed
            else:
                speed_bps = None

            interfaces_data.append({
                "if_index": idx,
                "if_name": to_str(name)[:100] if name is not None else None,
                "if_alias": to_str(alias)[:100] if alias is not None else None,
                "if_speed_bps": speed_bps,
                "if_type": IF_TYPE_MAP.get(itype, f"type{itype or 0}"),
                "admin_status": admin == 1,
                "oper_status": oper == 1,
            })

        result["interfaces_found"] = len(interfaces_data)
        result["interfaces_up"] = sum(
            1 for i in interfaces_data if i["oper_status"]
        )

        # --- 4. Persistencia ---
        with transaction.atomic():
            current_indexes = {i["if_index"] for i in interfaces_data}

            # Pre-cargar las existentes para preservar `monitored`
            existing = {
                iface.if_index: iface
                for iface in Interface.objects.filter(device=device)
            }

            for data in interfaces_data:
                iface = existing.get(data["if_index"])
                if iface:
                    # Actualizar campos del walk (NO `monitored`)
                    iface.if_name = data["if_name"]
                    iface.if_alias = data["if_alias"]
                    iface.if_speed_bps = data["if_speed_bps"]
                    iface.if_type = data["if_type"]
                    iface.admin_status = data["admin_status"]
                    iface.oper_status = data["oper_status"]
                    iface.save()
                    result["updated"] += 1
                else:
                    # Crear nueva, monitored=False por defecto
                    Interface.objects.create(
                        device=device,
                        monitored=False,
                        **data,
                    )
                    result["created"] += 1

            # Eliminar interfaces que ya no existen
            deleted_qs = Interface.objects.filter(
                device=device
            ).exclude(
                if_index__in=current_indexes
            )
            deleted_count = deleted_qs.count()
            if deleted_count > 0:
                deleted_qs.delete()
                result["deleted"] = deleted_count

        result["success"] = True

        log.info(
            "Discovery OK: %s (%s) — %d interfaces (%d up), "
            "%d nuevas, %d actualizadas, %d eliminadas",
            device.name, device.ip,
            result["interfaces_found"], result["interfaces_up"],
            result["created"], result["updated"], result["deleted"],
        )
    except Exception as e:
        log.exception("Error en discovery de %s: %s", device.name, e)
        result["error"] = str(e)

    return result