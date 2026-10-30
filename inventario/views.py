# inventario/views.py
"""
Vistas de la app `inventario`.

Incluye:
  - Equipos (Device):
      · device_list     — listado paginado (10/pág) con filtros y orden.
      · device_detail   — detalle de un equipo.
      · device_create   — crear equipo.
      · device_edit     — editar equipo.
      · device_delete   — eliminar equipo.
      · device_interfaces — gestionar interfaces (marcar monitored).
      · api_models      — API JSON de modelos por fabricante.

  - Modelos de equipo (DeviceModel) — NUEVO:
      · device_model_list   — listado paginado (10/pág).
      · device_model_create — crear modelo.
      · device_model_edit   — editar modelo.
      · device_model_delete — eliminar modelo (bloqueado si hay equipos).
      · device_model_toggle — activar/desactivar modelo.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.decorators import require_admin_or_super
from core.sorting import apply_sort, has_active_filters, ROLE_ORDER
from .forms import DeviceForm, DeviceModelForm
from .models import Device, DeviceModel, Interface


# ============================================================
# API: modelos filtrados por fabricante
# ============================================================
@login_required
def api_models(request):
    """
    Devuelve los modelos activos de un fabricante (JSON).

    Incluye flags de capacidad (`has_interfaces`, `has_chassis_oids`,
    `is_wireless_link`) para que el frontend pueda habilitar/deshabilitar
    los checkboxes y actualizar el panel de recomendaciones.

    Query params:
        vendor: nombre del fabricante (str).

    Returns:
        JsonResponse: {"models": [{id, name, has_interfaces,
                                    has_chassis_oids, is_wireless_link}, ...]}
    """
    from monitoreo.services.chassis_oids import CHASSIS_OIDS

    vendor = request.GET.get("vendor", "").strip()
    if not vendor:
        return JsonResponse({"models": []})

    models = DeviceModel.objects.filter(
        vendor=vendor, active=True
    ).order_by("name")

    vendor_lower = vendor.lower()
    vendor_has_chassis = bool(CHASSIS_OIDS.get(vendor_lower))

    result = []
    for m in models:
        result.append({
            "id": m.id,
            "name": m.name,
            "has_interfaces": bool(m.has_interfaces),
            "has_chassis_oids": bool(m.oids) or vendor_has_chassis,
            "is_wireless_link": bool(m.is_wireless_link),
        })

    return JsonResponse({"models": result})


# ============================================================
# LISTA DE EQUIPOS (con paginación)
# ============================================================
@login_required
def device_list(request):
    """
    Lista los equipos con filtros, ordenamiento y **paginación (10/pág)**.

    Filtros aceptados vía GET:
        q       — búsqueda por nombre, IP o ubicación.
        role    — rol del equipo (core/distribution/access/cpe).
        vendor  — fabricante.
        model   — ID del modelo.
        active  — "1" activos, "0" inactivos.
    """
    q = request.GET.get("q", "").strip()
    role_filter = request.GET.get("role", "")
    vendor_filter = request.GET.get("vendor", "")
    model_filter = request.GET.get("model", "")
    active_filter = request.GET.get("active", "")

    # Queryset base con anotaciones para evitar N+1
    devices = (
        Device.objects
        .select_related("device_model")
        .prefetch_related("interfaces")
        .annotate(
            role_order=ROLE_ORDER,
            iface_count=Count("interfaces", distinct=True),
            monitored_count=Count(
                "interfaces",
                filter=Q(interfaces__monitored=True),
                distinct=True,
            ),
        )
    )

    # Aplicar filtros
    if q:
        devices = devices.filter(
            Q(name__icontains=q)
            | Q(ip__icontains=q)
            | Q(location__icontains=q)
        )
    if role_filter:
        devices = devices.filter(device_role=role_filter)
    if vendor_filter:
        devices = devices.filter(vendor=vendor_filter)
    if model_filter:
        devices = devices.filter(device_model_id=model_filter)
    if active_filter == "1":
        devices = devices.filter(active=True)
    elif active_filter == "0":
        devices = devices.filter(active=False)

    # Ordenamiento
    SORTABLE = {
        "nombre":     "name",
        "ip":         "ip",
        "tipo":       "device_type",
        "rol":        "role_order",
        "vendor":     "vendor",
        "modelo":     "device_model__name",
        "ubicacion":  "location",
        "interfaces": "iface_count",
        "activo":     "active",
    }
    devices, sort_key, order = apply_sort(request, devices, SORTABLE, "name")

    # Paginación: 10 equipos por página
    paginator = Paginator(devices, 10)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    # ========================================================
    # Calcular contadores de clientes AP para la página actual
    # ========================================================
    # Los radio-enlaces no tienen interfaces tradicionales útiles;
    # en su lugar se cuenta la cantidad de clientes AP (online/total).
    # Solo se calcula para los devices de la página (máx. 10), así
    # que el coste es despreciable.
    from datetime import datetime

    now = timezone.now()

    for device in page_obj.object_list:
        if device.is_wireless_link:
            clients = device.ap_interfaces or []
            device.ap_clients_total = len(clients)
            online = 0
            for c in clients:
                last_seen = c.get("last_seen")
                if not last_seen:
                    continue
                try:
                    ls_dt = datetime.fromisoformat(
                        last_seen.replace("Z", "+00:00")
                    )
                    if ls_dt.tzinfo is None:
                        ls_dt = timezone.make_aware(ls_dt)
                    if (now - ls_dt).total_seconds() < 300:  # 5 min
                        online += 1
                except (ValueError, TypeError):
                    pass
            device.ap_clients_online = online
        else:
            device.ap_clients_total = 0
            device.ap_clients_online = 0

    # Fabricantes disponibles (para el filtro)
    vendor_choices = (
        Device.objects
        .exclude(vendor__isnull=True)
        .exclude(vendor="")
        .values_list("vendor", flat=True)
        .distinct()
        .order_by("vendor")
    )

    # Modelos del fabricante seleccionado (si aplica)
    if vendor_filter:
        model_choices = DeviceModel.objects.filter(
            vendor=vendor_filter, active=True
        ).order_by("name")
    else:
        model_choices = DeviceModel.objects.none()

    context = {
        "devices": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "q": q,
        "role_filter": role_filter,
        "vendor_filter": vendor_filter,
        "model_filter": model_filter,
        "active_filter": active_filter,
        "sort_key": sort_key,
        "order": order,
        "role_choices": Device.ROLE_CHOICES,
        "vendor_choices": vendor_choices,
        "model_choices": model_choices,
        "count_all": Device.objects.count(),
        "count_active": Device.objects.filter(active=True).count(),
        "count_core": Device.objects.filter(
            active=True, device_role__in=["core", "distribution"]
        ).count(),
        "has_filters": has_active_filters(
            request, ["q", "role", "vendor", "model", "active"]
        ),
    }
    return render(request, "inventario/device_list.html", context)


# ============================================================
# DETALLE DE EQUIPO
# ============================================================
@login_required
def device_detail(request, device_id):
    """
    Muestra el detalle de un equipo, sus interfaces y sus últimas alertas.
    """
    device = get_object_or_404(
        Device.objects.select_related("device_model"), pk=device_id
    )
    interfaces = device.interfaces.all().order_by("if_index")
    monitored = interfaces.filter(monitored=True)
    alerts = device.alerts.order_by("-created_at")[:10]

    # Alertas activas vs totales
    active_alerts_count = device.alerts.filter(status="activa").count()
    total_alerts_count = device.alerts.count()

    # Últimos 5 discovery jobs
    discovery_jobs = device.discovery_jobs.order_by("-started_at")[:5]

    context = {
        "device": device,
        "interfaces": interfaces,
        "monitored_count": monitored.count(),
        "total_count": interfaces.count(),
        "alerts": alerts,
        "active_alerts_count": active_alerts_count,
        "total_alerts_count": total_alerts_count,
        "discovery_jobs": discovery_jobs,
    }
    return render(request, "inventario/device_detail.html", context)


# ============================================================
# CREAR EQUIPO
# ============================================================
@login_required
@require_admin_or_super()
def device_create(request):
    """Crea un nuevo equipo."""
    if request.method == "POST":
        form = DeviceForm(request.POST)
        if form.is_valid():
            d = form.save()
            messages.success(request, f"Equipo '{d.name}' creado.")
            return redirect("inventario:device_detail", device_id=d.id)
    else:
        form = DeviceForm()

    return render(request, "inventario/device_form.html", {
        "form": form,
        "title": "Nuevo equipo",
        "is_edit": False,
    })


# ============================================================
# EDITAR EQUIPO
# ============================================================
@login_required
@require_admin_or_super()
def device_edit(request, device_id):
    """Edita un equipo existente."""
    device = get_object_or_404(Device, pk=device_id)

    if request.method == "POST":
        form = DeviceForm(request.POST, instance=device)
        if form.is_valid():
            form.save()
            messages.success(request, f"Equipo '{device.name}' actualizado.")
            return redirect("inventario:device_detail", device_id=device.id)
    else:
        form = DeviceForm(instance=device)

    return render(request, "inventario/device_form.html", {
        "form": form,
        "device": device,
        "title": f"Editar: {device.name}",
        "is_edit": True,
    })


# ============================================================
# ELIMINAR EQUIPO
# ============================================================
@login_required
@require_admin_or_super()
def device_delete(request, device_id):
    """Elimina un equipo (con confirmación previa)."""
    device = get_object_or_404(Device, pk=device_id)

    if request.method == "POST":
        name = device.name
        device.delete()
        messages.success(request, f"Equipo '{name}' eliminado.")
        return redirect("inventario:device_list")

    return render(request, "inventario/device_confirm_delete.html", {
        "device": device,
    })


# ============================================================
# GESTIONAR INTERFACES DE UN EQUIPO
# ============================================================
@login_required
def device_interfaces(request, device_id):
    """
    Gestiona las interfaces de un equipo.

    Comportamiento según el tipo de modelo:
      - **IF-MIB** (has_interfaces=True): tabla de interfaces tradicionales
        con checkbox de `monitored`. Editable por admin/superadmin.
      - **Radioenlace** (is_wireless_link=True): tabla de clientes AP
        con métricas en vivo (polling al endpoint de monitor_live).
      - **Ambos**: muestra dos tabs intercambiables.
      - **Ninguno**: mensaje central "el equipo no soporta interfaces".

    En todos los casos, el botón de Discovery llama al endpoint correcto
    (IF-MIB → run_discovery, wireless → run_ap_discovery).

    POST: solo procesa la actualización de `monitored` de la tab IF-MIB.
    La tab AP no usa POST (los clientes se descubren automáticamente).
    """
    from datetime import datetime, timedelta
    from django.utils import timezone

    device = get_object_or_404(Device, pk=device_id)

    # ============================================================
    # POST: actualizar interfaces monitoreadas (solo IF-MIB)
    # ============================================================
    if request.method == "POST":
        if not (
            request.user.is_superuser
            or request.user.groups.filter(name="Administrador").exists()
        ):
            raise PermissionDenied("No tienes permisos.")

        # Solo procesar si el modelo soporta IF-MIB
        if not device.has_interfaces_support:
            messages.warning(
                request,
                "El modelo de este equipo no soporta interfaces IF-MIB."
            )
            return redirect(
                "inventario:device_interfaces", device_id=device_id
            )

        selected_ids = set(request.POST.getlist("monitored"))
        interfaces = device.interfaces.all()
        updated = 0

        for iface in interfaces:
            should = str(iface.id) in selected_ids
            if iface.monitored != should:
                iface.monitored = should
                iface.save()
                updated += 1

        if updated:
            messages.success(request, f"Se actualizaron {updated} interfaz(es).")
        else:
            messages.info(request, "No hubo cambios.")

        return redirect("inventario:device_interfaces", device_id=device_id)

    # ============================================================
    # Determinar qué tabs mostrar
    # ============================================================
    has_ifaces = bool(device.has_interfaces_support)
    is_wireless = bool(device.is_wireless_link)
    monitors_ifaces = bool(device.monitor_interfaces)

    show_iface_tab = has_ifaces and monitors_ifaces
    show_ap_tab = is_wireless
    show_none = not show_iface_tab and not show_ap_tab

    # ============================================================
    # Contexto IF-MIB (solo si aplica)
    # ============================================================
    context = {
        "device": device,
        "is_wireless_link": is_wireless,
        "has_interfaces_support": has_ifaces,
        "monitor_interfaces": monitors_ifaces,
        "show_iface_tab": show_iface_tab,
        "show_ap_tab": show_ap_tab,
        "show_none": show_none,
        "show_both_tabs": show_iface_tab and show_ap_tab,
    }

    if show_iface_tab:
        interfaces = device.interfaces.all()

        search = request.GET.get("q", "").strip()
        monitored_filter = request.GET.get("monitored", "")
        status_filter = request.GET.get("status", "")
        type_filter = request.GET.get("type", "")
        has_speed_filter = request.GET.get("has_speed", "")

        if search:
            interfaces = interfaces.filter(
                Q(if_name__icontains=search) | Q(if_alias__icontains=search)
            )
        if monitored_filter == "1":
            interfaces = interfaces.filter(monitored=True)
        elif monitored_filter == "0":
            interfaces = interfaces.filter(monitored=False)
        if status_filter == "up":
            interfaces = interfaces.filter(oper_status=True)
        elif status_filter == "down":
            interfaces = interfaces.filter(oper_status=False)
        if type_filter:
            interfaces = interfaces.filter(if_type=type_filter)
        if has_speed_filter == "1":
            interfaces = interfaces.filter(if_speed_bps__gt=0)
        elif has_speed_filter == "0":
            interfaces = interfaces.filter(if_speed_bps=0)

        SORTABLE = {
            "index":     "if_index",
            "nombre":    "if_name",
            "alias":     "if_alias",
            "tipo":      "if_type",
            "velocidad": "if_speed_bps",
            "estado":    "oper_status",
            "monitor":   "monitored",
        }
        interfaces, sort_key, order = apply_sort(
            request, interfaces, SORTABLE, "if_index"
        )

        type_choices = list(
            device.interfaces.values_list("if_type", flat=True).distinct()
        )

        context.update({
            "interfaces": interfaces,
            "sort_key": sort_key,
            "order": order,
            "search": search,
            "monitored_filter": monitored_filter,
            "status_filter": status_filter,
            "type_filter": type_filter,
            "has_speed_filter": has_speed_filter,
            "type_choices": sorted([t for t in type_choices if t]),
            "count_all": device.interfaces.count(),
            "count_monitored": device.interfaces.filter(monitored=True).count(),
            "count_up": device.interfaces.filter(oper_status=True).count(),
            "has_filters": has_active_filters(
                request, ["q", "monitored", "status", "type", "has_speed"]
            ),
        })

    # ============================================================
    # Contexto AP (solo si aplica)
    # ============================================================
    if show_ap_tab:
        now = timezone.now()
        clients_raw = device.ap_interfaces or []

        # Enriquecer con online/offline
        enriched = []
        online_count = 0
        for c in clients_raw:
            last_seen_iso = c.get("last_seen")
            online = False
            if last_seen_iso:
                try:
                    ls_dt = datetime.fromisoformat(
                        last_seen_iso.replace("Z", "+00:00")
                    )
                    if ls_dt.tzinfo is None:
                        ls_dt = timezone.make_aware(ls_dt)
                    online = (now - ls_dt).total_seconds() < 300
                except (ValueError, TypeError):
                    online = False

            if online:
                online_count += 1

            enriched.append({
                "mac": c.get("mac", ""),
                "ip": c.get("ip", ""),
                "hostname": c.get("hostname", ""),
                "essid": c.get("essid", ""),
                "if_index": c.get("if_index"),
                "first_seen": c.get("first_seen"),
                "last_seen": last_seen_iso,
                "online": online,
            })

        # Orden: online primero, luego MAC
        enriched.sort(key=lambda x: (not x["online"], x["mac"]))

        context.update({
            "ap_clients": enriched,
            "ap_clients_total": len(enriched),
            "ap_clients_online": online_count,
        })

    return render(request, "inventario/device_interfaces.html", context)


# ============================================================
# MODELOS DE EQUIPO — LISTA PAGINADA
# ============================================================
@login_required
def device_model_list(request):
    """
    Lista los modelos de equipo con filtros, ordenamiento y **paginación**.

    Filtros aceptados vía GET:
        q        — búsqueda por nombre o descripción.
        vendor   — fabricante.
        wireless — "1" radio-enlaces, "0" no radio-enlaces.
        active   — "1" activos, "0" inactivos.

    Stats mostradas arriba de la tabla:
        count_all          — total de modelos.
        count_active       — modelos activos.
        count_wireless     — modelos marcados como radio-enlace.
        count_custom_oids  — modelos con al menos un OID propio.
    """
    q = request.GET.get("q", "").strip()
    vendor_filter = request.GET.get("vendor", "")
    wireless_filter = request.GET.get("wireless", "")
    active_filter = request.GET.get("active", "")

    # Queryset base con conteo de equipos asociados
    models_qs = DeviceModel.objects.annotate(
        devices_count=Count("devices", distinct=True),
        active_devices_count=Count(
            "devices",
            filter=Q(devices__active=True),
            distinct=True,
        ),
    )

    # Aplicar filtros
    if q:
        models_qs = models_qs.filter(
            Q(name__icontains=q) | Q(description__icontains=q)
        )
    if vendor_filter:
        models_qs = models_qs.filter(vendor=vendor_filter)
    if wireless_filter == "1":
        models_qs = models_qs.filter(is_wireless_link=True)
    elif wireless_filter == "0":
        models_qs = models_qs.filter(is_wireless_link=False)
    if active_filter == "1":
        models_qs = models_qs.filter(active=True)
    elif active_filter == "0":
        models_qs = models_qs.filter(active=False)

    # Ordenamiento
    SORTABLE = {
        "fabricante":  "vendor",
        "modelo":      "name",
        "radio":       "is_wireless_link",
        "equipos":     "devices_count",
        "activo":      "active",
        "actualizado": "updated_at",
    }
    models_qs, sort_key, order = apply_sort(
        request, models_qs, SORTABLE, "vendor"
    )

    # Paginación: 10 modelos por página
    paginator = Paginator(models_qs, 10)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    # Conteo de modelos con OIDs personalizados.
    # Se hace en Python porque `exclude(oids={})` no es portable
    # entre MySQL/PostgreSQL con JSONField.
    count_custom_oids = sum(
        1 for m in DeviceModel.objects.only("oids") if m.oids
    )

    context = {
        "models": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "q": q,
        "vendor_filter": vendor_filter,
        "wireless_filter": wireless_filter,
        "active_filter": active_filter,
        "sort_key": sort_key,
        "order": order,
        "vendor_choices": DeviceModel.VENDOR_CHOICES,
        "count_all": DeviceModel.objects.count(),
        "count_active": DeviceModel.objects.filter(active=True).count(),
        "count_wireless": DeviceModel.objects.filter(
            is_wireless_link=True
        ).count(),
        "count_custom_oids": count_custom_oids,
        "has_filters": has_active_filters(
            request, ["q", "vendor", "wireless", "active"]
        ),
    }
    return render(request, "inventario/device_model_list.html", context)


# ============================================================
# MODELOS DE EQUIPO — CREAR
# ============================================================
@login_required
@require_admin_or_super()
def device_model_create(request):
    """Crea un nuevo modelo de equipo con sus OIDs."""
    if request.method == "POST":
        form = DeviceModelForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(
                request,
                f"Modelo '{obj.name}' ({obj.vendor}) creado.",
            )
            return redirect("inventario:device_model_list")
    else:
        form = DeviceModelForm()

    return render(request, "inventario/device_model_form.html", {
        "form": form,
        "title": "Nuevo modelo de equipo",
        "is_edit": False,
        "devices_count": 0,
    })


# ============================================================
# MODELOS DE EQUIPO — EDITAR
# ============================================================
@login_required
@require_admin_or_super()
def device_model_edit(request, model_id):
    """
    Edita un modelo de equipo existente.

    Si el modelo ya tiene equipos asociados, el campo `vendor` se
    muestra deshabilitado (para no romper la coherencia con
    `Device.vendor`).
    """
    obj = get_object_or_404(DeviceModel, pk=model_id)

    if request.method == "POST":
        form = DeviceModelForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, f"Modelo '{obj.name}' actualizado.")
            return redirect("inventario:device_model_list")
    else:
        form = DeviceModelForm(instance=obj)

    return render(request, "inventario/device_model_form.html", {
        "form": form,
        "model_obj": obj,
        "title": f"Editar: {obj.vendor} - {obj.name}",
        "is_edit": True,
        "devices_count": obj.devices.count(),
    })


# ============================================================
# MODELOS DE EQUIPO — ELIMINAR
# ============================================================
@login_required
@require_admin_or_super()
def device_model_delete(request, model_id):
    """
    Elimina un modelo (con confirmación).

    Regla de negocio: si hay equipos usando el modelo, **se bloquea**
    la eliminación. Se sugiere desactivarlo en su lugar (soft delete).
    """
    obj = get_object_or_404(DeviceModel, pk=model_id)
    devices_count = obj.devices.count()

    if request.method == "POST":
        if devices_count > 0:
            messages.error(
                request,
                f"No se puede eliminar: hay {devices_count} equipo(s) "
                "que usan este modelo. Desactívalo en su lugar.",
            )
            return redirect(
                "inventario:device_model_edit", model_id=obj.id
            )

        name = obj.name
        obj.delete()
        messages.success(request, f"Modelo '{name}' eliminado.")
        return redirect("inventario:device_model_list")

    return render(request, "inventario/device_model_confirm_delete.html", {
        "model_obj": obj,
        "devices_count": devices_count,
    })


# ============================================================
# MODELOS DE EQUIPO — TOGGLE ACTIVO/INACTIVO
# ============================================================
@login_required
@require_admin_or_super()
def device_model_toggle(request, model_id):
    """
    Activa o desactiva un modelo (POST).

    Es útil para retirar un modelo sin perderlo ni eliminar sus
    equipos asociados.
    """
    if request.method != "POST":
        return redirect("inventario:device_model_list")

    obj = get_object_or_404(DeviceModel, pk=model_id)
    obj.active = not obj.active
    obj.save(update_fields=["active", "updated_at"])

    state = "activado" if obj.active else "desactivado"
    messages.success(request, f"Modelo '{obj.name}' {state}.")
    return redirect(
        request.META.get("HTTP_REFERER", "inventario:device_model_list")
    )


# ============================================================
# MODELO — EXPORTAR A JSON
# ============================================================
@login_required
def device_model_export(request, model_id):
    """
    Exporta un modelo individual a un archivo JSON descargable.

    El JSON contiene todos los campos configurables (excluyendo los
    campos de auditoría `created_at` y `updated_at`, que se regeneran
    al importar).

    Args:
        request: HttpRequest.
        model_id: ID del modelo.

    Returns:
        HttpResponse: archivo .json con Content-Disposition attachment.
    """
    import json
    from django.http import HttpResponse

    obj = get_object_or_404(DeviceModel, pk=model_id)

    data = {
        "vendor": obj.vendor,
        "name": obj.name,
        "oids": obj.oids or {},
        "radio_oids": obj.radio_oids or {},
        "description": obj.description or "",
        "is_wireless_link": bool(obj.is_wireless_link),
        "has_interfaces": bool(obj.has_interfaces),
        "active": bool(obj.active),
    }

    safe_vendor = "".join(c for c in obj.vendor if c.isalnum() or c in "-_")
    safe_name = "".join(c for c in obj.name if c.isalnum() or c in "-_ ")
    safe_name = safe_name.strip().replace(" ", "_")
    filename = f"model_{safe_vendor}_{safe_name}.json"

    response = HttpResponse(
        json.dumps(data, indent=2, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ============================================================
# MODELO — IMPORTAR DESDE JSON (individual o masivo)
# ============================================================
# Tamaño máximo aceptado para el archivo JSON (5 MB).
# Un modelo ocupa ~500 B, así que 5 MB permite ~10,000 modelos.
MAX_IMPORT_SIZE = 5 * 1024 * 1024


@login_required
@require_admin_or_super()
def device_models_import(request):
    """
    Importa uno o varios modelos desde un archivo JSON.

    Flujo de dos pasadas:
      - **Primera pasada**: sin `overwrite_names`. Si hay conflictos
        (modelos existentes por nombre), devuelve `ok=False` con la
        lista de conflictos para que el frontend muestre el modal.
      - **Segunda pasada**: con `overwrite_names` (posiblemente vacío).
        El backend autoriza los sobrescritos y SALTA el resto. Ya no
        vuelve a devolver conflictos → evita el loop infinito.

    Args:
        request: HttpRequest (POST).
            form-data:
              - file: el archivo JSON.
              - overwrite_names: JSON array con nombres autorizados a
                sobrescribir. Presencia del campo (aunque sea "[]")
                indica que es la segunda pasada.

    Returns:
        JsonResponse con:
          - ok: bool
          - created: list de nombres creados
          - updated: list de nombres actualizados
          - skipped: list de {name, reason}
          - conflicts: list de nombres en conflicto (si ok=False)
          - error: str (si ok=False por error)
    """
    import json
    from django.http import JsonResponse

    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido"}, status=405)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"ok": False, "error": "No se subió ningún archivo."})

    # ---- 0. Límite de tamaño ----
    if uploaded.size > MAX_IMPORT_SIZE:
        return JsonResponse({
            "ok": False,
            "error": (
                f"Archivo demasiado grande ({uploaded.size // 1024} KB). "
                f"Máximo {MAX_IMPORT_SIZE // (1024 * 1024)} MB."
            ),
        })

    # ---- 1. Parsear JSON ----
    try:
        raw = uploaded.read().decode("utf-8-sig")  # tolera BOM
        data = json.loads(raw)
    except UnicodeDecodeError:
        return JsonResponse({
            "ok": False,
            "error": "El archivo no está en UTF-8. Guarda el JSON con esa codificación.",
        })
    except json.JSONDecodeError as e:
        return JsonResponse({
            "ok": False,
            "error": f"JSON inválido: {e.msg} (línea {e.lineno}, columna {e.colno}).",
        })

    # Normalizar a lista
    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = data
    else:
        return JsonResponse({
            "ok": False,
            "error": "El JSON debe ser un objeto o una lista de objetos.",
        })

    if len(items) == 0:
        return JsonResponse({
            "ok": True,
            "created": [], "updated": [], "skipped": [],
            "message": "El archivo no contiene modelos.",
        })

    # ---- 2. Validar cada item ----
    validated = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return JsonResponse({
                "ok": False,
                "error": f"El elemento #{i+1} no es un objeto JSON.",
            })
        vendor = (item.get("vendor") or "").strip()
        name = (item.get("name") or "").strip()
        if not vendor or not name:
            return JsonResponse({
                "ok": False,
                "error": f"El elemento #{i+1} no tiene 'vendor' o 'name'.",
            })

        for field in ("oids", "radio_oids"):
            value = item.get(field) or {}
            if not isinstance(value, dict):
                return JsonResponse({
                    "ok": False,
                    "error": (
                        f"El campo '{field}' del modelo '{name}' debe ser un objeto JSON."
                    ),
                })
            for k, v in value.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    return JsonResponse({
                        "ok": False,
                        "error": (
                            f"El campo '{field}' del modelo '{name}' debe tener "
                            f"claves y valores string."
                        ),
                    })

        validated.append({
            "vendor": vendor,
            "name": name,
            "oids": item.get("oids") or {},
            "radio_oids": item.get("radio_oids") or {},
            "description": (item.get("description") or "").strip(),
            "is_wireless_link": bool(item.get("is_wireless_link", False)),
            "has_interfaces": bool(item.get("has_interfaces", True)),
            "active": bool(item.get("active", True)),
        })

    # ---- 3. Detectar conflictos (por nombre) ----
    # Uso setdefault para conservar el PRIMER modelo si hay nombres
    # duplicados en la BD (vendor distinto, mismo name). Se actualiza
    # solo el primero; el resto queda intacto.
    incoming_names = {v["name"] for v in validated}
    existing = {}
    for m in DeviceModel.objects.filter(name__in=incoming_names):
        existing.setdefault(m.name, m)

    # ¿Es primera pasada o segunda?
    # `request.POST.get()` devuelve None si el campo no fue enviado
    # (primera pasada), y "" o "[]" o '["a"]' si fue enviado (segunda).
    overwrite_raw = request.POST.get("overwrite_names")
    is_second_pass = overwrite_raw is not None

    overwrite_names = set()
    if overwrite_raw:
        try:
            parsed = json.loads(overwrite_raw)
            if isinstance(parsed, list):
                overwrite_names = {str(x) for x in parsed}
        except (ValueError, TypeError):
            pass  # JSON malformado → set vacío

    # Primera pasada con conflictos → devolver lista al frontend
    if not is_second_pass:
        conflicts = [
            v["name"] for v in validated
            if v["name"] in existing
        ]
        if conflicts:
            return JsonResponse({
                "ok": False,
                "conflicts": conflicts,
                "message": (
                    f"{len(conflicts)} modelo(s) ya existen en la base de datos. "
                    "Selecciona cuáles deseas sobrescribir, o continúa sin "
                    "sobrescribir ninguno para crear solo los nuevos."
                ),
            })

    # ---- 4. Crear / actualizar / saltar ----
    created, updated, skipped = [], [], []

    for v in validated:
        name = v["name"]
        if name in existing:
            if name in overwrite_names:
                # Autorizado → actualizar
                try:
                    obj = existing[name]
                    obj.vendor = v["vendor"]
                    obj.oids = v["oids"]
                    obj.radio_oids = v["radio_oids"]
                    obj.description = v["description"]
                    obj.is_wireless_link = v["is_wireless_link"]
                    obj.has_interfaces = v["has_interfaces"]
                    obj.active = v["active"]
                    obj.save()
                    updated.append(name)
                except Exception as e:
                    skipped.append({
                        "name": name,
                        "reason": f"error al actualizar: {e}",
                    })
            else:
                # No autorizado → saltar (segunda pasada sin marcar)
                skipped.append({
                    "name": name,
                    "reason": "no seleccionado para sobrescribir",
                })
        else:
            # Nuevo → crear
            try:
                DeviceModel.objects.create(
                    vendor=v["vendor"],
                    name=name,
                    oids=v["oids"],
                    radio_oids=v["radio_oids"],
                    description=v["description"],
                    is_wireless_link=v["is_wireless_link"],
                    has_interfaces=v["has_interfaces"],
                    active=v["active"],
                )
                created.append(name)
            except Exception as e:
                skipped.append({
                    "name": name,
                    "reason": f"error al crear: {e}",
                })

    return JsonResponse({
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "message": (
            f"{len(created)} creado(s), {len(updated)} actualizado(s), "
            f"{len(skipped)} saltado(s)."
        ),
    })


# ============================================================
# MODELOS — EXPORTAR MASIVO (selección o todos)
# ============================================================
@login_required
def device_models_export_bulk(request):
    """
    Exporta varios modelos a un único archivo JSON (lista).

    Query params:
        ids: lista de IDs separados por coma. Si está vacío,
             exporta TODOS los modelos.

    Returns:
        HttpResponse: archivo .json con lista de modelos.
    """
    import json
    from django.http import HttpResponse

    ids_param = request.GET.get("ids", "").strip()

    if ids_param:
        # Parseo tolerante: acepta "1,2,3" y descarta valores no numéricos
        # sin fallar toda la lista.
        ids = []
        for chunk in ids_param.split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                ids.append(int(chunk))
        models = DeviceModel.objects.filter(id__in=ids).order_by("vendor", "name")
    else:
        models = DeviceModel.objects.all().order_by("vendor", "name")

    data = []
    for obj in models:
        data.append({
            "vendor": obj.vendor,
            "name": obj.name,
            "oids": obj.oids or {},
            "radio_oids": obj.radio_oids or {},
            "description": obj.description or "",
            "is_wireless_link": bool(obj.is_wireless_link),
            "has_interfaces": bool(obj.has_interfaces),
            "active": bool(obj.active),
        })

    filename = (
        f"device_models_{len(data)}.json"
        if not ids_param
        else f"device_models_selected_{len(data)}.json"
    )

    response = HttpResponse(
        json.dumps(data, indent=2, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ============================================================
# MODELO — PARSEAR JSON (sin escribir a la BD)
# ============================================================
@login_required
@require_admin_or_super()
def device_models_parse(request):
    """
    Verifica si un `name` de modelo ya existe en la base de datos.

    Usado por el form de crear/editar modelo para pre-chequear conflictos
    de nombre ANTES de rellenar los campos del formulario. NO escribe
    nada a la BD.

    Args:
        request: HttpRequest (POST, JSON)
            - name: nombre del modelo a verificar.
            - current_id: ID del modelo en edición (None si es creación).

    Returns:
        JsonResponse:
          - ok: bool
          - conflict: None | {type: "create"|"edit", name, other_id}
    """
    import json
    from django.http import JsonResponse

    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido"}, status=405)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    name = (payload.get("name") or "").strip()
    current_id = payload.get("current_id")

    if not name:
        return JsonResponse({"ok": False, "error": "Falta 'name'"}, status=400)

    # Excluir el modelo actual si estamos en modo edición
    existing = DeviceModel.objects.filter(name=name)
    if current_id:
        try:
            existing = existing.exclude(pk=int(current_id))
        except (ValueError, TypeError):
            pass

    conflict = None
    first = existing.first()
    if first:
        conflict = {
            "type": "create" if not current_id else "edit",
            "name": first.name,
            "other_id": first.id,
        }

    return JsonResponse({"ok": True, "conflict": conflict})


# ============================================================
# EQUIPO — EXPORTAR A JSON
# ============================================================
@login_required
def device_export(request, device_id):
    """
    Exporta un equipo a un archivo JSON descargable.

    El JSON incluye el nombre del modelo (portable entre instancias),
    no el ID (que no lo es).

    Args:
        request: HttpRequest.
        device_id: ID del equipo.

    Returns:
        HttpResponse: archivo .json con Content-Disposition attachment.
    """
    import json
    from django.http import HttpResponse

    device = get_object_or_404(Device, pk=device_id)

    data = {
        "name": device.name,
        "ip": device.ip,
        "device_type": device.device_type,
        "device_role": device.device_role,
        "vendor": device.vendor,
        "device_model_name": (
            device.device_model.name if device.device_model else None
        ),
        "location": device.location,
        "snmp_version": device.snmp_version,
        "snmp_community": device.snmp_community or "",
        "snmp_user": device.snmp_user or "",
        "snmp_auth": device.snmp_auth or "",
        "snmp_priv": device.snmp_priv or "",
        "tcp_ports": device.tcp_ports or "",
        "monitor_interfaces": bool(device.monitor_interfaces),
        "monitor_health": bool(device.monitor_health),
        "active": bool(device.active),
    }

    safe_name = "".join(
        c for c in device.name if c.isalnum() or c in "-_ "
    ).strip().replace(" ", "_")
    filename = f"device_{safe_name}.json"

    response = HttpResponse(
        json.dumps(data, indent=2, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ============================================================
# EQUIPO — VALIDAR IMPORT (sin escribir a la BD)
# ============================================================
@login_required
@require_admin_or_super()
def device_import_check(request):
    """
    Valida un JSON de import de equipo (sin escribir a la BD).

    Verifica:
      - Campos mínimos presentes (name, ip, vendor, device_model_name).
      - El modelo existe y está activo en el vendor indicado.
      - Conflictos por `name` (otro equipo).
      - Conflictos por `ip` (otro equipo).
      - Info de capacidades del modelo (has_interfaces, has_chassis_oids,
        is_wireless_link) para que el frontend ajuste los checkboxes.

    Args:
        request: HttpRequest (POST, JSON).
            - name, ip, vendor, device_model_name, current_id.

    Returns:
        JsonResponse:
          - ok: bool
          - errors: list[str]
          - model_info: {id, name, has_interfaces, has_chassis_oids, is_wireless_link}
          - conflicts: {name: {...}, ip: {...}}
    """
    import json
    from django.http import JsonResponse
    from monitoreo.services.chassis_oids import CHASSIS_OIDS

    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    name = (data.get("name") or "").strip()
    ip = (data.get("ip") or "").strip()
    vendor = (data.get("vendor") or "").strip()
    model_name = (data.get("device_model_name") or "").strip()
    current_id = data.get("current_id")

    errors = []
    conflicts = {}
    model_info = None

    # Validaciones básicas
    if not name:
        errors.append("El campo 'name' es obligatorio.")
    if not ip:
        errors.append("El campo 'ip' es obligatorio.")
    if not vendor:
        errors.append("El campo 'vendor' es obligatorio.")
    if not model_name:
        errors.append("El campo 'device_model_name' es obligatorio.")

    # Validar que el modelo existe y obtener info
    if vendor and model_name:
        try:
            model = DeviceModel.objects.get(
                vendor=vendor, name=model_name, active=True
            )
            vendor_lower = (model.vendor or "").lower()
            has_chassis = bool(model.oids) or bool(
                CHASSIS_OIDS.get(vendor_lower)
            )
            model_info = {
                "id": model.id,
                "name": model.name,
                "has_interfaces": bool(model.has_interfaces),
                "has_chassis_oids": has_chassis,
                "is_wireless_link": bool(model.is_wireless_link),
            }
        except DeviceModel.DoesNotExist:
            errors.append(
                f"No existe un modelo activo llamado '{model_name}' "
                f"para el fabricante '{vendor}'. Regístralo primero."
            )

    # Conflicto por name
    if name:
        qs = Device.objects.filter(name=name)
        if current_id:
            try:
                qs = qs.exclude(pk=int(current_id))
            except (ValueError, TypeError):
                pass
        first = qs.first()
        if first:
            conflicts["name"] = {"value": name, "other_id": first.id}

    # Conflicto por IP
    if ip:
        qs = Device.objects.filter(ip=ip)
        if current_id:
            try:
                qs = qs.exclude(pk=int(current_id))
            except (ValueError, TypeError):
                pass
        first = qs.first()
        if first:
            conflicts["ip"] = {"value": ip, "other_id": first.id}

    return JsonResponse({
        "ok": len(errors) == 0,
        "errors": errors,
        "model_info": model_info,
        "conflicts": conflicts,
    })


# ============================================================
# EQUIPO — EXPORTAR MASIVO
# ============================================================
@login_required
def device_export_bulk(request):
    """
    Exporta varios equipos a un único archivo JSON (lista).

    Query params:
        ids: lista de IDs separados por coma. Si está vacío,
             exporta TODOS los equipos.

    Returns:
        HttpResponse: archivo .json con lista de equipos.
    """
    import json
    from django.http import HttpResponse

    ids_param = request.GET.get("ids", "").strip()

    if ids_param:
        ids = []
        for chunk in ids_param.split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                ids.append(int(chunk))
        devices = (
            Device.objects
            .filter(id__in=ids)
            .select_related("device_model")
            .order_by("name")
        )
    else:
        devices = (
            Device.objects
            .select_related("device_model")
            .order_by("name")
        )

    data = []
    for d in devices:
        data.append({
            "name": d.name,
            "ip": d.ip,
            "device_type": d.device_type,
            "device_role": d.device_role,
            "vendor": d.vendor,
            "device_model_name": (
                d.device_model.name if d.device_model else None
            ),
            "location": d.location,
            "snmp_version": d.snmp_version,
            "snmp_community": d.snmp_community or "",
            "snmp_user": d.snmp_user or "",
            "snmp_auth": d.snmp_auth or "",
            "snmp_priv": d.snmp_priv or "",
            "tcp_ports": d.tcp_ports or "",
            "monitor_interfaces": bool(d.monitor_interfaces),
            "monitor_health": bool(d.monitor_health),
            "active": bool(d.active),
        })

    filename = (
        f"devices_{len(data)}.json" if not ids_param
        else f"devices_selected_{len(data)}.json"
    )

    response = HttpResponse(
        json.dumps(data, indent=2, ensure_ascii=False),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ============================================================
# EQUIPO — IMPORTAR MASIVO
# ============================================================
@login_required
@require_admin_or_super()
def device_import_bulk(request):
    """
    Importa varios equipos desde un archivo JSON.

    **Flujo de dos pasadas:**

    **Primera pasada** (sin `overwrite_names`):
      - Valida estructura, campos mínimos y unicidad dentro del JSON.
      - Para cada item:
          · Verifica que el modelo exista y esté activo.
          · Verifica que el IP no esté ocupado por OTRO equipo.
          · Si el `name` ya existe en BD → es UPDATE (requiere autorización).
          · Si el `name` no existe → es CREATE (auto).
      - Devuelve `ok=False` con `invalid` (errores duros) y `conflicts`
        (updates que necesitan autorización) SIN procesar nada.

    **Segunda pasada** (con `overwrite_names`, incluso `"[]"`):
      - Procesa TODO: crea los nuevos, actualiza los autorizados,
        salta los no autorizados.
      - Devuelve `ok=True` con `created/updated/skipped`.

    Args:
        request: HttpRequest (POST).
            form-data:
              - file: archivo JSON (objeto único o lista).
              - overwrite_names: JSON array de nombres autorizados
                (solo en segunda pasada).

    Returns:
        JsonResponse con:
          - ok: bool
          - invalid: list[{name, ip, reasons[]}] (errores duros)
          - conflicts: list[{name, ip, vendor, model, reasons[]}]
          - created/updated/skipped (si ok=True)
    """
    import json
    from django.http import JsonResponse
    from monitoreo.services.chassis_oids import CHASSIS_OIDS

    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido"}, status=405)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"ok": False, "error": "No se subió ningún archivo."})

    if uploaded.size > MAX_IMPORT_SIZE:
        return JsonResponse({
            "ok": False,
            "error": (
                f"Archivo demasiado grande ({uploaded.size // 1024} KB). "
                f"Máximo {MAX_IMPORT_SIZE // (1024 * 1024)} MB."
            ),
        })

    # ---- 1. Parsear JSON ----
    try:
        raw = uploaded.read().decode("utf-8-sig")
        data = json.loads(raw)
    except UnicodeDecodeError:
        return JsonResponse({
            "ok": False,
            "error": "El archivo no está en UTF-8.",
        })
    except json.JSONDecodeError as e:
        return JsonResponse({
            "ok": False,
            "error": f"JSON inválido: {e.msg} (línea {e.lineno}).",
        })

    items = [data] if isinstance(data, dict) else data
    if not isinstance(items, list):
        return JsonResponse({
            "ok": False,
            "error": "El JSON debe ser un objeto o lista de objetos.",
        })
    if len(items) == 0:
        return JsonResponse({
            "ok": True,
            "created": [], "updated": [], "skipped": [],
            "message": "El archivo no contiene equipos.",
        })

    # ---- 2. Validar estructura de cada item ----
    validated = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return JsonResponse({
                "ok": False,
                "error": f"El elemento #{i+1} no es un objeto JSON.",
            })
        for field in ("name", "ip", "vendor", "device_model_name"):
            if not (item.get(field) or "").strip():
                return JsonResponse({
                    "ok": False,
                    "error": f"El elemento #{i+1} no tiene '{field}'.",
                })

        validated.append({
            "name": item["name"].strip(),
            "ip": item["ip"].strip(),
            "vendor": item["vendor"].strip(),
            "device_model_name": item["device_model_name"].strip(),
            "device_type": (item.get("device_type") or "router").strip(),
            "device_role": (item.get("device_role") or "access").strip(),
            "location": (item.get("location") or "").strip(),
            "snmp_version": (item.get("snmp_version") or "2c").strip(),
            "snmp_community": (item.get("snmp_community") or "").strip(),
            "snmp_user": (item.get("snmp_user") or "").strip(),
            "snmp_auth": (item.get("snmp_auth") or "").strip(),
            "snmp_priv": (item.get("snmp_priv") or "").strip(),
            "tcp_ports": (item.get("tcp_ports") or "161").strip(),
            "monitor_interfaces": bool(item.get("monitor_interfaces", True)),
            "monitor_health": bool(item.get("monitor_health", True)),
            "active": bool(item.get("active", True)),
        })

    # ---- 3. Validar unicidad DENTRO del JSON ----
    names = [v["name"] for v in validated]
    if len(names) != len(set(names)):
        dups = sorted({n for n in names if names.count(n) > 1})
        return JsonResponse({
            "ok": False,
            "error": f"Nombres duplicados en el JSON: {', '.join(dups)}",
        })

    ips = [v["ip"] for v in validated]
    if len(ips) != len(set(ips)):
        dups = sorted({ip for ip in ips if ips.count(ip) > 1})
        return JsonResponse({
            "ok": False,
            "error": f"IPs duplicadas en el JSON: {', '.join(dups)}",
        })

    # ---- 4. Clasificar cada item ----
    invalid = []      # Errores duros: no procesables
    conflicts = []    # Updates que necesitan autorización
    ready = []        # Creates sin problemas

    for v in validated:
        # 4.a. Buscar modelo
        try:
            model = DeviceModel.objects.get(
                vendor=v["vendor"],
                name=v["device_model_name"],
                active=True,
            )
        except DeviceModel.DoesNotExist:
            invalid.append({
                "name": v["name"],
                "ip": v["ip"],
                "reasons": [
                    f"Modelo '{v['device_model_name']}' no existe o está "
                    f"inactivo en el fabricante '{v['vendor']}'."
                ],
            })
            continue

        # 4.b. Buscar device existente por nombre
        existing = Device.objects.filter(name=v["name"]).first()

        if existing:
            # UPDATE: validar que el nuevo IP no esté ocupado por OTRO device
            ip_conflict = (
                Device.objects
                .filter(ip=v["ip"])
                .exclude(pk=existing.pk)
                .first()
            )
            if ip_conflict:
                invalid.append({
                    "name": v["name"],
                    "ip": v["ip"],
                    "reasons": [
                        f"IP '{v['ip']}' ya en uso por el equipo "
                        f"'{ip_conflict.name}' (ID {ip_conflict.pk})."
                    ],
                })
                continue

            conflicts.append({
                "name": v["name"],
                "ip": v["ip"],
                "vendor": v["vendor"],
                "model": v["device_model_name"],
                "reasons": [
                    f"Ya existe un equipo con este nombre (ID {existing.pk}). "
                    f"Requiere autorización para actualizarlo."
                ],
                "existing_id": existing.pk,
                "_item": v,
                "_model": model,
            })
        else:
            # CREATE: validar que el IP no esté ocupado
            ip_conflict = Device.objects.filter(ip=v["ip"]).first()
            if ip_conflict:
                invalid.append({
                    "name": v["name"],
                    "ip": v["ip"],
                    "reasons": [
                        f"IP '{v['ip']}' ya en uso por el equipo "
                        f"'{ip_conflict.name}' (ID {ip_conflict.pk}). "
                        f"Cambia el IP en el JSON."
                    ],
                })
                continue

            ready.append({"_item": v, "_model": model})

    # ---- 5. ¿Primera o segunda pasada? ----
    overwrite_raw = request.POST.get("overwrite_names")
    is_second_pass = overwrite_raw is not None

    overwrite_names = set()
    if overwrite_raw:
        try:
            parsed = json.loads(overwrite_raw)
            if isinstance(parsed, list):
                overwrite_names = {str(x) for x in parsed}
        except (ValueError, TypeError):
            pass

    # Primera pasada con conflictos o invalid → solo reportar
    if not is_second_pass and (invalid or conflicts):
        return JsonResponse({
            "ok": False,
            "invalid": invalid,
            "conflicts": [
                {k: v for k, v in c.items() if not k.startswith("_")}
                for c in conflicts
            ],
            "ready_count": len(ready),
        })

    # ---- 6. Procesar (segunda pasada o primera sin conflictos) ----
    created, updated, skipped = [], [], []

    def _has_chassis(model):
        """Helper: ¿el modelo tiene OIDs de chasis? (propias o por vendor)."""
        if model.oids:
            return True
        vendor_lower = (model.vendor or "").lower()
        return bool(CHASSIS_OIDS.get(vendor_lower))

    # 6.a. Creates
    for r in ready:
        v = r["_item"]
        model = r["_model"]
        has_chassis = _has_chassis(model)

        try:
            Device.objects.create(
                name=v["name"],
                ip=v["ip"],
                device_type=v["device_type"],
                device_role=v["device_role"],
                vendor=v["vendor"],
                device_model=model,
                location=v["location"],
                snmp_version=v["snmp_version"],
                snmp_community=v["snmp_community"],
                snmp_user=v["snmp_user"] or None,
                snmp_auth=v["snmp_auth"] or None,
                snmp_priv=v["snmp_priv"] or None,
                tcp_ports=v["tcp_ports"],
                monitor_interfaces=v["monitor_interfaces"] and model.has_interfaces,
                monitor_health=v["monitor_health"] and has_chassis,
                active=v["active"],
            )
            created.append(v["name"])
        except Exception as e:
            skipped.append({
                "name": v["name"],
                "reason": f"error al crear: {e}",
            })

    # 6.b. Updates (solo autorizados)
    for c in conflicts:
        v = c["_item"]
        model = c["_model"]
        existing = Device.objects.get(pk=c["existing_id"])

        if v["name"] not in overwrite_names:
            skipped.append({
                "name": v["name"],
                "reason": "no autorizado para sobrescribir",
            })
            continue

        has_chassis = _has_chassis(model)

        try:
            existing.ip = v["ip"]
            existing.device_type = v["device_type"]
            existing.device_role = v["device_role"]
            existing.vendor = v["vendor"]
            existing.device_model = model
            existing.location = v["location"]
            existing.snmp_version = v["snmp_version"]
            existing.snmp_community = v["snmp_community"]
            existing.snmp_user = v["snmp_user"] or None
            existing.snmp_auth = v["snmp_auth"] or None
            existing.snmp_priv = v["snmp_priv"] or None
            existing.tcp_ports = v["tcp_ports"]
            existing.monitor_interfaces = (
                v["monitor_interfaces"] and model.has_interfaces
            )
            existing.monitor_health = v["monitor_health"] and has_chassis
            existing.active = v["active"]
            existing.save()
            updated.append(v["name"])
        except Exception as e:
            skipped.append({
                "name": v["name"],
                "reason": f"error al actualizar: {e}",
            })

    return JsonResponse({
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "message": (
            f"{len(created)} creado(s), {len(updated)} actualizado(s), "
            f"{len(skipped)} saltado(s)."
        ),
    })


# ============================================================
# EQUIPO — MARCAR/DESMARCAR INTERFAZ DESTACADA DEL DASHBOARD
# ============================================================
@login_required
@require_admin_or_super()
def device_interface_set_dashboard(request, device_id, interface_id):
    """
    Marca o desmarca una interfaz como "destacada del dashboard".

    Comportamiento:
      - Si `interface_id == 0`: desmarca la destacada actual.
      - Si la interfaz YA es la destacada: la desmarca (toggle).
      - Si es otra interfaz: marca esa como destacada (la anterior
        se reemplaza automáticamente porque `dashboard_interface` es
        un ForeignKey, solo hay una por device).

    Solo aplica a equipos NO wireless. Los radioenlaces siempre
    muestran métricas de radio en el dashboard (no tráfico por
    interfaz), así que no tiene sentido marcar una "preferida".

    Args:
        request: HttpRequest (POST, AJAX).
        device_id: ID del equipo.
        interface_id: ID de la interfaz (0 para desmarcar).

    Returns:
        JsonResponse:
          - ok: bool
          - dashboard_interface_id: int | None (ID de la nueva
            destacada, o None si quedó sin destacada).
          - message: str (para mostrar en toast).
    """
    from django.http import JsonResponse

    if request.method != "POST":
        return JsonResponse(
            {"ok": False, "error": "Método no permitido"}, status=405
        )

    device = get_object_or_404(Device, pk=device_id)

    # Validación: solo equipos no wireless
    if device.is_wireless_link:
        return JsonResponse({
            "ok": False,
            "error": (
                "Los radioenlaces no usan 'interfaz destacada'. El "
                "dashboard muestra automáticamente sus métricas de radio."
            ),
        }, status=400)

    # Validación: solo si el equipo tiene interfaces habilitadas
    if not device.has_interfaces_support or not device.monitor_interfaces:
        return JsonResponse({
            "ok": False,
            "error": "El monitoreo de interfaces está deshabilitado para este equipo.",
        }, status=400)

    # ----------------------------------------------------------
    # Caso: desmarcar (interface_id = 0)
    # ----------------------------------------------------------
    if interface_id == 0:
        device.dashboard_interface = None
        device.save(update_fields=["dashboard_interface", "updated_at"])
        return JsonResponse({
            "ok": True,
            "dashboard_interface_id": None,
            "message": "Interfaz destacada removida. Se usará la primera con tráfico.",
        })

    # ----------------------------------------------------------
    # Validar que la interfaz pertenezca al device
    # ----------------------------------------------------------
    iface = get_object_or_404(Interface, pk=interface_id, device=device)

    # ----------------------------------------------------------
    # Toggle: si ya es la destacada, desmarcar
    # ----------------------------------------------------------
    if device.dashboard_interface_id == iface.id:
        device.dashboard_interface = None
        device.save(update_fields=["dashboard_interface", "updated_at"])
        return JsonResponse({
            "ok": True,
            "dashboard_interface_id": None,
            "message": (
                f"'{iface.display_name}' ya no es la interfaz destacada. "
                f"Se usará la primera con tráfico."
            ),
        })

    # ----------------------------------------------------------
    # Marcar nueva destacada
    # ----------------------------------------------------------
    device.dashboard_interface = iface
    device.save(update_fields=["dashboard_interface", "updated_at"])
    return JsonResponse({
        "ok": True,
        "dashboard_interface_id": iface.id,
        "message": f"'{iface.display_name}' marcada como destacada del dashboard.",
    })