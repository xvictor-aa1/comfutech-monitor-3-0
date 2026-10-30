# monitoreo/views.py
"""
Vistas de la app `monitoreo`.

Incluye:
  - run_discovery: ejecuta discovery para un equipo.
  - run_discovery_ap: ejecuta discovery para un equipo wireless Access Point.
  - run_discovery_all: ejecuta discovery para todos los equipos.
  - discovery_history: historial de ejecuciones por equipo.
  - monitor_status: estado del monitor (servicio + configuración).
  - monitor_live: monitoreo en vivo de equipos.
  - monitor_devices_live: API JSON de métricas en vivo (incluye RF).
"""
import logging
import time
import traceback

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.decorators import require_admin_or_super
from core.runtime_config import get_system_config
from core.sorting import apply_sort, has_active_filters
from inventario.models import Device, DeviceModel
from .models import DiscoveryJob, MonitorStatus
from .services.chassis_oids import (
    get_available_health_metrics,
    has_meaningful_health_metrics,
)
from .services.discovery import discover_interfaces

log = logging.getLogger(__name__)


# ============================================================
# DISCOVERY — EQUIPO INDIVIDUAL
# ============================================================
@login_required
@require_admin_or_super()
def run_discovery(request, device_id):
    """Ejecuta el discovery SNMP para un equipo específico."""
    device = get_object_or_404(Device, pk=device_id)

    if request.method != "POST":
        return redirect("inventario:device_interfaces", device_id=device_id)

    # Crear job en estado running
    job = DiscoveryJob.objects.create(
        device=device,
        status="running",
        triggered_by=request.user if request.user.is_authenticated else None,
    )

    start = time.time()
    result = discover_interfaces(device)
    elapsed_ms = int((time.time() - start) * 1000)

    # Actualizar job
    job.finished_at = timezone.now()
    job.duration_ms = elapsed_ms
    job.interfaces_found = result["interfaces_found"]
    job.interfaces_up = result["interfaces_up"]
    job.interfaces_created = result["created"]
    job.interfaces_updated = result["updated"]
    job.interfaces_deleted = result["deleted"]

    if result["success"]:
        job.status = "success"
        messages.success(
            request,
            f"Discovery de '{device.name}': "
            f"{result['interfaces_found']} interfaces detectadas "
            f"({result['interfaces_up']} up), "
            f"{result['created']} nuevas, {result['updated']} actualizadas, "
            f"{result['deleted']} eliminadas. "
            f"Duración: {elapsed_ms} ms."
        )
    else:
        job.status = "failed"
        job.error_message = result.get("error") or "Error desconocido"
        messages.error(
            request,
            f"Discovery de '{device.name}' falló: {job.error_message}"
        )

    job.save()
    return redirect("inventario:device_interfaces", device_id=device_id)


# ============================================================
# DISCOVERY — CLIENTES AP (equipos wireless)
# ============================================================
@login_required
@require_admin_or_super()
def run_ap_discovery(request, device_id):
    """
    Ejecuta el discovery de clientes AP (ubntWlStatTable) para un equipo
    wireless específico.

    Solo aplica a modelos con `is_wireless_link=True`. Actualiza la
    lista `device.ap_interfaces` preservando clientes offline.

    Args:
        request: HttpRequest (POST).
        device_id: ID del equipo.

    Returns:
        Redirect a device_interfaces con mensaje de éxito/error.
    """
    from .services.ap_clients import discover_ap_clients

    device = get_object_or_404(Device, pk=device_id)

    if request.method != "POST":
        return redirect(
            "inventario:device_interfaces", device_id=device_id
        )

    # Validar que el modelo sea wireless
    if not device.is_wireless_link:
        messages.error(
            request,
            f"El equipo '{device.name}' no es un radioenlace. "
            "Usa 'Discovery Interfaces' en su lugar."
        )
        return redirect(
            "inventario:device_interfaces", device_id=device_id
        )

    result = discover_ap_clients(device)

    if result["success"]:
        messages.success(
            request,
            f"Discovery AP de '{device.name}': "
            f"{result['clients_found']} cliente(s) conectados, "
            f"{result['added']} nuevos, {result['updated']} actualizados, "
            f"{result['total']} totales (incluyendo offline)."
        )
    else:
        messages.error(
            request,
            f"Discovery AP de '{device.name}' falló: {result['error']}"
        )

    return redirect("inventario:device_interfaces", device_id=device_id)


# ============================================================
# DISCOVERY — TODOS LOS EQUIPOS
# ============================================================
@login_required
@require_admin_or_super()
def run_discovery_all(request):
    """
    Ejecuta el discovery en todos los equipos activos (endpoint JSON).

    Para cada equipo:
      1. Discovery de interfaces SNMP (IF-MIB).
      2. Si el modelo es wireless, discovery de clientes AP
         (ubntWlStatTable).

    Returns:
        JsonResponse: resumen por equipo con ambos resultados.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    from .services.ap_clients import discover_ap_clients

    devices = Device.objects.filter(active=True).select_related("device_model")
    total = devices.count()
    results = []

    for device in devices:
        # ---- 1. Discovery de interfaces ----
        job = DiscoveryJob.objects.create(
            device=device, status="running", triggered_by=request.user,
        )
        start = time.time()
        result = discover_interfaces(device)
        elapsed_ms = int((time.time() - start) * 1000)

        job.finished_at = timezone.now()
        job.duration_ms = elapsed_ms
        job.interfaces_found = result["interfaces_found"]
        job.interfaces_up = result["interfaces_up"]
        job.interfaces_created = result["created"]
        job.interfaces_updated = result["updated"]
        job.interfaces_deleted = result["deleted"]
        job.status = "success" if result["success"] else "failed"
        if not result["success"]:
            job.error_message = result.get("error") or "Error desconocido"
        job.save()

        entry = {
            "device": device.name,
            "success": result["success"],
            "found": result["interfaces_found"],
            "created": result["created"],
            "updated": result["updated"],
            "deleted": result["deleted"],
            "duration_ms": elapsed_ms,
            "error": result.get("error"),
            "ap_clients": None,   # se rellena abajo si aplica
        }

        # ---- 2. Discovery de clientes AP (solo wireless) ----
        is_wireless = bool(
            device.device_model and device.device_model.is_wireless_link
        )
        if is_wireless:
            try:
                ap_result = discover_ap_clients(device)
                entry["ap_clients"] = {
                    "success": ap_result["success"],
                    "clients_found": ap_result["clients_found"],
                    "added": ap_result["added"],
                    "updated": ap_result["updated"],
                    "total": ap_result["total"],
                    "error": ap_result.get("error"),
                }
            except Exception as e:
                log.exception("[%s] Discovery AP falló: %s", device.name, e)
                entry["ap_clients"] = {
                    "success": False,
                    "error": str(e),
                }

        results.append(entry)

    return JsonResponse({
        "total": total,
        "results": results,
        "success_count": sum(1 for r in results if r["success"]),
        "failed_count": sum(1 for r in results if not r["success"]),
    })


# ============================================================
# DISCOVERY — HISTORIAL
# ============================================================
@login_required
def discovery_history(request, device_id):
    """Muestra el historial de ejecuciones del discovery de un equipo."""
    device = get_object_or_404(Device, pk=device_id)
    jobs = DiscoveryJob.objects.filter(device=device).select_related("triggered_by")

    # Filtros
    status_filter = request.GET.get("status", "")
    triggered_filter = request.GET.get("triggered_by", "")
    search = request.GET.get("q", "").strip()
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")

    if status_filter:
        jobs = jobs.filter(status=status_filter)
    if triggered_filter:
        jobs = jobs.filter(triggered_by_id=triggered_filter)
    if search:
        jobs = jobs.filter(error_message__icontains=search)
    if date_from:
        jobs = jobs.filter(started_at__date__gte=date_from)
    if date_to:
        jobs = jobs.filter(started_at__date__lte=date_to)

    # Ordenamiento
    SORTABLE = {
        "fecha":        "started_at",
        "estado":       "status",
        "duracion":     "duration_ms",
        "encontradas":  "interfaces_found",
        "nuevas":       "interfaces_created",
        "actualizadas": "interfaces_updated",
        "eliminadas":   "interfaces_deleted",
        "disparado":    "triggered_by__username",
    }
    jobs, sort_key, order = apply_sort(request, jobs, SORTABLE, "-started_at")

    # ============================================================
    # Paginación: 10 ejecuciones por página
    # ============================================================
    from django.core.paginator import Paginator
    paginator = Paginator(jobs, 10)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    from django.contrib.auth.models import User
    user_ids = DiscoveryJob.objects.filter(device=device).values_list(
        "triggered_by", flat=True
    ).distinct()
    triggered_users = User.objects.filter(id__in=[u for u in user_ids if u])

    base = DiscoveryJob.objects.filter(device=device)
    context = {
        "device": device,
        "jobs": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "sort_key": sort_key,
        "order": order,
        "status_filter": status_filter,
        "triggered_filter": triggered_filter,
        "search": search,
        "date_from": date_from,
        "date_to": date_to,
        "triggered_users": triggered_users,
        "count_all": base.count(),
        "count_success": base.filter(status="success").count(),
        "count_failed": base.filter(status="failed").count(),
        "count_running": base.filter(status="running").count(),
        "has_filters": has_active_filters(
            request, ["status", "triggered_by", "q", "date_from", "date_to"]
        ),
    }
    return render(request, "monitoreo/discovery_history.html", context)


# ============================================================
# MONITOR — ESTADO DEL SERVICIO
# ============================================================
@login_required
def monitor_status(request):
    """
    Vista principal del monitor: estado del servicio + configuración.

    Muestra estado, heartbeats, intervalos y último run de cada poller.

    Muestra:
      - Estado (activo/detenido) del proceso monitor.
      - Último heartbeat, host y PID.
      - Intervalos configurados de cada poller.
      - Última ejecución de cada poller.
    """
    status = MonitorStatus.objects.filter(id=1).first()
    cfg = get_system_config()

    context = {
        "status": status,
        "is_alive": status.is_alive if status else False,
        "cfg": cfg,
        "monitor_enabled": cfg.monitor_enabled,
        "snmp_interval": cfg.snmp_poll_interval,
        "health_interval": cfg.health_poll_interval,
        "icmp_interval": cfg.icmp_poll_interval,
        "radio_interval": cfg.radio_poll_interval,
        "ap_clients_interval": cfg.ap_clients_poll_interval,
    }
    return render(request, "monitoreo/monitor_status.html", context)


# ============================================================
# MONITOR — LIVE (MONITOREO EN VIVO)
# ============================================================
@login_required
def monitor_live(request):
    """
    Página de Monitoreo en vivo.

    Muestra las tarjetas con los últimos valores reportados por los
    pollers: ICMP, SNMP tráfico, Core Health, Radio y estado TCP.

    Solo renderiza el template; los datos los pide el frontend
    vía AJAX a `monitor_devices_live`.
    """
    
    # Equipos con sus modelos precargados
    devices = (
        Device.objects
        .filter(active=True)
        .select_related("device_model")
        .prefetch_related("interfaces")
    )

    # Estadísticas para el header
    total_devices = devices.count()
    monitored_count = sum(
        1 for d in devices if any(i.monitored for i in d.interfaces.all())
    )

    context = {
        "devices_count": total_devices,
        "monitored_count": monitored_count,
    }
    return render(request, "monitoreo/monitor_live.html", context)


# ============================================================
# MONITOR — API JSON LIVE
# ============================================================
@login_required
def monitor_devices_live(request):
    """
    API JSON con los últimos valores de cada equipo.

    Incluye:
      - Bloque `radio` con métricas de RF si el equipo es wireless.
      - `has_radio_metrics` y `available_radio_metrics` para que el
        frontend decida si mostrar el bloque.
      - `is_wireless_link` para el badge.
      - `wireless_info` (utilización de enlace) para equipos wireless.

    Returns:
        JsonResponse: {timestamp, devices: [...], _debug: {...}}
    """
    from .services import influx_reader

    try:
        # --- Equipos activos con modelo y interfaces precargadas ---
        devices = list(
            Device.objects
            .filter(active=True)
            .select_related("device_model")
            .prefetch_related("interfaces")
        )

        # --- Snapshot de métricas (con caché interna) ---
        snapshot = influx_reader.get_live_snapshot()
        icmp_data = snapshot.get("icmp", {})
        traffic_data = snapshot.get("traffic", {})
        health_data = snapshot.get("health", {})
        tcp_data = snapshot.get("tcp", {})
        radio_data = snapshot.get("radio", {})
        ap_clients_data = snapshot.get("ap_clients", {})

        # --- Mapa de alias por dispositivo ---
        alias_map = {}
        for device in devices:
            alias_map[device.id] = {
                i.if_name: (i.if_alias or "")
                for i in device.interfaces.all() if i.if_name
            }

        result = []
        for device in devices:
            monitored_ifaces = [i for i in device.interfaces.all() if i.monitored]

            # --- Determinar si es radio-enlace ---
            is_wireless = bool(
                device.device_model and device.device_model.is_wireless_link
            )

            # --- Métricas de chasis disponibles para este equipo ---
            available_health = get_available_health_metrics(device)
            has_health = (
                has_meaningful_health_metrics(device)
                and bool(device.monitor_health)
            )

            # ¿El modelo tiene interfaces tradicionales?
            model_has_interfaces = bool(
                device.device_model and device.device_model.has_interfaces
            ) if device.device_model else True

            # Tráfico: solo si el modelo soporta interfaces, el usuario
            # habilitó monitor_interfaces Y hay interfaces monitoreadas.
            has_traffic = (
                bool(monitored_ifaces)
                and model_has_interfaces
                and device.monitor_interfaces
            )

            # --- Métricas de RF disponibles ---
            available_radio = []
            has_radio = False
            if is_wireless:
                from .services.chassis_oids import get_available_radio_metrics
                available_radio = get_available_radio_metrics(device)
                has_radio = bool(available_radio)

            # --- ICMP ---
            icmp = icmp_data.get(device.name, {})
            icmp_payload = None
            if icmp:
                icmp_payload = {
                    "alive": icmp.get("alive"),
                    "rtt": icmp.get("rtt"),
                    "loss": icmp.get("loss"),
                    "ts": icmp.get("ts").isoformat() if icmp.get("ts") else None,
                }

            # --- Tráfico ---
            traffic_payload = []
            if device.name in traffic_data:
                for t in traffic_data[device.name]:
                    iface_name = t.get("interface")
                    alias = alias_map.get(device.id, {}).get(iface_name, "")
                    traffic_payload.append({
                        "interface": iface_name,
                        "alias": alias,
                        "in_bps": t.get("in_bps"),
                        "out_bps": t.get("out_bps"),
                        "utilization": t.get("utilization_pct"),
                        "capacity_bps": t.get("capacity_bps"),
                        "ts": t.get("ts").isoformat() if t.get("ts") else None,
                    })

            # --- Información extra para radioenlaces ---
            # Se busca la interfaz con la mayor utilización para destacarla
            wireless_info = None
            if is_wireless and traffic_payload:
                valid_traffic = [
                    t for t in traffic_payload
                    if t.get("utilization") is not None
                ]
                if valid_traffic:
                    best = max(valid_traffic, key=lambda t: t["utilization"])
                    wireless_info = {
                        "interface": best.get("interface"),
                        "alias": best.get("alias"),
                        "capacity_bps": best.get("capacity_bps"),
                        "utilization_pct": best.get("utilization"),
                        "in_bps": best.get("in_bps"),
                        "out_bps": best.get("out_bps"),
                    }

            # ========================================================
            # Interfaz "destacada" para el dashboard
            # ========================================================
            # Para equipos normales: preferimos la interfaz que el
            # usuario marcó como destacada o la primera con tráfico.
            # Para radioenlaces: no aplica (el dashboard muestra
            # métricas de radio en lugar de tráfico).
            dashboard_traffic = None
            if traffic_payload and not is_wireless:
                preferred_name = None
                if device.dashboard_interface_id:
                    try:
                        preferred_name = device.dashboard_interface.if_name
                    except Exception:
                        preferred_name = None

                if preferred_name:
                    for t in traffic_payload:
                        if t.get("interface") == preferred_name:
                            dashboard_traffic = t
                            break
                if dashboard_traffic is None:
                    dashboard_traffic = traffic_payload[0]

            # --- Chasis ---
            health = health_data.get(device.name, {})
            health_payload = None
            if health:
                health_payload = {
                    "cpu": health.get("cpu"),
                    "mem": health.get("mem"),
                    "temp": health.get("temp"),
                    "uptime": health.get("uptime"),
                    "ts": health.get("ts").isoformat() if health.get("ts") else None,
                }

            # --- TCP ---
            tcp_payload = []
            if device.name in tcp_data:
                for t in tcp_data[device.name]:
                    tcp_payload.append({
                        "port": t.get("port"),
                        "is_open": t.get("is_open"),
                    })

            # Radiofrecuencia
            radio = radio_data.get(device.name, {})
            radio_payload = None
            if radio:
                radio_payload = {
                    "freq": radio.get("radio_freq"),
                    "txpower": radio.get("radio_txpower"),
                    "signal": radio.get("wl_signal"),
                    "noise": radio.get("wl_noise_floor"),
                    "ccq": radio.get("wl_ccq"),
                    "tx_rate": radio.get("wl_tx_rate"),
                    "rx_rate": radio.get("wl_rx_rate"),
                    "airmax_quality": radio.get("airmax_quality"),
                    "airmax_capacity": radio.get("airmax_capacity"),
                    "chan_width": radio.get("chan_width"),
                    "ts": radio.get("ts").isoformat() if radio.get("ts") else None,
                }
            
            # --- Clientes AP (solo si es AP) ---
            ap_clients_payload = None
            if is_wireless:
                # Mapa de config estática por MAC
                static_map = {
                    (c.get("mac") or "").upper(): c
                    for c in (device.ap_interfaces or [])
                }
                live_map = {
                    (c.get("client_mac") or "").upper(): c
                    for c in ap_clients_data.get(device.name, [])
                }

                # Unión: config estática + métricas en vivo
                all_macs = set(static_map.keys()) | set(live_map.keys())
                clients_out = []
                for mac in all_macs:
                    static = static_map.get(mac, {})
                    live = live_map.get(mac, {})
                    # Online si tiene métricas recientes (últimos 5 min)
                    online = False
                    live_ts = live.get("ts")
                    if live_ts:
                        try:
                            age = (timezone.now() - live_ts).total_seconds()
                            online = age < 300
                        except Exception:
                            online = False

                    clients_out.append({
                        "mac": mac,
                        "ip": static.get("ip") or live.get("client_ip", ""),
                        "hostname": static.get("hostname", ""),
                        "essid": static.get("essid") or live.get("essid", ""),
                        "if_index": static.get("if_index"),
                        "online": online,
                        "signal": live.get("signal_dbm"),
                        "noise": live.get("noise_dbm"),
                        "ccq": live.get("ccq_pct"),
                        "tx_rate": live.get("tx_rate_bps"),
                        "rx_rate": live.get("rx_rate_bps"),
                        "snr": live.get("snr_db"),
                        "first_seen": static.get("first_seen"),
                        "last_seen": static.get("last_seen"),
                        "ts": live_ts.isoformat() if live_ts else None,
                    })

                # Ordenar: online primero, luego por MAC
                clients_out.sort(key=lambda c: (not c["online"], c["mac"]))
                ap_clients_payload = clients_out

                # Actualizar el flag is_access_point
                # (hay clientes conectados ahora mismo)
                has_active_clients = any(c["online"] for c in clients_out)

            result.append({
                "id": device.id,
                "name": device.name,
                "ip": device.ip,
                "role": device.device_role,
                "vendor": device.vendor,
                "model": device.device_model.name if device.device_model else None,
                "location": device.location,
                "has_traffic": has_traffic,
                # Flags nuevos:
                "has_health_metrics": has_health,
                "available_health_metrics": available_health,
                "has_radio_metrics": has_radio,
                "available_radio_metrics": available_radio,
                "is_wireless_link": is_wireless,
                "wireless_info": wireless_info,
                # Payloads:
                "icmp": icmp_payload,
                "traffic": traffic_payload,
                "health": health_payload,
                "tcp": tcp_payload,
                "dashboard_traffic": dashboard_traffic,
                "radio": radio_payload,
                "has_interfaces_support": model_has_interfaces,
                "monitor_interfaces_enabled": bool(device.monitor_interfaces),
                "is_access_point": bool(ap_clients_payload and len(ap_clients_payload) > 0),
                "ap_clients": ap_clients_payload,
                "has_active_ap_clients": has_active_clients if is_wireless else False,
                "monitor_health_enabled": bool(device.monitor_health),
            })

        return JsonResponse({
            "timestamp": timezone.now().isoformat(),
            "devices": result,
            "_debug": {
                "count_devices": len(result),
                "count_icmp": len(icmp_data),
                "count_traffic": len(traffic_data),
                "count_health": len(health_data),
                "count_tcp": len(tcp_data),
                "count_radio": len(radio_data),
                "client_ip": request.META.get("REMOTE_ADDR"),
                "forwarded_for": request.META.get("HTTP_X_FORWARDED_FOR"),
            },
        })

    except Exception as e:
        log.exception("Error en monitor_devices_live: %s", e)
        return JsonResponse({
            "timestamp": timezone.now().isoformat(),
            "devices": [],
            "error": str(e),
            "traceback": traceback.format_exc() if settings.DEBUG else None,
        }, status=500)


# ============================================================
# DASHBOARD — SPARKLINE
# ============================================================
@login_required
def dashboard_sparkline(request):
    """
    Devuelve la serie temporal para los sparklines del dashboard.

    Query params:
        device_id (int, requerido): ID del equipo.
        metric (str, requerido): traffic_in | traffic_out | signal
            | ccq | cpu | mem | latency.
        minutes (int, opcional, default 10): ventana (5-60 min).

    Returns:
        JsonResponse: {points: [{t, v}, ...], metric, minutes}
    """
    from .services import influx_reader

    device_id = request.GET.get("device_id")
    metric = request.GET.get("metric", "traffic_in")
    minutes = request.GET.get("minutes", "10")

    if not device_id:
        return JsonResponse({"error": "device_id requerido"}, status=400)

    try:
        device = Device.objects.get(pk=int(device_id))
    except (Device.DoesNotExist, ValueError):
        return JsonResponse({"error": "Equipo no encontrado"}, status=404)

    # Para traffic_*: determinar interfaz
    interface_name = None
    if metric in ("traffic_in", "traffic_out"):
        iface = device.dashboard_interface_resolved
        if iface:
            interface_name = iface.if_name

    try:
        minutes_int = int(minutes)
    except (ValueError, TypeError):
        minutes_int = 10

    points = influx_reader.get_sparkline_series(
        device_name=device.name,
        metric=metric,
        interface_name=interface_name,
        minutes=minutes_int,
    )

    return JsonResponse({
        "points": points,
        "metric": metric,
        "minutes": max(5, min(60, minutes_int)),
    })