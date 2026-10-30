# core/views_settings.py
"""
Panel de configuración del sistema (solo superadmin).

La configuración se guarda en `config.ini` (no en BD). Los cambios
se aplican en el próximo ciclo del monitor (≤60s) vía
`config_ini.reload_if_changed()`.

Diseño:
  - Un único formulario con TABS visuales.
  - Todos los inputs se envían juntos al guardar.
  - Cada tab tiene sus propios botones "Probar".
  - Un único botón "Guardar toda la configuración".
"""
import logging

import requests
from django.contrib import messages
from django.shortcuts import render, redirect

from core import config_ini
from core.decorators import require_superadmin
from core.runtime_config import get_system_config, get_email_config
from monitoreo.services import telegram

log = logging.getLogger(__name__)


# ============================================================
# HELPERS DE EXTRACCIÓN DEL POST
# ============================================================
def _get_str(request, key: str, default: str = "") -> str:
    return (request.POST.get(key) or default).strip()


def _get_int(request, key: str, default: int = 0) -> int:
    try:
        return int(request.POST.get(key, default))
    except (ValueError, TypeError):
        return default


def _get_bool(request, key: str) -> bool:
    return request.POST.get(key) == "on"


def _clamp(value: int, min_v: int, max_v: int) -> int:
    return max(min_v, min(max_v, value))


# ============================================================
# GUARDAR — VISTA PRINCIPAL
# ============================================================
@require_superadmin()
def system_settings(request):
    """
    Panel de configuración del sistema.

    GET:
      - Renderiza el formulario con los valores actuales del .ini.

    POST:
      - Guarda todas las secciones de una sola vez en config.ini.
    """
    if request.method == "POST":
        # ============================================================
        # INFLUXDB
        # ============================================================
        influx_updates = {
            "url": _get_str(request, "influx_url") or "http://localhost:8086",
            "org": _get_str(request, "influx_org") or "comfutech",
            "bucket": _get_str(request, "influx_bucket") or "metricas_red",
        }
        new_token = _get_str(request, "influx_token")
        if new_token:
            influx_updates["token"] = new_token
        # Si está vacío, NO sobrescribimos el token existente.

        # ============================================================
        # MONITOR
        # ============================================================
        monitor_updates = {
            "enabled": "true" if _get_bool(request, "monitor_enabled") else "false",
            "snmp_poll_interval": str(_clamp(
                _get_int(request, "snmp_poll_interval", 60), 10, 3600
            )),
            "health_poll_interval": str(_clamp(
                _get_int(request, "health_poll_interval", 120), 10, 3600
            )),
            "icmp_poll_interval": str(_clamp(
                _get_int(request, "icmp_poll_interval", 120), 10, 3600
            )),
            "radio_poll_interval": str(_clamp(
                _get_int(request, "radio_poll_interval", 120), 10, 3600
            )),
            "ap_clients_poll_interval": str(_clamp(
                _get_int(request, "ap_clients_poll_interval", 120), 10, 3600
            )),
        }

        # ============================================================
        # TELEGRAM
        # ============================================================
        telegram_updates = {
            "enabled": "true" if _get_bool(request, "telegram_enabled") else "false",
            "chat_id": _get_str(request, "telegram_chat_id"),
        }
        new_bot_token = _get_str(request, "telegram_bot_token")
        if new_bot_token:
            telegram_updates["bot_token"] = new_bot_token

        # ============================================================
        # GRAFANA
        # ============================================================
        grafana_updates = {
            "url": _get_str(request, "grafana_url") or "http://localhost:3000",
        }

        # ============================================================
        # EMAIL
        # ============================================================
        email_updates = {
            "host": _get_str(request, "email_host") or "smtp.gmail.com",
            "port": str(_get_int(request, "email_port", 587)),
            "use_tls": "true" if _get_bool(request, "email_use_tls") else "false",
            "use_ssl": "true" if _get_bool(request, "email_use_ssl") else "false",
            "host_user": _get_str(request, "email_host_user"),
            "default_from": (
                _get_str(request, "default_from_email")
                or "Comfutech Monitor <noreply@comfutech.local>"
            ),
        }
        new_email_password = _get_str(request, "email_host_password")
        if new_email_password:
            email_updates["host_password"] = new_email_password

        # ============================================================
        # ESCRIBIR EN CONFIG.INI
        # ============================================================
        try:
            config_ini.write_sections(
                updates={
                    "influxdb": influx_updates,
                    "monitor": monitor_updates,
                    "telegram": telegram_updates,
                    "grafana": grafana_updates,
                    "email": email_updates,
                },
                updated_by=request.user.username,
            )
        except Exception as e:
            log.exception("Error guardando config.ini")
            messages.error(
                request,
                f"No se pudo guardar la configuración: {e}. "
                "Verifica los permisos del archivo config.ini.",
            )
            return redirect("core:system_settings")

        # Reaplicar email en el settings runtime
        try:
            from core.runtime_config import apply_email_config_to_settings
            apply_email_config_to_settings()
        except Exception as e:
            log.error("No se pudo aplicar la config de email: %s", e)

        # Resetear el cliente de InfluxDB para que tome la nueva config
        try:
            from monitoreo.services import influx_writer
            influx_writer.reset()
        except Exception:
            pass

        messages.success(
            request,
            "Configuración guardada en config.ini. "
            "El monitor aplicará los cambios en menos de 60 segundos.",
        )
        return redirect("core:system_settings")

    # ============================================================
    # GET
    # ============================================================
    cfg = get_system_config()
    email_cfg = get_email_config()

    context = {
        "cfg": cfg,
        "influx_token_set": bool(cfg.influx_token),
        "telegram_token_set": bool(cfg.telegram_bot_token),
        "email_cfg": email_cfg,
        "email_password_set": bool(email_cfg["password"]),
        "config_file_path": str(config_ini.CONFIG_PATH),
    }
    return render(request, "core/system_settings.html", context)


# ============================================================
# TEST: INFLUXDB
# ============================================================
@require_superadmin()
def test_influx(request):
    """Prueba la conexión a InfluxDB con los valores del POST."""
    if request.method != "POST":
        return redirect("core:system_settings")

    from influxdb_client import InfluxDBClient

    saved = get_system_config()
    url = _get_str(request, "influx_url") or saved.influx_url
    token = _get_str(request, "influx_token") or saved.influx_token
    org = _get_str(request, "influx_org") or saved.influx_org
    bucket = _get_str(request, "influx_bucket") or saved.influx_bucket

    if not url:
        messages.error(request, "❌ Falta la URL de InfluxDB.")
        return redirect("core:system_settings")
    if not token:
        messages.error(request, "❌ Falta el API Token de InfluxDB.")
        return redirect("core:system_settings")
    if not org:
        messages.error(request, "❌ Falta la Organización de InfluxDB.")
        return redirect("core:system_settings")
    if not bucket:
        messages.error(request, "❌ Falta el Bucket de InfluxDB.")
        return redirect("core:system_settings")

    # PASO 1: servidor online
    health_url = url.rstrip("/") + "/health"
    try:
        r = requests.get(health_url, timeout=5)
        server_online = r.status_code == 200
    except requests.exceptions.ConnectionError:
        messages.error(request, f"❌ No se puede conectar a {url}.")
        return redirect("core:system_settings")
    except requests.exceptions.Timeout:
        messages.error(request, "❌ Timeout al conectar con InfluxDB.")
        return redirect("core:system_settings")
    except Exception as e:
        messages.error(request, f"❌ Error de conexión: {e}")
        return redirect("core:system_settings")

    if not server_online:
        messages.error(request, f"❌ El servidor responde con HTTP {r.status_code}.")
        return redirect("core:system_settings")

    # PASO 2 y 3: token + bucket
    client = None
    try:
        client = InfluxDBClient(url=url, token=token, org=org, timeout=5000)
        try:
            buckets_api = client.buckets_api()
            buckets = buckets_api.find_buckets().buckets
            bucket_names = [b.name for b in buckets]
        except Exception as e:
            err = str(e)
            if "unauthorized" in err.lower() or "401" in err:
                messages.error(request, "❌ El API Token es inválido o no tiene permisos.")
            else:
                messages.error(request, f"❌ Error consultando la API: {err[:200]}")
            return redirect("core:system_settings")

        if bucket not in bucket_names:
            messages.warning(
                request,
                f"⚠️ Conexión OK, pero el bucket '{bucket}' no existe. "
                f"Disponibles: {', '.join(bucket_names) or '(ninguno)'}.",
            )
        else:
            messages.success(
                request,
                f"✅ Conexión exitosa. Bucket '{bucket}' accesible "
                f"({len(buckets)} bucket(s)).",
            )
    except Exception as e:
        messages.error(request, f"❌ Error inesperado: {e}")
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass

    return redirect("core:system_settings")


# ============================================================
# TEST: GRAFANA
# ============================================================
@require_superadmin()
def test_grafana(request):
    if request.method != "POST":
        return redirect("core:system_settings")

    saved = get_system_config()
    url = _get_str(request, "grafana_url") or saved.grafana_url

    if not url:
        messages.error(request, "❌ Falta la URL de Grafana.")
        return redirect("core:system_settings")

    try:
        r = requests.get(url, timeout=5, allow_redirects=True)
        if r.status_code < 400:
            messages.success(request, f"✅ Grafana responde (HTTP {r.status_code}).")
        elif r.status_code < 500:
            messages.warning(
                request,
                f"⚠️ Grafana responde con HTTP {r.status_code}. "
                "Puede requerir autenticación.",
            )
        else:
            messages.error(request, f"❌ Grafana responde con HTTP {r.status_code}.")
    except requests.exceptions.ConnectionError:
        messages.error(request, f"❌ No se puede conectar a {url}.")
    except requests.exceptions.Timeout:
        messages.error(request, "❌ Timeout al conectar con Grafana.")
    except Exception as e:
        messages.error(request, f"❌ Error: {e}")

    return redirect("core:system_settings")


# ============================================================
# TEST: TELEGRAM
# ============================================================
@require_superadmin()
def test_telegram(request):
    if request.method != "POST":
        return redirect("core:system_settings")

    if telegram.send_test_message():
        messages.success(request, "✅ Mensaje enviado. Revisa tu chat de Telegram.")
    else:
        messages.error(
            request,
            "❌ No se pudo enviar. Verifica que Telegram esté activado, "
            "y que el Bot Token y el Chat ID sean correctos.",
        )
    return redirect("core:system_settings")


# ============================================================
# TEST: EMAIL
# ============================================================
@require_superadmin()
def test_email(request):
    if request.method != "POST":
        return redirect("core:system_settings")

    from django.core.mail import send_mail
    from django.conf import settings as dj_settings

    to = _get_str(request, "test_email_to")
    if not to:
        messages.error(request, "❌ Debes indicar un email de destino.")
        return redirect("core:system_settings")

    saved = get_email_config()
    host = _get_str(request, "email_host") or saved["host"]
    port = _get_int(request, "email_port", saved["port"] or 587)
    use_tls = _get_bool(request, "email_use_tls")
    use_ssl = _get_bool(request, "email_use_ssl")
    user = _get_str(request, "email_host_user") or saved["user"]
    password = _get_str(request, "email_host_password") or saved["password"]
    from_email = (
        _get_str(request, "default_from_email")
        or saved["from_email"]
        or "Comfutech Monitor <noreply@comfutech.local>"
    )

    dj_settings.EMAIL_HOST = host
    dj_settings.EMAIL_PORT = port
    dj_settings.EMAIL_USE_TLS = use_tls and not use_ssl
    dj_settings.EMAIL_USE_SSL = use_ssl
    dj_settings.EMAIL_HOST_USER = user
    dj_settings.EMAIL_HOST_PASSWORD = password
    dj_settings.DEFAULT_FROM_EMAIL = from_email

    try:
        send_mail(
            subject="[Comfutech Monitor] Email de prueba",
            message=(
                "Si recibes este mensaje, la configuración de email "
                "funciona correctamente.\n\n— Comfutech Monitor"
            ),
            from_email=from_email,
            recipient_list=[to],
            fail_silently=False,
        )
        messages.success(request, f"✅ Email enviado correctamente a {to}.")
    except Exception as e:
        messages.error(request, f"❌ Error al enviar el email: {e}")

    return redirect("core:system_settings")