# core/sorting.py
"""
Helper compartido para ordenamiento de listas.

Uso:
    from core.sorting import apply_sort, has_active_filters, ROLE_ORDER
    qs, sort_key, order = apply_sort(request, qs, SORTABLE, "name")
"""
from django.db.models import Case, IntegerField, Value, When


def apply_sort(request, qs, sortable_fields: dict, default_sort: str = "-created_at"):
    """
    Aplica ordenamiento según request.GET['sort'] y ['order'].

    Args:
        request: HttpRequest.
        qs: queryset base.
        sortable_fields: dict {clave_url: campo_modelo}.
        default_sort: orden por defecto.

    Returns:
        tuple: (qs_ordenado, sort_key, order)
    """
    sort_key = request.GET.get("sort", "")
    order = request.GET.get("order", "desc")

    if sort_key in sortable_fields:
        field = sortable_fields[sort_key]
        direction = "" if order == "asc" else "-"
        qs = qs.order_by(f"{direction}{field}")
    else:
        qs = qs.order_by(default_sort)
        sort_key = ""
        order = "desc"

    return qs, sort_key, order


def has_active_filters(request, keys: list) -> bool:
    """Devuelve True si alguno de los query params dados tiene valor."""
    return any(request.GET.get(k, "").strip() for k in keys)


# ============================================================
# ANOTACIONES COMUNES
# ============================================================
SEVERITY_ORDER = Case(
    When(severity="critical", then=Value(3)),
    When(severity="warning",  then=Value(2)),
    When(severity="info",     then=Value(1)),
    default=Value(0),
    output_field=IntegerField(),
)

STATUS_ALERT_ORDER = Case(
    When(status="activa",     then=Value(3)),
    When(status="reconocida", then=Value(2)),
    When(status="resuelta",   then=Value(1)),
    default=Value(0),
    output_field=IntegerField(),
)

ROLE_ORDER = Case(
    When(device_role="core",         then=Value(4)),
    When(device_role="distribution", then=Value(3)),
    When(device_role="access",       then=Value(2)),
    When(device_role="cpe",          then=Value(1)),
    default=Value(0),
    output_field=IntegerField(),
)