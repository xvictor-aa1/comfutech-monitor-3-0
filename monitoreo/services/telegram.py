# monitoreo/services/telegram.py
"""
Notificador de Telegram.

Lee la configuración desde `core.runtime_config` (que a su vez
la lee de la tabla `system_config`).
"""
import logging
import time

import requests

from core.runtime_config import get_telegram_config

log = logging.getLogger(__name__)

_last_sent = {}
DEFAULT_COOLDOWN = 600


def send_message(text: str, alert_key: str = None,
                 cooldown_sec: int = DEFAULT_COOLDOWN) -> bool:
    cfg = get_telegram_config()

    if not cfg["enabled"]:
        return False
    if not cfg["bot_token"] or not cfg["chat_id"]:
        log.debug("Telegram sin configurar.")
        return False

    if alert_key:
        now = time.time()
        last = _last_sent.get(alert_key, 0)
        if now - last < cooldown_sec:
            return False
        _last_sent[alert_key] = now

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

    cooldown = rule.telegram_cooldown_sec if rule else DEFAULT_COOLDOWN
    key = f"rule:{rule.id}:device:{device.id}" if rule and device else None

    return send_message(text, alert_key=key, cooldown_sec=cooldown)


def send_test_message() -> bool:
    return send_message(
        "🧪 <b>Test de Telegram</b>\n\n"
        "Si ves este mensaje, la configuración funciona correctamente.",
    )