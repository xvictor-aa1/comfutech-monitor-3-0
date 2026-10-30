# core/views.py
"""Vista principal del dashboard."""
import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Case, IntegerField, Value, When
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from alertas.models import Alert, AlertRule
from inventario.models import Device, DeviceModel

log = logging.getLogger(__name__)

# Cantidad máxima de equipos visibles en las cards del dashboard.
MAX_DEVICES_SHOWN = 6

# Rangos de tiempo disponibles para el dashboard.
TIMEFRAME_CHOICES = {
    "1h":  {
        "label": "Última hora",
        "delta": timedelta(hours=1),
        "alerts_label": "en 1h",
        },
    "24h": {
        "label": "Últimas 24h",
        "delta": timedelta(hours=24),
        "alerts_label": "en 24h",
        },
    "7d":  {
        "label": "Últimos 7 días",
        "delta": timedelta(days=7),
        "alerts_label": "en 7d",
        },
}


@login_required
def dashboard(request):
    """
    Vista principal del dashboard.

    Query params:
        range: "1h" | "24h" | "7d" — ventana temporal para las alertas
               recientes y los stats de alertas. Default: 24h.

    Muestra:
      - Stats generales (equipos, modelos, reglas, alertas).
      - Los primeros MAX_DEVICES_SHOWN equipos (Core → Distribución
        → Acceso → CPE).
      - Alertas recientes en el rango temporal seleccionado.
      - Aviso si hay más equipos de los visibles.
    """
    now = timezone.now()

    # ------------------------------------------------------------
    # Timeframe seleccionado
    # ------------------------------------------------------------
    range_key = request.GET.get("range", "24h")
    if range_key not in TIMEFRAME_CHOICES:
        range_key = "24h"

    range_info = TIMEFRAME_CHOICES[range_key]
    range_delta = range_info["delta"]
    range_start = now - range_delta

    # ============================================================
    # Stats: equipos
    # ============================================================
    active_devices_qs = Device.objects.filter(active=True)
    total_devices = active_devices_qs.count()
    core_devices = active_devices_qs.filter(
        device_role__in=["core", "distribution"]
    ).count()

    # ============================================================
    # Stats: modelos
    # ============================================================
    active_models_qs = DeviceModel.objects.filter(active=True)
    total_models = active_models_qs.count()
    wireless_models = active_models_qs.filter(is_wireless_link=True).count()

    # ============================================================
    # Stats: reglas
    # ============================================================
    total_rules = AlertRule.objects.count()
    active_rules = AlertRule.objects.filter(enabled=True).count()
    rules_with_telegram = AlertRule.objects.filter(
        enabled=True, telegram_enabled=True
    ).count()

    # ============================================================
    # Stats: alertas
    # ============================================================
    active_alerts_qs = Alert.objects.filter(status="activa")
    active_alerts_count = active_alerts_qs.count()
    critical_count = active_alerts_qs.filter(severity="critical").count()
    warning_count = active_alerts_qs.filter(severity="warning").count()

    # Alertas recientes en el rango seleccionado
    recent_alerts = (
        Alert.objects
        .filter(created_at__gte=range_start)
        .select_related("device", "rule")
        .order_by("-created_at")[:8]
    )

    # Conteo de alertas en el rango (para el badge del stat)
    alerts_in_range = Alert.objects.filter(
        created_at__gte=range_start
    ).count()

    # ============================================================
    # Equipos a mostrar en las cards (top MAX_DEVICES_SHOWN)
    # ============================================================
    # Prioridad: Core (0) > Distribución (1) > Acceso (2) > CPE (3).
    role_priority = Case(
        When(device_role="core", then=Value(0)),
        When(device_role="distribution", then=Value(1)),
        When(device_role="access", then=Value(2)),
        When(device_role="cpe", then=Value(3)),
        default=Value(4),
        output_field=IntegerField(),
    )

    devices_to_show = list(
        active_devices_qs
        .select_related("device_model")
        .prefetch_related("interfaces")
        .annotate(role_priority=role_priority)
        .order_by("role_priority", "name")[:MAX_DEVICES_SHOWN]
    )

    device_ids_to_show = [d.id for d in devices_to_show]
    has_more_devices = total_devices > MAX_DEVICES_SHOWN

    # ============================================================
    # Context
    # ============================================================
    context = {
        "total_devices": total_devices,
        "core_devices": core_devices,
        "total_models": total_models,
        "wireless_models": wireless_models,
        "total_rules": total_rules,
        "active_rules": active_rules,
        "rules_with_telegram": rules_with_telegram,
        "active_alerts_count": active_alerts_count,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "alerts_in_range": alerts_in_range,
        "recent_alerts": recent_alerts,
        "devices_to_show": devices_to_show,
        "device_ids_to_show": device_ids_to_show,
        "has_more_devices": has_more_devices,
        "max_devices_shown": MAX_DEVICES_SHOWN,
        # Timeframe
        "range_key": range_key,
        "range_info": range_info,
        "timeframe_choices": TIMEFRAME_CHOICES,
    }
    return render(request, "core/dashboard.html", context)


# ============================================================
# API: ALERTAS NUEVAS (para toasts en el dashboard)
# ============================================================
@login_required
def recent_alerts_api(request):
    """
    Devuelve alertas nuevas desde un timestamp (para mostrar toasts).

    Query params:
        since: timestamp ISO. Solo devuelve alertas con
               created_at > since.

    Returns:
        JsonResponse: {alerts: [...], timestamp: iso_now}
    """
    since_param = request.GET.get("since", "")

    try:
        since_dt = timezone.datetime.fromisoformat(
            since_param.replace("Z", "+00:00")
        )
    except (ValueError, AttributeError):
        # Fallback: últimos 30s
        since_dt = timezone.now() - timedelta(seconds=30)

    # Traer alertas activas creadas después del timestamp
    alerts = (
        Alert.objects
        .filter(created_at__gt=since_dt, status="activa")
        .select_related("device")
        .order_by("-created_at")[:10]
    )

    data = [{
        "id": a.id,
        "severity": a.severity,
        "severity_label": a.get_severity_display(),
        "message": a.message[:200],
        "device": a.device.name if a.device else None,
        "device_id": a.device.id if a.device else None,
        "created_at": a.created_at.isoformat(),
    } for a in alerts]

    return JsonResponse({
        "alerts": data,
        "timestamp": timezone.now().isoformat(),
    })