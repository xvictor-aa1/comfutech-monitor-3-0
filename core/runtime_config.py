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

    Composición mixta:
      · InfluxDB, Grafana, Telegram, Email → `config.toml`.
      · `monitor.enabled` (toggle global) → `config.toml`.
      · Los 5 intervalos de polling (snmp, health, icmp, radio,
        ap_clients) → tabla `monitor_poller_config` (modelo
        `PollerConfig`). Si la fila aún no existe (BD recién creada o
        migraciones en curso), se usan los defaults del modelo.

    Atributos expuestos (compatibles con templates y vistas):
        cfg.influx_url, cfg.influx_token, cfg.influx_org, cfg.influx_bucket
        cfg.grafana_url
        cfg.telegram_enabled, cfg.telegram_bot_token, cfg.telegram_chat_id
        cfg.monitor_enabled
        cfg.snmp_poll_interval, cfg.health_poll_interval,
        cfg.icmp_poll_interval, cfg.radio_poll_interval,
        cfg.ap_clients_poll_interval
        cfg.updated_at, cfg.updated_by

    Además expone `_raw` con todas las secciones para debug
    (incluida la sección `poller` con los intervalos leídos de BD).
    """
    influx = config_ini.get_section("influxdb")
    grafana = config_ini.get_section("grafana")
    telegram = config_ini.get_section("telegram")
    monitor = config_ini.get_section("monitor")
    meta = config_ini.get_meta()

    # --- Intervalos de polling: desde la BD (PollerConfig) ---
    poller = _get_poller_config_safe()

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

        # Monitor: `enabled` sigue en config.toml; intervalos en BD.
        monitor_enabled=_as_bool(monitor.get("enabled"), True),
        snmp_poll_interval=poller["snmp_poll_interval"],
        health_poll_interval=poller["health_poll_interval"],
        icmp_poll_interval=poller["icmp_poll_interval"],
        radio_poll_interval=poller["radio_poll_interval"],
        ap_clients_poll_interval=poller["ap_clients_poll_interval"],

        # Auditoría
        updated_at=_as_datetime(meta.get("updated_at")),
        updated_by=_as_str(meta.get("updated_by")) or None,
    )
    cfg._raw = {
        "influxdb": influx,
        "grafana": grafana,
        "telegram": telegram,
        "monitor": monitor,
        "poller": poller,
        "meta": meta,
    }
    return cfg


def _get_poller_config_safe() -> dict:
    """
    Devuelve los intervalos de polling de la BD (modelo `PollerConfig`).

    Se usa un helper separado para:
      1. Aislar el `try/except` (la BD puede no estar lista durante el
         bootstrap de Django o durante migraciones).
      2. Devolver un dict con los defaults del modelo si la fila aún
         no existe o la consulta falla.

    Los defaults devueltos coinciden con los del modelo
    (30/60/30/60/60).

    Returns:
        dict con las 5 claves de intervalos (siempre int).
    """
    defaults = {
        "snmp_poll_interval": 30,
        "health_poll_interval": 60,
        "icmp_poll_interval": 30,
        "radio_poll_interval": 60,
        "ap_clients_poll_interval": 60,
    }
    try:
        from monitoreo.models import PollerConfig
        poller = PollerConfig.objects.filter(pk=1).first()
        if poller is None:
            return defaults
        return {
            "snmp_poll_interval": int(
                poller.snmp_poll_interval or defaults["snmp_poll_interval"]
            ),
            "health_poll_interval": int(
                poller.health_poll_interval or defaults["health_poll_interval"]
            ),
            "icmp_poll_interval": int(
                poller.icmp_poll_interval or defaults["icmp_poll_interval"]
            ),
            "radio_poll_interval": int(
                poller.radio_poll_interval or defaults["radio_poll_interval"]
            ),
            "ap_clients_poll_interval": int(
                poller.ap_clients_poll_interval
                or defaults["ap_clients_poll_interval"]
            ),
        }
    except Exception as e:
        log.debug(
            "No se pudo leer PollerConfig de la BD (%s). "
            "Se usan defaults en memoria.", e,
        )
        return defaults


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
    """
    Aplica la config SMTP de `config.toml` al módulo `django.conf.settings`.

    Esta función es la ÚNICA fuente de verdad para los parámetros SMTP
    que usa `django.core.mail.send_mail()` en runtime. Se llama desde:
      1. `core/apps.py::CoreConfig.ready()` — al arrancar Django.
      2. `core/email_utils.py::_ensure_email_config_applied()` — antes
         de cada envío (defensivo).
      3. `core/views_settings.py::system_settings()` — al guardar desde UI.

    Normalización TLS/SSL:
      `EMAIL_USE_TLS` y `EMAIL_USE_SSL` son **mutuamente excluyentes** en
      Django. Si `config.toml` los tiene ambos en `True`, Django lanza
      error al enviar. Aquí normalizamos: si ambos están activos,
      preferimos TLS (puerto 587) y desactivamos SSL.

    Si `config.toml` está vacío o incompleto, se aplican los defaults
    seguros de `get_email_config()` (smtp.gmail.com:587 con TLS).
    """
    from django.conf import settings as dj_settings
    cfg = get_email_config()

    # Normalización TLS/SSL: mutuamente excluyentes.
    use_tls = bool(cfg["use_tls"])
    use_ssl = bool(cfg["use_ssl"])
    if use_tls and use_ssl:
        log.warning(
            "Config SMTP inválida: EMAIL_USE_TLS=True y EMAIL_USE_SSL=True "
            "son mutuamente excluyentes. Se aplicará solo TLS (puerto 587)."
        )
        use_ssl = False

    dj_settings.EMAIL_HOST = cfg["host"]
    dj_settings.EMAIL_PORT = cfg["port"]
    dj_settings.EMAIL_USE_TLS = use_tls
    dj_settings.EMAIL_USE_SSL = use_ssl
    dj_settings.EMAIL_HOST_USER = cfg["user"]
    dj_settings.EMAIL_HOST_PASSWORD = cfg["password"]
    dj_settings.DEFAULT_FROM_EMAIL = cfg["from_email"]

    # Diagnóstico: registrar qué se aplicó (sin exponer credenciales).
    log.debug(
        "Config SMTP aplicada: host=%s port=%s tls=%s ssl=%s user=%s from=%s",
        dj_settings.EMAIL_HOST, dj_settings.EMAIL_PORT,
        use_tls, use_ssl,
        "sí" if dj_settings.EMAIL_HOST_USER else "no",
        dj_settings.DEFAULT_FROM_EMAIL,
    )


# ============================================================
# COMPAT: `reset_cache` era el invalidados de la caché en BD
# Ahora no hay caché propia (Dynaconf la maneja), pero mantenemos
# la función por compatibilidad con signals y llamadores.
# ============================================================
def reset_cache() -> None:
    """Fuerza recarga de Dynaconf."""
    config_ini._reload_dynaconf()