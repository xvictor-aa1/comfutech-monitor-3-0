# core/runtime_config.py
"""
Carga perezosa de la configuración runtime desde `config.ini`.

Se mantiene la API pública original (`get_system_config()`,
`get_influx_config()`, etc.) para no romper llamadores. Internamente
todo se lee del .ini vía `core.config_ini` y Dynaconf.

`get_system_config()` devuelve un objeto con atributos compatibles
con los templates existentes (`cfg.influx_url`, `cfg.monitor_enabled`,
`cfg.updated_at`, etc.).
"""
import logging
from types import SimpleNamespace
from typing import Dict

from . import config_ini

log = logging.getLogger(__name__)


# ============================================================
# HELPERS DE CONVERSIÓN
# ============================================================
def _as_str(v, default="") -> str:
    if v is None:
        return default
    return str(v).strip()


def _as_int(v, default: int) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _as_bool(v, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    return str(v).strip().lower() in ("true", "1", "yes", "on")


def _as_datetime(v):
    """Convierte un string ISO a datetime (o None si no es válido)."""
    if not v:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


# ============================================================
# SYSTEM CONFIG (shim compatible con templates)
# ============================================================
def get_system_config():
    """
    Devuelve un objeto con los campos de configuración como atributos.

    Compatible con:
        cfg.influx_url, cfg.influx_token, cfg.influx_org, cfg.influx_bucket
        cfg.grafana_url
        cfg.telegram_enabled, cfg.telegram_bot_token, cfg.telegram_chat_id
        cfg.monitor_enabled
        cfg.snmp_poll_interval, cfg.health_poll_interval,
        cfg.icmp_poll_interval, cfg.radio_poll_interval,
        cfg.ap_clients_poll_interval
        cfg.updated_at, cfg.updated_by

    Además expone `_raw` con todas las secciones para debug.
    """
    influx = config_ini.get_section("influxdb")
    grafana = config_ini.get_section("grafana")
    telegram = config_ini.get_section("telegram")
    monitor = config_ini.get_section("monitor")
    meta = config_ini.get_meta()

    cfg = SimpleNamespace(
        # InfluxDB
        influx_url=_as_str(influx.get("url"), "http://localhost:8086"),
        influx_token=_as_str(influx.get("token")),
        influx_org=_as_str(influx.get("org"), "comfutech"),
        influx_bucket=_as_str(influx.get("bucket"), "metricas_red"),

        # Grafana
        grafana_url=_as_str(grafana.get("url"), "http://localhost:3000"),

        # Telegram
        telegram_enabled=_as_bool(telegram.get("enabled")),
        telegram_bot_token=_as_str(telegram.get("bot_token")),
        telegram_chat_id=_as_str(telegram.get("chat_id")),

        # Monitor
        monitor_enabled=_as_bool(monitor.get("enabled"), True),
        snmp_poll_interval=_as_int(monitor.get("snmp_poll_interval"), 60),
        health_poll_interval=_as_int(monitor.get("health_poll_interval"), 120),
        icmp_poll_interval=_as_int(monitor.get("icmp_poll_interval"), 120),
        radio_poll_interval=_as_int(monitor.get("radio_poll_interval"), 120),
        ap_clients_poll_interval=_as_int(monitor.get("ap_clients_poll_interval"), 120),

        # Auditoría
        updated_at=_as_datetime(meta.get("updated_at")),
        updated_by=_as_str(meta.get("updated_by")) or None,
    )
    cfg._raw = {
        "influxdb": influx,
        "grafana": grafana,
        "telegram": telegram,
        "monitor": monitor,
        "meta": meta,
    }
    return cfg


# ============================================================
# ACCESOS RÁPIDOS
# ============================================================
def get_grafana_url() -> str:
    return get_system_config().grafana_url


def get_influx_config() -> Dict:
    c = get_system_config()
    return {
        "url": c.influx_url,
        "token": c.influx_token,
        "org": c.influx_org,
        "bucket": c.influx_bucket,
    }


def get_telegram_config() -> Dict:
    c = get_system_config()
    return {
        "enabled": c.telegram_enabled,
        "bot_token": c.telegram_bot_token,
        "chat_id": c.telegram_chat_id,
    }


def get_monitor_config() -> Dict:
    c = get_system_config()
    return {
        "enabled": c.monitor_enabled,
        "snmp_poll_interval": c.snmp_poll_interval,
        "health_poll_interval": c.health_poll_interval,
        "icmp_poll_interval": c.icmp_poll_interval,
        "radio_poll_interval": c.radio_poll_interval,
        "ap_clients_poll_interval": c.ap_clients_poll_interval,
    }


# ============================================================
# MAINTENANCE CONFIG
# ============================================================
def get_maintenance_config() -> Dict:
    """
    Devuelve la configuración de la sección [maintenance] del TOML.

    Returns:
        dict con:
          - auto_backup_enabled: bool
          - backup_time: str (HH:MM)
          - backup_on_startup: bool
          - backup_db: bool
          - backup_config: bool
          - retention_days: int
          - mysql_dump_path: str
    """
    m = config_ini.get_section("maintenance")
    return {
        "auto_backup_enabled": _as_bool(m.get("auto_backup_enabled")),
        "backup_time": _as_str(m.get("backup_time"), "03:00"),
        "backup_on_startup": _as_bool(m.get("backup_on_startup")),
        "backup_db": _as_bool(m.get("backup_db"), True),
        "backup_config": _as_bool(m.get("backup_config"), True),
        "retention_days": _as_int(m.get("retention_days"), 30),
        "dump_tool_path": _as_str(m.get("dump_tool_path") or m.get("mysql_dump_path")),
    }


# ============================================================
# EMAIL CONFIG
# ============================================================
def get_email_config() -> Dict:
    email = config_ini.get_section("email")
    return {
        "host": _as_str(email.get("host"), "localhost"),
        "port": _as_int(email.get("port"), 587),
        "use_tls": _as_bool(email.get("use_tls"), True),
        "use_ssl": _as_bool(email.get("use_ssl")),
        "user": _as_str(email.get("host_user")),
        "password": _as_str(email.get("host_password")),
        "from_email": _as_str(
            email.get("default_from"),
            "Comfutech Monitor <noreply@comfutech.local>",
        ),
    }


def apply_email_config_to_settings() -> None:
    """Aplica la config SMTP al módulo `django.conf.settings` en runtime."""
    from django.conf import settings as dj_settings
    cfg = get_email_config()

    dj_settings.EMAIL_HOST = cfg["host"]
    dj_settings.EMAIL_PORT = cfg["port"]
    dj_settings.EMAIL_USE_TLS = cfg["use_tls"]
    dj_settings.EMAIL_USE_SSL = cfg["use_ssl"]
    dj_settings.EMAIL_HOST_USER = cfg["user"]
    dj_settings.EMAIL_HOST_PASSWORD = cfg["password"]
    dj_settings.DEFAULT_FROM_EMAIL = cfg["from_email"]


# ============================================================
# COMPAT: `reset_cache` era el invalidados de la caché en BD
# Ahora no hay caché propia (Dynaconf la maneja), pero mantenemos
# la función por compatibilidad con signals y llamadores.
# ============================================================
def reset_cache() -> None:
    """Fuerza recarga de Dynaconf."""
    config_ini._reload_dynaconf()