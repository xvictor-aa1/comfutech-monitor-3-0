# core/config_ini.py
""""
Gestión del archivo `config.toml` — configuración runtime.

Responsabilidades:
  - Leer el .toml con Dynaconf (cache en memoria, reload por mtime).
  - Escribir el .toml de forma atómica con tomlkit (preserva comentarios
    y orden).
  - Crear backup automático (.toml.bak) antes de cada escritura.
  - Restringir permisos del archivo (0600 en sistemas Unix).
  - Migrar automáticamente `config.ini` legacy → `config.toml` si existe.
  - Exponer helpers tipados (`get_section()`).

Formato TOML vs INI:
  TOML maneja nativamente caracteres que rompen INI:
    - `#` dentro de un valor (TOML: literal dentro de comillas).
    - `=` dentro de un valor (TOML: literal dentro de comillas).
    - Espacios en contraseñas (TOML: literal dentro de comillas).
    - Valores que terminan en `==` (base64 / tokens InfluxDB).
  Ver `config.toml.example` para ejemplos.

Seguridad:
  - El archivo es texto plano en disco. La protección depende de los
    permisos del sistema de archivos (modo 0600).
  - Si se requiere cifrado real, añadir una capa de encrypt/decrypt
    con una master key fuera del .toml.
"""
import configparser
import logging
import os
import shutil
import tempfile
import threading
import time
import tomllib  # stdlib Python 3.11+
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import tomlkit
from django.conf import settings
from dynaconf import Dynaconf

log = logging.getLogger(__name__)

# ============================================================
# RUTAS
# ============================================================
CONFIG_PATH: Path = Path(
    getattr(settings, "COMFUTECH_CONFIG_FILE", settings.BASE_DIR / "config.toml")
)

# Ruta del archivo INI legacy (para migración automática)
LEGACY_INI_PATH: Path = CONFIG_PATH.with_suffix(".ini")

# ============================================================
# ESTADO GLOBAL
# ============================================================
_lock = threading.RLock()
_last_mtime: float = 0.0

# ============================================================
# DYNACONF — lectura
# ============================================================
_settings = Dynaconf(
    settings_files=[str(CONFIG_PATH)],
    environments=False,
    load_dotenv=False,
    env_switcher="ENV_FOR_DYNACONF",
    envvar_prefix="COMFUTECH",   # COMFUTECH_INFLUXDB__TOKEN puede sobrescribir
    merge_enabled=True,
)


# ============================================================
# ESTRUCTURA POR DEFECTO
# ============================================================
def _default_structure() -> dict:
    """Devuelve la estructura por defecto del config.toml."""
    return {
        "influxdb": {
            "url": "http://localhost:8086",
            "token": "",
            "org": "comfutech",
            "bucket": "metricas_red",
        },
        "grafana": {"url": "http://localhost:3000"},
        "telegram": {
            "enabled": False,
            "bot_token": "",
            "chat_id": "",
        },
        "monitor": {
            "enabled": True,
            "snmp_poll_interval": 60,
            "health_poll_interval": 120,
            "icmp_poll_interval": 120,
            "radio_poll_interval": 120,
            "ap_clients_poll_interval": 120,
        },
        "email": {
            "host": "smtp.gmail.com",
            "port": 587,
            "use_tls": True,
            "use_ssl": False,
            "host_user": "",
            "host_password": "",
            "default_from": "Comfutech Monitor <noreply@comfutech.local>",
        },
        "maintenance": {
            "auto_backup_enabled": False,
            "backup_time": "03:00",
            "backup_on_startup": False,
            "backup_db": True,
            "backup_config": True,
            "retention_days": 30,
            "dump_tool_path": "",
        },
        "_meta": {
            "updated_at": "",
            "updated_by": "",
            "last_backup_run": "",
            "last_backup_type": "",
            "last_backup_filename": "",
        },
    }


_HEADER_COMMENT = (
    "============================================================\n"
    "config.toml — Configuración runtime de Comfutech Monitor\n"
    "============================================================\n"
    "Este archivo contiene credenciales. NO lo versiones.\n"
    "Editable desde /configuracion/ o manualmente.\n"
    "Los cambios se aplican en ≤60s (heartbeat del monitor).\n"
    "============================================================"
)


# ============================================================
# MIGRACIÓN INI → TOML
# ============================================================
def _migrate_from_ini_if_needed() -> bool:
    """
    Si existe `config.ini` legacy y no existe `config.toml`, migra los
    datos preservándolos todos.

    El archivo `.ini` original se renombra a `.ini.bak` para auditoría.

    Returns:
        bool: True si se migró algo.
    """
    if CONFIG_PATH.exists():
        return False
    if not LEGACY_INI_PATH.exists():
        return False

    log.info("Migrando %s → %s", LEGACY_INI_PATH, CONFIG_PATH)

    parser = configparser.ConfigParser()
    try:
        parser.read(LEGACY_INI_PATH, encoding="utf-8")
    except Exception as e:
        log.error("Error leyendo %s: %s", LEGACY_INI_PATH, e)
        return False

    # Construir estructura
    data: dict = {}
    for section in parser.sections():
        data[section] = {}
        for key, value in parser.items(section):
            data[section][key] = _coerce_str(value)

    # Rellenar defaults para secciones faltantes
    defaults = _default_structure()
    for section, defaults_section in defaults.items():
        if section not in data:
            data[section] = defaults_section
        else:
            for k, v in defaults_section.items():
                data[section].setdefault(k, v)

    try:
        _write_toml_atomic(data)
        # Backup del INI original
        backup = LEGACY_INI_PATH.with_suffix(".ini.bak")
        try:
            shutil.move(str(LEGACY_INI_PATH), str(backup))
        except Exception as e:
            log.warning("No se pudo renombrar %s: %s", LEGACY_INI_PATH, e)
        log.info("Migración INI → TOML completada. Backup en %s", backup)
        return True
    except Exception as e:
        log.error("Error escribiendo TOML durante migración: %s", e)
        return False


def _coerce_str(value: Any) -> str:
    """Convierte valores INI (siempre str) a str limpio."""
    return "" if value is None else str(value)


# ============================================================
# HELPERS INTERNOS
# ============================================================
def _ensure_file_exists() -> None:
    """Crea el archivo con valores por defecto si no existe (con header)."""
    if CONFIG_PATH.exists():
        return

    # Intentar migrar desde .ini primero
    if _migrate_from_ini_if_needed():
        _apply_file_permissions()
        return

    # Crear desde cero
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = _default_structure()
    _write_toml_atomic(data)
    _apply_file_permissions()
    log.info("config.toml creado con valores por defecto: %s", CONFIG_PATH)


def _apply_file_permissions() -> None:
    """
    Restringe los permisos del archivo.

    Unix: 0600 (solo el propietario lee y escribe).
    Windows: mejor esfuerzo (el usuario debe verificar la ACL).
    """
    try:
        if os.name == "posix":
            os.chmod(CONFIG_PATH, 0o600)
        # En Windows no hay un equivalente directo portable sin pywin32.
        # Recomendación documentada: icacls.
    except Exception as e:
        log.warning("No se pudieron ajustar permisos de %s: %s", CONFIG_PATH, e)


def _reload_dynaconf() -> None:
    """Fuerza a Dynaconf a re-leer el archivo."""
    try:
        _settings.reload()
    except Exception as e:
        log.error("Error recargando Dynaconf: %s", e)


def _get_mtime() -> float:
    """Devuelve el mtime del archivo (0 si no existe)."""
    try:
        return CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def reload_if_changed() -> bool:
    """
    Recarga Dynaconf solo si el archivo cambió desde la última lectura.

    Uso típico: llamar al inicio de cada ciclo del monitor (heartbeat).

    Returns:
        bool: True si se recargó (el archivo cambió).
    """
    global _last_mtime
    mtime = _get_mtime()
    if mtime <= _last_mtime:
        return False
    with _lock:
        _last_mtime = mtime
    _reload_dynaconf()
    log.info("config.toml recargado (mtime=%.3f)", mtime)
    return True


# ============================================================
# ESCRITURA ATÓMICA CON TOMLKIT
# ============================================================
def _to_toml_value(value: Any) -> Any:
    """
    Convierte un valor Python a un tipo serializable por tomlkit.

    Estrategia:
      - None → ""
      - bool → bool (nativo TOML)
      - int/float → nativo
      - str → str (tomlkit lo escribe entre comillas dobles)
      - list/dict → recursivo
      - cualquier otra cosa → str()
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_to_toml_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_toml_value(v) for k, v in value.items()}
    return str(value)


def _write_toml_atomic(data: dict) -> None:
    """
    Escribe `data` en el .toml de forma atómica.

    Preserva comentarios y estructura del archivo existente (vía tomlkit).

    Args:
        data: dict con la estructura completa a escribir. Las secciones
              no presentes se conservan si el archivo ya existía.
    """
    # Leer el archivo actual (si existe) para preservar comentarios
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                doc = tomlkit.parse(f.read())
        except Exception as e:
            log.warning(
                "No se pudo parsear %s (%s), se sobreescribirá",
                CONFIG_PATH, e,
            )
            doc = tomlkit.document()
    else:
        doc = tomlkit.document()

    # Añadir header si es archivo nuevo
    if not CONFIG_PATH.exists():
        for line in _HEADER_COMMENT.splitlines():
            doc.add(tomlkit.comment(line))
        doc.add(tomlkit.nl())

    # Merge recursivo de secciones
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        if section not in doc:
            doc[section] = tomlkit.table()
        for k, v in values.items():
            doc[section][k] = _to_toml_value(v)

    # Metadata
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if "_meta" not in doc:
        doc["_meta"] = tomlkit.table()
    doc["_meta"]["updated_at"] = now_iso
    # `updated_by` se añade después en write_sections

    # Escritura atómica: temp + replace
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".config_", suffix=".toml", dir=str(CONFIG_PATH.parent)
    )
    os.close(tmp_fd)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(tomlkit.dumps(doc))
        os.replace(tmp_path, CONFIG_PATH)  # atómico
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# ============================================================
# LECTURA
# ============================================================
def get_section(name: str) -> Dict[str, Any]:
    """
    Devuelve una sección del .toml como dict.

    Args:
        name: nombre de la sección (sin corchetes). TOML es case-sensitive.

    Returns:
        dict con los pares clave/valor tipados (bool, int, str).
        Vacío si la sección no existe.
    """
    _ensure_file_exists()
    try:
        section = getattr(_settings, name.upper(), None)
        if section is None:
            return {}
        try:
            return dict(section)
        except Exception:
            return {}
    except Exception as e:
        log.warning("Error leyendo sección '%s' del .toml: %s", name, e)
        return {}


def get_meta() -> Dict[str, str]:
    """Devuelve la sección [_meta] (updated_at, updated_by)."""
    return get_section("_meta")


# ============================================================
# ESCRITURA PÚBLICA
# ============================================================
def write_sections(updates: Dict[str, Dict[str, Any]], updated_by: str = "") -> None:
    """
    Escribe las secciones indicadas en el .toml de forma atómica.

    Estrategia:
      1. Crear backup `config.toml.bak` (si el archivo existe).
      2. Merge con el contenido actual preservando comentarios.
      3. Escribir en un archivo temporal.
      4. Renombrar el temporal (operación atómica).
      5. Restringir permisos.
      6. Recargar Dynaconf.

    Los valores se convierten automáticamente:
      - None → ""
      - bool/int/float/str → nativo
      - Otros → str()

    Args:
        updates: dict {seccion: {clave: valor}}.
        updated_by: username del operador (se guarda en [_meta]).
    """
    _ensure_file_exists()

    with _lock:
        # ---- 1. Backup
        if CONFIG_PATH.exists():
            try:
                backup = CONFIG_PATH.with_suffix(".toml.bak")
                shutil.copy2(CONFIG_PATH, backup)
            except Exception as e:
                log.warning("No se pudo crear backup del .toml: %s", e)

        # ---- 2. Preparar datos completos (merge implícito con tomlkit)
        data = dict(updates)

        # Metadata (updated_by)
        if "_meta" not in data:
            data["_meta"] = {}
        data["_meta"]["updated_by"] = updated_by or ""

        # ---- 3-4. Escribir atómicamente
        try:
            _write_toml_atomic(data)
        except Exception as e:
            log.error("Error escribiendo config.toml: %s", e)
            raise

        # ---- 5. Permisos
        _apply_file_permissions()

        # ---- 6. Recargar Dynaconf
        _reload_dynaconf()

        log.info("config.toml actualizado por '%s'", updated_by or "(sistema)")


# ============================================================
# API DE COMPATIBILIDAD
# ============================================================
def reset_cache() -> None:
    """Fuerza recarga de Dynaconf (compat con código anterior)."""
    _reload_dynaconf()


# ============================================================
# META — actualización puntual
# ============================================================
def set_meta_value(key: str, value: str) -> None:
    """
    Actualiza un valor individual en la sección [_meta].

    No toca las demás secciones. Útil para registrar eventos
    automáticos (ej: `last_backup_run`) sin pasar por la UI.

    Args:
        key: clave a actualizar.
        value: nuevo valor (str).
    """
    _ensure_file_exists()
    # write_sections usa el mismo _lock (RLock), así que es re-entrante
    write_sections(
        {"_meta": {key: "" if value is None else str(value)}},
        updated_by="system",
    )