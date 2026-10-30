# core/templatetags/sorting_tags.py
"""
Template tag para generar encabezados de tabla ordenables.

Uso en templates:
    {% load sorting_tags %}
    {% sortable_th "fecha" "Fecha" "120px" %}

El tag genera un <th> con un enlace que conserva los filtros actuales
del request (query params) pero resetea la paginación (`page`) al
reordenar. Esto evita el bug clásico de "reordeno desde la página 5
y me quedo viendo una página vacía".
"""
from django import template

register = template.Library()


@register.inclusion_tag("core/_sortable_th.html", takes_context=True)
def sortable_th(context, key, label, width=""):
    """
    Renderiza un <th> con enlace de ordenamiento.

    El enlace:
      - Conserva todos los query params actuales (filtros, búsqueda, etc.).
      - **Elimina `page`** para volver a la página 1 al reordenar
        (evita mostrar una página vacía tras cambiar el orden).
      - Alterna `order` entre `asc` y `desc` cuando se pulsa sobre la
        misma columna; en caso contrario, usa `desc` por defecto.

    Args:
        context: contexto del template (inyectado automáticamente).
        key: clave del campo por el que se ordena (ej: "fecha").
        label: texto visible en el encabezado (ej: "Fecha").
        width: ancho CSS opcional para el <th> (ej: "120px").

    Returns:
        dict: contexto para renderizar `core/_sortable_th.html` con
              las claves: key, label, width, current_sort,
              current_order y url.
    """
    request = context["request"]
    current_sort = request.GET.get("sort", "")
    current_order = request.GET.get("order", "desc")

    # Construir URL preservando otros parámetros
    params = request.GET.copy()

    # ⚠️ IMPORTANTE: eliminar 'page' para volver a la página 1 al
    # reordenar. Sin esto, si el usuario está en la página 5 y cambia
    # el orden, el paginador lo deja en la página 5 con los nuevos
    # criterios, lo que puede mostrar una página vacía o confusa.
    params.pop("page", None)

    # Alternar orden: si ya estamos ordenando por esta columna en
    # descendente, el siguiente clic será ascendente. En caso contrario,
    # el primer clic siempre es descendente (más útil para fechas y
    # valores numéricos).
    if current_sort == key and current_order == "desc":
        params["order"] = "asc"
    else:
        params["order"] = "desc"
    params["sort"] = key

    return {
        "key": key,
        "label": label,
        "width": width,
        "current_sort": current_sort,
        "current_order": current_order,
        "url": "?" + params.urlencode(),
    }