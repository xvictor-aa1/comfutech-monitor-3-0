# core/templatetags/breadcrumb.py
"""
Template tag para generar breadcrumbs automáticos basados en la URL.

Cada vista NO necesita declarar su breadcrumb. El mapping
`BREADCRUMB_MAP` centraliza la jerarquía de navegación por
(app_name, url_name).

Uso en base.html:
    {% load breadcrumb %}
    ...
    {% auto_breadcrumb %}

Si una vista necesita un breadcrumb custom, puede pasar
`breadcrumb_items` en el contexto como lista de dicts:
    [{"label": "Equipos", "url": "/equipos/"}, {"label": "Custom"}]
"""
from django import template
from django.urls import NoReverseMatch, reverse

register = template.Library()


# ============================================================
# MAPEO DE BREADCRUMBS POR VISTA
# ============================================================
# Cada entrada: lista de items. El último es el "current" (sin url).
# Cada item puede tener:
#   - label (str): texto mostrado
#   - url_name (str, opcional): nombre de la URL a resolver
#   - url_kwargs (dict, opcional): kwargs para reverse()
BREADCRUMB_MAP = {
    # ------------------------------------------------------------
    # INVENTARIO
    # ------------------------------------------------------------
    ("inventario", "device_list"): [
        {"label": "Equipos"},
    ],
    ("inventario", "device_create"): [
        {"label": "Equipos", "url_name": "inventario:device_list"},
        {"label": "Nuevo equipo"},
    ],
    ("inventario", "device_detail"): [
        {"label": "Equipos", "url_name": "inventario:device_list"},
        {"label": "Detalle"},
    ],
    ("inventario", "device_edit"): [
        {"label": "Equipos", "url_name": "inventario:device_list"},
        {"label": "Editar"},
    ],
    ("inventario", "device_delete"): [
        {"label": "Equipos", "url_name": "inventario:device_list"},
        {"label": "Eliminar"},
    ],
    ("inventario", "device_interfaces"): [
        {"label": "Equipos", "url_name": "inventario:device_list"},
        {"label": "Interfaces"},
    ],
    ("inventario", "device_model_list"): [
        {"label": "Equipos", "url_name": "inventario:device_list"},
        {"label": "Modelos"},
    ],
    ("inventario", "device_model_create"): [
        {"label": "Equipos", "url_name": "inventario:device_list"},
        {"label": "Modelos", "url_name": "inventario:device_model_list"},
        {"label": "Nuevo modelo"},
    ],
    ("inventario", "device_model_edit"): [
        {"label": "Equipos", "url_name": "inventario:device_list"},
        {"label": "Modelos", "url_name": "inventario:device_model_list"},
        {"label": "Editar"},
    ],
    ("inventario", "device_model_delete"): [
        {"label": "Equipos", "url_name": "inventario:device_list"},
        {"label": "Modelos", "url_name": "inventario:device_model_list"},
        {"label": "Eliminar"},
    ],

    # ------------------------------------------------------------
    # ALERTAS
    # ------------------------------------------------------------
    ("alertas", "alert_list"): [
        {"label": "Alertas"},
    ],
    ("alertas", "alert_delete"): [
        {"label": "Alertas", "url_name": "alertas:alert_list"},
        {"label": "Eliminar"},
    ],
    ("alertas", "rule_list"): [
        {"label": "Alertas", "url_name": "alertas:alert_list"},
        {"label": "Reglas"},
    ],
    ("alertas", "rule_create"): [
        {"label": "Alertas", "url_name": "alertas:alert_list"},
        {"label": "Reglas", "url_name": "alertas:rule_list"},
        {"label": "Nueva regla"},
    ],
    ("alertas", "rule_edit"): [
        {"label": "Alertas", "url_name": "alertas:alert_list"},
        {"label": "Reglas", "url_name": "alertas:rule_list"},
        {"label": "Editar"},
    ],
    ("alertas", "rule_delete"): [
        {"label": "Alertas", "url_name": "alertas:alert_list"},
        {"label": "Reglas", "url_name": "alertas:rule_list"},
        {"label": "Eliminar"},
    ],

    # ------------------------------------------------------------
    # MONITOREO
    # ------------------------------------------------------------
    ("monitoreo", "monitor_status"): [
        {"label": "Monitor", "url_name": "monitoreo:monitor_live"},
        {"label": "Estado del servicio"},
    ],
    ("monitoreo", "monitor_live"): [
        {"label": "Monitor"},
    ],
    ("monitoreo", "discovery_history"): [
        {"label": "Equipos", "url_name": "inventario:device_list"},
        {"label": "Historial Discovery"},
    ],

    # ------------------------------------------------------------
    # CORE
    # ------------------------------------------------------------
    ("core", "dashboard"): [],  # no mostrar en dashboard
    ("core", "user_list"): [
        {"label": "Usuarios"},
    ],
    ("core", "user_create"): [
        {"label": "Usuarios", "url_name": "core:user_list"},
        {"label": "Nuevo"},
    ],
    ("core", "user_edit"): [
        {"label": "Usuarios", "url_name": "core:user_list"},
        {"label": "Editar"},
    ],
    ("core", "user_password"): [
        {"label": "Usuarios", "url_name": "core:user_list"},
        {"label": "Cambiar contraseña"},
    ],
    ("core", "user_delete"): [
        {"label": "Usuarios", "url_name": "core:user_list"},
        {"label": "Eliminar"},
    ],
    ("core", "profile"): [
        {"label": "Mi perfil"},
    ],
    ("core", "system_settings"): [
        {"label": "Configuración"},
    ],
}


@register.inclusion_tag("components/_breadcrumb.html", takes_context=True)
def auto_breadcrumb(context):
    """
    Genera el breadcrumb para la página actual.

    Estrategia:
      1. Si la vista pasó `breadcrumb_items` en el contexto, se usa esa
         lista (permite personalización por vista).
      2. Si no, se consulta BREADCRUMB_MAP con (app_name, url_name).
      3. Si no hay mapping, no se muestra nada.

    Si la vista tiene un `device` en el contexto, se enriquece el
    breadcrumb insertando el nombre del device antes del último item.
    """
    request = context.get("request")
    if not request or not request.resolver_match:
        return {"items": []}

    # ------------------------------------------------------------
    # 1. ¿La vista proveyó items custom?
    # ------------------------------------------------------------
    custom_items = context.get("breadcrumb_items")
    if custom_items is not None:
        return {"items": custom_items}

    # ------------------------------------------------------------
    # 2. Auto-generar desde el mapping
    # ------------------------------------------------------------
    resolver = request.resolver_match
    app = resolver.app_name
    url_name = resolver.url_name

    items_def = BREADCRUMB_MAP.get((app, url_name), [])

    # Dashboard y vistas no mapeadas → no mostrar
    if not items_def:
        return {"items": []}

    # Resolver URLs
    resolved = []
    for item in items_def:
        resolved_item = {"label": item["label"], "url": None}
        if item.get("url_name"):
            try:
                resolved_item["url"] = reverse(
                    item["url_name"],
                    kwargs=item.get("url_kwargs", {}),
                )
            except NoReverseMatch:
                pass
        resolved.append(resolved_item)

    # ------------------------------------------------------------
    # 3. Enriquecer con nombre de device si aplica
    # ------------------------------------------------------------
    device = context.get("device")
    if device and hasattr(device, "id") and len(resolved) >= 2:
        # Insertar el nombre del device antes del último item
        # SOLO si el último item es una vista de ese device
        last_label = resolved[-1]["label"]
        if last_label in ("Detalle", "Interfaces", "Editar", "Eliminar"):
            try:
                device_url = reverse(
                    "inventario:device_detail", args=[device.id]
                )
                resolved.insert(len(resolved) - 1, {
                    "label": device.name,
                    "url": device_url if last_label != "Detalle" else None,
                })
                # Si es "Detalle", el nombre del device es el current
                # (no debe tener URL)
                if last_label == "Detalle":
                    resolved[-1] = {
                        "label": device.name,
                        "url": None,
                    }
                    resolved.pop(-2)
            except NoReverseMatch:
                pass

    return {"items": resolved}