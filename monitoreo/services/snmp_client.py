# monitoreo/services/snmp_client.py
"""
Cliente SNMP para PySNMP 7.x.

Características:
  - API asíncrona de pysnmp 7.x con wrapper síncrono por thread.
  - Event loop por thread (evita conflictos en APScheduler).
  - Construcción de autenticación según versión SNMP (1, 2c, 3).
  - Conversión robusta de tipos SNMP (Integer32, Counter64, Gauge32, TimeTicks).
  - Soporte de GET (múltiples OIDs) y WALK (bulk).
"""
import asyncio
import logging
import threading
from typing import List, Optional, Tuple

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine,
    CommunityData,
    UsmUserData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    get_cmd,
    bulk_cmd,
)

# Fallback de tipos especiales
try:
    from pysnmp.proto.rfc1905 import NoSuchInstance, NoSuchObject
except ImportError:
    NoSuchInstance = type("NoSuchInstance", (), {})
    NoSuchObject = type("NoSuchObject", (), {})

log = logging.getLogger(__name__)


# ============================================================
# CONFIGURACIÓN
# ============================================================
SNMP_TIMEOUT = 3        # segundos por intento
SNMP_RETRIES = 1        # reintentos por consulta
MAX_REPETITIONS = 25    # OIDs por respuesta en bulk walk
MAX_RESULTS = 1024      # límite de seguridad para walk


# ============================================================
# EVENT LOOP POR THREAD
# ============================================================
# APScheduler ejecuta jobs en threads distintos. Cada thread debe tener
# su propio event loop porque asyncio no permite dos loops en el mismo
# thread al mismo tiempo.
_loop_local = threading.local()


def _get_loop() -> asyncio.AbstractEventLoop:
    """
    Devuelve (o crea) el event loop del thread actual.

    Si el thread ya tiene un loop activo, se reutiliza. Si no, se crea
    uno nuevo y se guarda en thread-local storage.

    Returns:
        asyncio.AbstractEventLoop: el loop listo para usar.
    """
    loop = getattr(_loop_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _loop_local.loop = loop
    return loop


def _run_async(coro):
    """
    Ejecuta una coroutine en el loop del thread actual.

    Si el loop ya está corriendo (raro pero posible), lanza RuntimeError.
    En ese caso el caller debe gestionar el resultado desde otro contexto.

    Args:
        coro: coroutine a ejecutar.

    Returns:
        El resultado de la coroutine.
    """
    loop = _get_loop()
    if loop.is_running():
        # Estamos dentro de un loop ya corriendo → crear tarea nueva
        # Esto NO debería pasar en el scheduler estándar
        raise RuntimeError(
            "El event loop del thread ya está corriendo. "
            "Llamar esta función desde código síncrono."
        )
    return loop.run_until_complete(coro)


# ============================================================
# AUTENTICACIÓN
# ============================================================
def _build_auth(device):
    """
    Construye el objeto de autenticación según la versión SNMP.

    Args:
        device: instancia de inventario.models.Device con los campos
                snmp_version, snmp_community, snmp_user, snmp_auth, snmp_priv.

    Returns:
        Tupla de (auth_object, is_v3).
    """
    snmp_version = (device.snmp_version or "2c").lower().strip()

    # --- SNMPv3 ---
    if snmp_version == "3":
        if not device.snmp_user:
            raise ValueError(
                f"Equipo {device.name}: SNMPv3 requiere snmp_user."
            )
        auth = UsmUserData(
            device.snmp_user,
            authKey=device.snmp_auth or None,
            privKey=device.snmp_priv or None,
        )
        return auth, True

    # --- SNMPv1 / v2c ---
    community = device.snmp_community or "public"
    mpModel = 0 if snmp_version == "1" else 1  # 0=v1, 1=v2c
    return CommunityData(community, mpModel=mpModel), False


def _build_transport_async(ip: str):
    """
    Construye el transporte UDP asíncrono hacia un IP.

    Args:
        ip: dirección IP del equipo.

    Returns:
        coroutine que resuelve a UdpTransportTarget.
    """
    return UdpTransportTarget.create(
        (ip, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES
    )


# ============================================================
# GET MÚLTIPLE
# ============================================================
async def _snmp_get_async(device, oids: List[str]) -> List[Optional[object]]:
    """
    Ejecuta un GET SNMP con múltiples OIDs en una sola PDU.

    Args:
        device: instancia de Device.
        oids: lista de strings OID a consultar.

    Returns:
        list: valores en el mismo orden que `oids`, con `None` donde no
              hubo respuesta o no exista el OID.
    """
    if not oids:
        return []

    try:
        auth, _ = _build_auth(device)
    except ValueError as e:
        log.error("%s", e)
        return [None] * len(oids)

    try:
        transport = await _build_transport_async(device.ip)
    except Exception as e:
        log.debug("Error creando transporte SNMP %s: %s", device.ip, e)
        return [None] * len(oids)

    try:
        errInd, errStat, errIdx, varBinds = await get_cmd(
            SnmpEngine(),
            auth,
            transport,
            ContextData(),
            *[ObjectType(ObjectIdentity(o)) for o in oids],
        )
    except Exception as e:
        log.debug("Excepción SNMP GET %s: %s", device.ip, e)
        return [None] * len(oids)

    if errInd or errStat:
        log.debug(
            "SNMP GET fallo %s: %s / %s",
            device.ip,
            errInd,
            errStat.prettyPrint() if hasattr(errStat, "prettyPrint") else errStat,
        )
        return [None] * len(oids)

    result: List[Optional[object]] = []
    for vb in varBinds:
        val = vb[1]
        if isinstance(val, (NoSuchInstance, NoSuchObject)):
            result.append(None)
        else:
            result.append(val)
    return result


def snmp_get_multiple(device, oids: List[str]) -> List[Optional[object]]:
    """
    Wrapper síncrono de `_snmp_get_async`.

    Args:
        device: instancia de Device.
        oids: lista de OIDs.

    Returns:
        list: valores correspondientes (o `None`).
    """
    try:
        return _run_async(_snmp_get_async(device, oids))
    except Exception as e:
        log.error("Error ejecutando GET SNMP en %s: %s", device.ip, e)
        return [None] * len(oids)


# ============================================================
# WALK
# ============================================================
async def _snmp_walk_async(device, base_oid: str) -> List[Tuple[str, object]]:
    """
    Recorre un subárbol SNMP con GETBULK (o GETNEXT como fallback).

    Args:
        device: instancia de Device.
        base_oid: OID raíz del subárbol a recorrer.

    Returns:
        list: pares (oid_str, valor) encontrados dentro del subárbol.
    """
    try:
        auth, _ = _build_auth(device)
    except ValueError as e:
        log.error("%s", e)
        return []

    try:
        transport = await _build_transport_async(device.ip)
    except Exception as e:
        log.debug("Error creando transporte SNMP %s: %s", device.ip, e)
        return []

    engine = SnmpEngine()
    context = ContextData()

    results: List[Tuple[str, object]] = []
    current_oid = base_oid
    prefix = base_oid + "."

    while True:
        try:
            errInd, errStat, errIdx, varBinds = await bulk_cmd(
                engine,
                auth,
                transport,
                context,
                0,
                MAX_REPETITIONS,
                ObjectType(ObjectIdentity(current_oid)),
            )
        except Exception as e:
            log.debug("Excepción SNMP WALK %s %s: %s", device.ip, base_oid, e)
            break

        if errInd or errStat or not varBinds:
            break

        end = False
        for vb in varBinds:
            oid_str = str(vb[0])
            if not oid_str.startswith(prefix):
                end = True
                break
            if isinstance(vb[1], (NoSuchInstance, NoSuchObject)):
                continue
            results.append((oid_str, vb[1]))
            current_oid = oid_str
            if len(results) >= MAX_RESULTS:
                end = True
                break

        if end:
            break

    return results


def snmp_walk(device, base_oid: str) -> List[Tuple[str, object]]:
    """
    Wrapper síncrono de `_snmp_walk_async`.

    Args:
        device: instancia de Device.
        base_oid: OID raíz.

    Returns:
        list: pares (oid_str, valor).
    """
    try:
        return _run_async(_snmp_walk_async(device, base_oid))
    except Exception as e:
        log.error("Error ejecutando WALK SNMP en %s: %s", device.ip, e)
        return []


# ============================================================
# CONVERSIÓN DE TIPOS
# ============================================================
def to_int(value) -> Optional[int]:
    """
    Convierte un valor SNMP a int de forma segura.

    Soporta Integer32, Counter32, Counter64, Gauge32, strings numéricos
    y objetos con `.prettyPrint()`.

    Args:
        value: valor SNMP o None.

    Returns:
        int o None si no se puede convertir.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        pass
    # Fallback para objetos que solo exponen prettyPrint
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return None


def to_float(value) -> Optional[float]:
    """
    Convierte un valor SNMP a float de forma segura.

    Args:
        value: valor SNMP o None.

    Returns:
        float o None si no se puede convertir.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        pass
    try:
        return float(str(value))
    except (ValueError, TypeError):
        return None


def to_str(value) -> Optional[str]:
    """
    Convierte un valor SNMP a string de forma segura.

    Args:
        value: valor SNMP o None.

    Returns:
        str o None.
    """
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="ignore")
        except Exception:
            return None
    try:
        return str(value)
    except Exception:
        return None