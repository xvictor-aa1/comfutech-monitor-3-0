# monitoreo/services/telegram.py
"""
Notificador de Telegram.

Lee la configuración desde `core.runtime_config`.

El cooldown por regla se persiste en la tabla `TelegramCooldown` para
que sobreviva a reinicios del monitor. La clave de cooldown es
`rule:<rule_id>` o, si se pasa un device (legacy),
`rule:<rule_id>:device:<device_id>`.
"""
import logging
from datetime import timedelta

import requests
from django.db import close_old_connections
from django.utils import timezone

from core.runtime_config import get_telegram_config

log = logging.getLogger(__name__)

# Cooldown por defecto si la regla no define uno.
DEFAULT_COOLDOWN = 600


# ============================================================
# HELPERS DE COOLDOWN PERSISTENTE
# ============================================================
def _get_cooldown_state(key: str) -> tuple:
    """
    Devuelve (last_sent_at, seconds_since_last) para una clave.

    Args:
        key: clave de cooldown (ej. "rule:1").

    Returns:
        tuple: (datetime | None, float | None).
    """
    from monitoreo.models import TelegramCooldown
    try:
        obj = TelegramCooldown.objects.filter(key=key).first()
    except Exception as e:
        log.warning("Error consultando TelegramCooldown '%s': %s", key, e)
        return None, None

    if not obj:
        return None, None

    now = timezone.now()
    delta = (now - obj.last_sent_at).total_seconds()
    return obj.last_sent_at, delta


def _update_cooldown(key: str) -> None:
    """
    Actualiza (o crea) el registro de cooldown para una clave.

    Args:
        key: clave de cooldown.
    """
    from monitoreo.models import TelegramCooldown
    try:
        now = timezone.now()
        TelegramCooldown.objects.update_or_create(
            key=key,
            defaults={"last_sent_at": now},
        )
    except Exception as e:
        log.warning("Error actualizando TelegramCooldown '%s': %s", key, e)


def cleanup_stale_cooldowns(max_age_sec: int = 86400) -> int:
    """
    Elimina registros de `TelegramCooldown` con más de `max_age_sec`
    sin actualizarse.

    Se llama desde el heartbeat del scheduler. Evita que la tabla
    crezca indefinidamente cuando se eliminan reglas o devices.

    Args:
        max_age_sec: antigüedad máxima en segundos (default 24h).

    Returns:
        int: número de registros eliminados.
    """
    from monitoreo.models import TelegramCooldown
    try:
        cutoff = timezone.now() - timedelta(seconds=max_age_sec)
        deleted, _ = TelegramCooldown.objects.filter(
            last_sent_at__lt=cutoff,
        ).delete()
        if deleted:
            log.debug("Limpiados %d cooldown(s) de Telegram huérfanos.", deleted)
        return deleted
    except Exception as e:
        log.error("Error limpiando cooldowns de Telegram: %s", e)
        return 0


# ============================================================
# ENVÍO
# ============================================================
def send_message(text: str, alert_key: str = None,
                 cooldown_sec: int = DEFAULT_COOLDOWN) -> bool:
    """
    Envía un mensaje a Telegram con cooldown persistente.

    Args:
        text: cuerpo del mensaje (HTML).
        alert_key: clave de cooldown (ej. "rule:1"). Si es None,
            no se aplica cooldown (útil para tests manuales).
        cooldown_sec: segundos mínimos entre envíos con la misma
            clave.

    Returns:
        bool: True si se envió, False si no (deshabilitado, sin
            config, o cooldown activo).
    """
    cfg = get_telegram_config()

    if not cfg["enabled"]:
        return False
    if not cfg["bot_token"] or not cfg["chat_id"]:
        log.debug("Telegram sin configurar.")
        return False

    # --- Cooldown persistente ---
    if alert_key:
        _, delta = _get_cooldown_state(alert_key)
        if delta is not None and delta < cooldown_sec:
            log.debug(
                "Telegram: cooldown activo para '%s' (%.0fs < %ds).",
                alert_key, delta, cooldown_sec,
            )
            return False
        # Actualizamos el cooldown antes de enviar para evitar
        # dobles envíos si dos threads llegan al mismo tiempo.
        _update_cooldown(alert_key)

    # --- Envío HTTP ---
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    payload = {
        "chat_id": cfg["chat_id"],
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            log.error("Telegram error %s: %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception as e:
        log.error("Error enviando a Telegram: %s", e)
        return False


def send_alert(severity, message, device=None, rule=None,
               append_context=True) -> bool:
    """
    Envía una alerta a Telegram con cooldown por regla.

    Args:
        severity: "critical" | "warning" | "info".
        message: cuerpo del mensaje.
        device: instancia de Device (se usa solo para el contexto si
            `append_context=True`).
        rule: instancia de AlertRule (obligatoria para cooldown).
        append_context: si True, añade contexto de device/rule al
            mensaje (útil cuando `custom_message` está vacío).

    Returns:
        bool: True si se envió.
    """
    emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(severity, "⚪")
    sev_label = {
        "critical": "CRITICAL",
        "warning": "WARNING",
        "info": "INFO",
    }.get(severity, severity.upper())

    text = f"{emoji} <b>{sev_label}</b>\n\n{message}"

    if append_context:
        if device and getattr(device, "ip", None):
            text += f"\n\n<b>Equipo:</b> {device.name} ({device.ip})"
        if rule:
            text += f"\n<b>Regla:</b> {rule.name}"

    # Cooldown persistente por regla (o por regla+device si se pasa device).
    if rule and device:
        key = f"rule:{rule.id}:device:{device.id}"
    elif rule:
        key = f"rule:{rule.id}"
    else:
        key = None

    cooldown = rule.telegram_cooldown_sec if rule else DEFAULT_COOLDOWN

    return send_message(text, alert_key=key, cooldown_sec=cooldown)


def send_test_message() -> bool:
    """Envía un mensaje de prueba (sin cooldown)."""
    return send_message(
        "🧪 <b>Test de Telegram</b>\n\n"
        "Si ves este mensaje, la configuración funciona correctamente.",
    )