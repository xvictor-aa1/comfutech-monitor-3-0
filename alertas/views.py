# alertas/views.py
"""
Vistas de la app `alertas`.

Incluye:
  - alert_list: listado paginado (10 por página) de alertas.
  - alert_acknowledge / alert_resolve / alert_delete.
  - export_alerts_excel / export_alerts_pdf: exportación de alertas.
  - rule_list (paginado 10/pág) / rule_create / rule_edit / rule_delete.
  - rule_toggle / rule_duplicate / rule_bulk.

A partir de la v4:
  · `Alert` ya no tiene FKs a Device/Interface/AlertRule. Las vistas
    consultan por `rule_id` / `rule_name` planos.
  · El filtro "Equipo" del listado de alertas se reemplaza por
    "Regla de alerta".
  · El formulario de regla incorpora el bloque de auto-resolución
    (`auto_resolve_conditionals_json`) y los flags `enable_auto_resolve`
    y `mark_as_resolved`.
"""
import json
import logging
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.decorators import require_admin_or_super
from core.sorting import apply_sort, has_active_filters, SEVERITY_ORDER
from inventario.models import Device
from .forms import AlertRuleForm
from .models import Alert, AlertRule

log = logging.getLogger(__name__)


# ============================================================
# ALERTAS — LISTA PAGINADA
# ============================================================
@login_required
def alert_list(request):
    """
    Lista las alertas con filtros, ordenamiento y paginación (10/pág).

    Filtros aceptados vía GET:
      - status: activa / reconocida / resuelta.
      - severity: critical / warning / info.
      - rule_id: ID de la regla que disparó la alerta (IntegerField).
      - q: búsqueda libre en el mensaje o en `rule_name`.
      - date_from / date_to: rango de fechas.

    A partir de la v4, las alertas NO se filtran por device/interface
    (ya no hay FKs). En su lugar, se ofrece filtro por regla.
    """
    status_filter = request.GET.get("status", "")
    severity_filter = request.GET.get("severity", "")
    rule_filter = request.GET.get("rule_id", "")
    search = request.GET.get("q", "").strip()
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")

    # Query base. A partir de la v4 no hay select_related porque no hay FKs.
    alerts = Alert.objects.all().annotate(
        severity_order=SEVERITY_ORDER,
    )

    # Aplicar filtros.
    if status_filter:
        alerts = alerts.filter(status=status_filter)
    if severity_filter:
        alerts = alerts.filter(severity=severity_filter)
    if rule_filter:
        try:
            alerts = alerts.filter(rule_id=int(rule_filter))
        except (ValueError, TypeError):
            pass  # Filtro inválido: ignorar
    if search:
        alerts = alerts.filter(
            Q(message__icontains=search) | Q(rule_name__icontains=search)
        )
    if date_from:
        alerts = alerts.filter(created_at__date__gte=date_from)
    if date_to:
        alerts = alerts.filter(created_at__date__lte=date_to)

    # Ordenamiento (por defecto: más recientes primero).
    SORTABLE = {
        "fecha":     "created_at",
        "severidad": "severity_order",
        "tipo":      "alert_type",
        "regla":     "rule_name",
        "mensaje":   "message",
        "valor":     "value_observed",
        "estado":    "status",
    }
    alerts, sort_key, order = apply_sort(request, alerts, SORTABLE, "-created_at")

    # Paginación: 10 alertas por página.
    paginator = Paginator(alerts, 10)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    # Contadores globales (sin filtros).
    all_alerts = Alert.objects.all()
    total_rules = AlertRule.objects.count()

    # Lista de reglas para el select del filtro. Ordenadas por nombre.
    rules_for_filter = AlertRule.objects.order_by("name").values(
        "id", "name", "severity"
    )

    context = {
        "alerts": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "sort_key": sort_key,
        "order": order,
        "status_filter": status_filter,
        "severity_filter": severity_filter,
        "rule_filter": rule_filter,
        "search": search,
        "date_from": date_from,
        "date_to": date_to,
        # Reglas para el filtro (reemplaza a `devices`).
        "rules_for_filter": rules_for_filter,
        # Contadores para las tarjetas.
        "count_all": all_alerts.count(),
        "count_activa": all_alerts.filter(status="activa").count(),
        "count_critical": all_alerts.filter(
            status="activa", severity="critical"
        ).count(),
        "count_resolved_24h": all_alerts.filter(
            status="resuelta",
            resolved_at__gte=timezone.now() - timezone.timedelta(hours=24)
        ).count(),
        # Info para el CTA de "crea tu primera regla".
        "total_rules": total_rules,
        "has_rules": total_rules > 0,
        # ¿Hay filtros activos?
        "has_filters": has_active_filters(
            request,
            ["status", "severity", "rule_id", "q", "date_from", "date_to"],
        ),
    }
    return render(request, "alertas/alert_list.html", context)


# ============================================================
# ALERTAS — ACCIONES
# ============================================================
@login_required
@require_admin_or_super()
def alert_acknowledge(request, alert_id):
    """Marca una alerta como reconocida."""
    alert = get_object_or_404(Alert, pk=alert_id)
    alert.status = "reconocida"
    alert.save(update_fields=["status"])
    messages.success(request, f"Alerta #{alert.id} reconocida.")
    return redirect(request.META.get("HTTP_REFERER", "alertas:alert_list"))


@login_required
@require_admin_or_super()
def alert_resolve(request, alert_id):
    """Marca una alerta como resuelta."""
    alert = get_object_or_404(Alert, pk=alert_id)
    alert.status = "resuelta"
    alert.resolved_at = timezone.now()
    alert.save(update_fields=["status", "resolved_at"])
    messages.success(request, f"Alerta #{alert.id} resuelta.")
    return redirect(request.META.get("HTTP_REFERER", "alertas:alert_list"))


@login_required
@require_admin_or_super()
def alert_delete(request, alert_id):
    """Elimina una alerta (con confirmación previa)."""
    alert = get_object_or_404(Alert, pk=alert_id)

    if request.method == "POST":
        alert.delete()
        messages.success(request, "Alerta eliminada.")
        return redirect("alertas:alert_list")

    return render(request, "alertas/alert_confirm_delete.html", {"alert": alert})


# ============================================================
# ALERTAS — EXPORTACIÓN
# ============================================================
@login_required
def export_alerts_excel(request):
    """
    Exporta las alertas filtradas a Excel (XLSX).
    Respeta los filtros y el ordenamiento aplicados en la lista.
    """
    from .exports import export_excel

    try:
        buf = export_excel(request)
        filename = f"alertas_comfutech_{datetime.now():%Y%m%d_%H%M}.xlsx"
        response = HttpResponse(
            buf.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        log.exception("Error generando Excel de alertas")
        messages.error(request, f"No se pudo generar el Excel: {e}")
        return redirect("alertas:alert_list")


@login_required
def export_alerts_pdf(request):
    """
    Exporta las alertas filtradas a PDF.
    Respeta los filtros y el ordenamiento aplicados en la lista.
    """
    from .exports import export_pdf

    try:
        buf = export_pdf(request)
        filename = f"alertas_comfutech_{datetime.now():%Y%m%d_%H%M}.pdf"
        response = HttpResponse(buf.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        log.exception("Error generando PDF de alertas")
        messages.error(request, f"No se pudo generar el PDF: {e}")
        return redirect("alertas:alert_list")


# ============================================================
# REGLAS — LISTA PAGINADA
# ============================================================
@login_required
def rule_list(request):
    """
    Lista las reglas de alerta paginadas (10 por página).

    Filtros:
      - q: búsqueda por nombre/descripción.
      - severity: prioridad.
      - enabled: activa/inactiva.
      - auto_resolve: "1" (con auto-resolve habilitado), "0" (sin él).

    A partir de la v4, el conteo de alertas por regla se hace con
    Subquery sobre `Alert.rule_id` (ya no hay FK). `last_fired` se
    anota con Subquery para evitar N+1 en el template.
    """
    q = request.GET.get("q", "").strip()
    severity_filter = request.GET.get("severity", "")
    enabled_filter = request.GET.get("enabled", "")
    auto_resolve_filter = request.GET.get("auto_resolve", "")

    # ------------------------------------------------------------
    # Subqueries para conteos por rule_id (sin FK).
    # ------------------------------------------------------------
    active_alerts_subq = (
        Alert.objects
        .filter(rule_id=OuterRef("id"), status="activa")
        .values("rule_id")
        .annotate(c=Count("*"))
        .values("c")
    )
    total_alerts_subq = (
        Alert.objects
        .filter(rule_id=OuterRef("id"))
        .values("rule_id")
        .annotate(c=Count("*"))
        .values("c")
    )
    last_fired_subq = (
        Alert.objects
        .filter(rule_id=OuterRef("id"))
        .order_by("-created_at")
        .values("created_at")[:1]
    )

    rules = AlertRule.objects.annotate(
        active_alerts=Coalesce(Subquery(active_alerts_subq), 0),
        total_alerts=Coalesce(Subquery(total_alerts_subq), 0),
        last_fired=Subquery(last_fired_subq),
    )

    # Filtros.
    if q:
        rules = rules.filter(
            Q(name__icontains=q) | Q(description__icontains=q)
        )
    if severity_filter:
        rules = rules.filter(severity=severity_filter)
    if enabled_filter == "1":
        rules = rules.filter(enabled=True)
    elif enabled_filter == "0":
        rules = rules.filter(enabled=False)
    if auto_resolve_filter == "1":
        rules = rules.filter(enable_auto_resolve=True)
    elif auto_resolve_filter == "0":
        rules = rules.filter(enable_auto_resolve=False)

    SORTABLE = {
        "nombre":          "name",
        "prioridad":       "severity",
        "estado":          "enabled",
        "alertas_activas": "active_alerts",
        "ultima":          "last_fired",
        "actualizada":     "updated_at",
    }
    rules, sort_key, order = apply_sort(request, rules, SORTABLE, "-updated_at")

    # Paginación: 10 reglas por página.
    paginator = Paginator(rules, 10)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    # Enriquecer cada regla con sus condicionales (disparo + auto-resolve).
    rules_data = []
    for rule in page_obj.object_list:
        rules_data.append({
            "rule": rule,
            "conditionals": rule.get_conditionals_with_devices(),
            "conditionals_count": rule.conditionals_count,
            "auto_resolve_conditionals": rule.get_auto_resolve_conditionals_with_devices(),
            "auto_resolve_conditionals_count": rule.auto_resolve_conditionals_count,
            "has_auto_resolve": rule.has_auto_resolve,
        })

    # Contadores globales.
    base = AlertRule.objects.all()
    # `firing_count`: reglas con alertas activas (por rule_id).
    active_rule_ids = set(
        Alert.objects.filter(status="activa")
        .exclude(rule_id__isnull=True)
        .values_list("rule_id", flat=True)
        .distinct()
    )
    # `auto_resolve_count`: reglas activas con flag ON + condicionales.
    auto_resolve_count = sum(
        1 for r in base.filter(enabled=True)
        if r.has_auto_resolve
    )
    # `mark_as_resolved_count`: reglas activas con mark_as_resolved.
    mark_as_resolved_count = base.filter(
        enabled=True, mark_as_resolved=True
    ).count()

    context = {
        "rules_data": rules_data,
        "page_obj": page_obj,
        "paginator": paginator,
        "q": q,
        "severity_filter": severity_filter,
        "enabled_filter": enabled_filter,
        "auto_resolve_filter": auto_resolve_filter,
        "sort_key": sort_key,
        "order": order,
        "severity_choices": AlertRule.SEVERITY_CHOICES,
        "total": base.count(),
        "active_count": base.filter(enabled=True).count(),
        "telegram_count": base.filter(enabled=True, telegram_enabled=True).count(),
        "firing_count": len(active_rule_ids),
        "auto_resolve_count": auto_resolve_count,
        "mark_as_resolved_count": mark_as_resolved_count,
        "has_filters": has_active_filters(
            request, ["q", "severity", "enabled", "auto_resolve"]
        ),
    }
    return render(request, "alertas/rule_list.html", context)


# ============================================================
# REGLAS — CREAR
# ============================================================
@login_required
@require_admin_or_super()
def rule_create(request):
    """Crea una nueva regla."""
    if request.method == "POST":
        form = AlertRuleForm(request.POST)
        if form.is_valid():
            rule = form.save(created_by=request.user)
            messages.success(request, f"Regla '{rule.name}' creada.")
            return redirect("alertas:rule_list")
    else:
        form = AlertRuleForm()

    devices = Device.objects.filter(active=True).order_by("name")

    context = {
        "form": form,
        "title": "Nueva regla de alerta",
        "is_edit": False,
        "devices": devices,
        "metrics": AlertRule.METRIC_CHOICES,
        "operators": AlertRule.OPERATOR_CHOICES,
        "logics": AlertRule.LOGIC_CHOICES,
        "max_groups": AlertRule.MAX_GROUPS,
        "max_conditionals_per_group": AlertRule.MAX_CONDITIONALS_PER_GROUP,
        "max_total_conditionals": AlertRule.MAX_TOTAL_CONDITIONALS,
        # JSONs iniciales para ambos bloques (vacíos en creación).
        "existing_conditionals": {"version": 2, "groups": []},
        "existing_auto_resolve_conditionals": {"version": 2, "groups": []},
    }
    return render(request, "alertas/rule_form.html", context)


# ============================================================
# REGLAS — EDITAR
# ============================================================
@login_required
@require_admin_or_super()
def rule_edit(request, rule_id):
    """
    Edita una regla existente.

    Si la validación falla, se preservan los condicionales POSTeados
    para que el usuario no pierda su trabajo al re-renderizar.
    Aplica a AMBOS bloques (disparo y auto-resolución).
    """
    rule = get_object_or_404(AlertRule, pk=rule_id)

    # Determinar qué condición pasar al template como `existing_conditionals`.
    existing_for_render = rule.conditionals
    existing_auto_for_render = rule.auto_resolve_conditionals

    if request.method == "POST":
        form = AlertRuleForm(request.POST)
        if form.is_valid():
            form.save(rule=rule)
            messages.success(request, f"Regla '{rule.name}' actualizada.")
            return redirect("alertas:rule_list")

        # POST inválido: intentar recuperar los condicionales enviados
        # para que los editores los muestren al re-renderizar.
        try:
            posted = json.loads(request.POST.get("conditionals_json", ""))
            if isinstance(posted, dict) and "groups" in posted:
                existing_for_render = posted
        except (ValueError, TypeError):
            pass

        try:
            posted_auto = json.loads(
                request.POST.get("auto_resolve_conditionals_json", "")
            )
            if isinstance(posted_auto, dict) and "groups" in posted_auto:
                existing_auto_for_render = posted_auto
        except (ValueError, TypeError):
            pass
    else:
        initial = {
            "name": rule.name,
            "description": rule.description,
            "severity": rule.severity,
            "custom_message": rule.custom_message,
            "telegram_enabled": rule.telegram_enabled,
            "telegram_cooldown_sec": rule.telegram_cooldown_sec,
            "fire_once": rule.fire_once,
            "skip_on_startup": rule.skip_on_startup,
            "enabled": rule.enabled,
            "enable_auto_resolve": rule.enable_auto_resolve,
            "mark_as_resolved": rule.mark_as_resolved,
        }
        form = AlertRuleForm(initial=initial)

    devices = Device.objects.filter(active=True).order_by("name")

    context = {
        "form": form,
        "rule": rule,
        "title": f"Editar: {rule.name}",
        "is_edit": True,
        "devices": devices,
        "metrics": AlertRule.METRIC_CHOICES,
        "operators": AlertRule.OPERATOR_CHOICES,
        "logics": AlertRule.LOGIC_CHOICES,
        "max_groups": AlertRule.MAX_GROUPS,
        "max_conditionals_per_group": AlertRule.MAX_CONDITIONALS_PER_GROUP,
        "max_total_conditionals": AlertRule.MAX_TOTAL_CONDITIONALS,
        "existing_conditionals": existing_for_render,
        "existing_auto_resolve_conditionals": existing_auto_for_render,
    }
    return render(request, "alertas/rule_form.html", context)


# ============================================================
# REGLAS — ELIMINAR
# ============================================================
@login_required
@require_admin_or_super()
def rule_delete(request, rule_id):
    """
    Elimina una regla (con confirmación previa).

    A partir de la v4, las alertas emitidas por esta regla NO se
    eliminan (no hay FK). Se conservan con su `rule_id` y `rule_name`
    como snapshot. Si se quiere "desvincularlas" también, hay que
    borrarlas manualmente.
    """
    rule = get_object_or_404(AlertRule, pk=rule_id)

    if request.method == "POST":
        name = rule.name
        rule.delete()
        messages.success(request, f"Regla '{name}' eliminada.")
        return redirect("alertas:rule_list")

    return render(request, "alertas/rule_confirm_delete.html", {"rule": rule})


# ============================================================
# REGLAS — TOGGLE
# ============================================================
@login_required
@require_admin_or_super()
def rule_toggle(request, rule_id):
    """Activa/desactiva una regla."""
    rule = get_object_or_404(AlertRule, pk=rule_id)

    if request.method == "POST":
        rule.enabled = not rule.enabled
        rule.save(update_fields=["enabled", "updated_at"])
        state = "activada" if rule.enabled else "desactivada"
        messages.success(request, f"Regla '{rule.name}' {state}.")

    return redirect(request.META.get("HTTP_REFERER", "alertas:rule_list"))


# ============================================================
# REGLAS — DUPLICAR
# ============================================================
@login_required
@require_admin_or_super()
def rule_duplicate(request, rule_id):
    """
    Duplica una regla existente.

    A partir de la v4, se copian también:
      - `auto_resolve_conditionals`
      - `enable_auto_resolve`
      - `mark_as_resolved`
    """
    if request.method != "POST":
        return redirect("alertas:rule_list")

    original = get_object_or_404(AlertRule, pk=rule_id)

    dup = AlertRule()
    dup.name = f"{original.name} (copia)"
    dup.description = original.description
    # --- Condicionales de disparo ---
    dup.conditionals = original.conditionals
    # --- Condicionales de auto-resolución ---
    dup.auto_resolve_conditionals = original.auto_resolve_conditionals
    dup.enable_auto_resolve = original.enable_auto_resolve
    dup.mark_as_resolved = original.mark_as_resolved
    # --- Resto de campos ---
    dup.severity = original.severity
    dup.custom_message = original.custom_message
    dup.telegram_enabled = original.telegram_enabled
    dup.telegram_cooldown_sec = original.telegram_cooldown_sec
    dup.fire_once = original.fire_once
    dup.skip_on_startup = original.skip_on_startup
    dup.enabled = False  # duplicada desactivada por defecto.
    dup.created_by = request.user
    dup.save()

    messages.success(request, f"Regla duplicada como '{dup.name}'.")
    return redirect("alertas:rule_edit", rule_id=dup.pk)


# ============================================================
# REGLAS — ACCIONES EN BLOQUE
# ============================================================
@login_required
@require_admin_or_super()
def rule_bulk(request):
    """Aplica acciones masivas sobre reglas seleccionadas."""
    if request.method != "POST":
        return redirect("alertas:rule_list")

    action = request.POST.get("bulk_action")
    ids = request.POST.getlist("selected_rules")

    if not ids:
        messages.warning(request, "No hay reglas seleccionadas.")
        return redirect("alertas:rule_list")

    qs = AlertRule.objects.filter(pk__in=ids)

    if action == "enable":
        n = qs.update(enabled=True)
        messages.success(request, f"{n} regla(s) activada(s).")
    elif action == "disable":
        n = qs.update(enabled=False)
        messages.success(request, f"{n} regla(s) desactivada(s).")
    elif action == "delete":
        n = qs.count()
        qs.delete()
        messages.success(request, f"{n} regla(s) eliminada(s).")

    return redirect("alertas:rule_list")