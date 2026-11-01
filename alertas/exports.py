# alertas/exports.py
"""
Exportación de alertas a Excel y PDF.

A partir de la v4:
  · `Alert` no tiene FK a `Device` ni a `AlertRule`. La información de
    la regla se lee de `alert.rule_name` (snapshot) y `alert.rule_id`.
  · La columna "Equipo" del reporte se reemplaza por "Regla de alerta".
  · El ordenamiento por columna "equipo" se reemplaza por "regla".
  · `_get_alerts` ya no necesita `select_related` (no hay relaciones).

El resto (colores por severidad/estado, formato, filtros) se mantiene
idéntico al comportamiento previo.
"""
import io
from datetime import datetime
from django.utils import timezone
from django.db.models import Case, IntegerField, Value, When
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
)


# ============================================================
# HELPERS
# ============================================================
def _apply_filters(qs, filters):
    """
    Aplica filtros del request al queryset.

    A partir de la v4, el filtro por `device` se reemplaza por
    `rule_id` (IntegerField). También se permite búsqueda por
    `rule_name` dentro de `q`.

    Args:
        qs: queryset base de `Alert`.
        filters: dict con los valores de `request.GET`.

    Returns:
        QuerySet filtrado.
    """
    if filters.get("status"):
        qs = qs.filter(status=filters["status"])
    if filters.get("severity"):
        qs = qs.filter(severity=filters["severity"])
    if filters.get("rule_id"):
        try:
            qs = qs.filter(rule_id=int(filters["rule_id"]))
        except (ValueError, TypeError):
            pass
    if filters.get("metric"):
        qs = qs.filter(alert_type=filters["metric"])
    if filters.get("q"):
        from django.db.models import Q
        q = filters["q"]
        qs = qs.filter(
            Q(message__icontains=q) | Q(rule_name__icontains=q)
        )
    if filters.get("date_from"):
        qs = qs.filter(created_at__date__gte=filters["date_from"])
    if filters.get("date_to"):
        qs = qs.filter(created_at__date__lte=filters["date_to"])
    return qs


SEVERITY_ORDER = Case(
    When(severity="critical", then=Value(3)),
    When(severity="warning",  then=Value(2)),
    When(severity="info",     then=Value(1)),
    default=Value(0),
    output_field=IntegerField(),
)

STATUS_ORDER = Case(
    When(status="activa",     then=Value(3)),
    When(status="reconocida", then=Value(2)),
    When(status="resuelta",   then=Value(1)),
    default=Value(0),
    output_field=IntegerField(),
)

# A partir de la v4, "equipo" se reemplaza por "regla".
SORTABLE_FIELDS = {
    "fecha":     "created_at",
    "severidad": "severity_order",
    "tipo":      "alert_type",
    "regla":     "rule_name",
    "mensaje":   "message",
    "valor":     "value_observed",
    "estado":    "status_order",
}


def _get_alerts(request):
    """
    Devuelve el queryset de alertas filtrado y ordenado según el request.

    A partir de la v4, no hay `select_related` (no hay FKs). Se
    mantiene el `annotate` de orden para los sortables por severidad
    y estado.
    """
    from .models import Alert

    filters = {
        "status":    request.GET.get("status", ""),
        "severity":  request.GET.get("severity", ""),
        "rule_id":   request.GET.get("rule_id", ""),
        "metric":    request.GET.get("metric", ""),
        "q":         request.GET.get("q", "").strip(),
        "date_from": request.GET.get("date_from", ""),
        "date_to":   request.GET.get("date_to", ""),
    }

    qs = Alert.objects.annotate(
        severity_order=SEVERITY_ORDER,
        status_order=STATUS_ORDER,
    )

    qs = _apply_filters(qs, filters)

    # Aplicar el mismo ordenamiento que la vista.
    sort_key = request.GET.get("sort", "fecha")
    order = request.GET.get("order", "desc")
    if sort_key in SORTABLE_FIELDS:
        field = SORTABLE_FIELDS[sort_key]
        direction = "" if order == "asc" else "-"
        qs = qs.order_by(f"{direction}{field}")
    else:
        qs = qs.order_by("-created_at")

    return qs, filters


# ============================================================
# EXCEL
# ============================================================
def export_excel(request):
    """
    Genera un archivo Excel con las alertas filtradas.

    Columnas: ID, Fecha, Hora, Severidad, Tipo, Regla de alerta,
    Mensaje, Valor, Estado.

    A partir de la v4, la columna "Equipo" se reemplaza por
    "Regla de alerta" (usa `alert.rule_name`).
    """
    alerts, filters = _get_alerts(request)

    wb = Workbook()
    ws = wb.active
    ws.title = "Alertas"

    # --- Título ---
    ws.merge_cells("A1:I1")
    title_cell = ws["A1"]
    title_cell.value = "Reporte de Alertas - Comfutech Monitor"
    title_cell.font = Font(bold=True, size=14, color="FFFFFF")
    title_cell.fill = PatternFill("solid", fgColor="0D6EFD")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 25

    # --- Filtros + Orden ---
    filter_parts = []
    if filters["status"]:
        filter_parts.append(f"Estado: {filters['status']}")
    if filters["severity"]:
        filter_parts.append(f"Severidad: {filters['severity']}")
    if filters["rule_id"]:
        filter_parts.append(f"Regla ID: {filters['rule_id']}")
    if filters["metric"]:
        filter_parts.append(f"Tipo: {filters['metric']}")
    if filters["q"]:
        filter_parts.append(f"Búsqueda: {filters['q']}")
    if filters["date_from"]:
        filter_parts.append(f"Desde: {filters['date_from']}")
    if filters["date_to"]:
        filter_parts.append(f"Hasta: {filters['date_to']}")

    sort_key = request.GET.get("sort", "fecha")
    order = request.GET.get("order", "desc")
    order_label = "↓ Descendente" if order == "desc" else "↑ Ascendente"
    sort_labels = {
        "fecha": "Fecha", "severidad": "Severidad", "tipo": "Tipo",
        "regla": "Regla de alerta", "mensaje": "Mensaje",
        "valor": "Valor", "estado": "Estado",
    }
    order_parts = [f"Ordenado por: {sort_labels.get(sort_key, sort_key)} {order_label}"]

    filter_text = " | ".join(filter_parts) if filter_parts else "Sin filtros"
    order_text = " | ".join(order_parts)

    ws.merge_cells("A2:I2")
    ws["A2"] = f"Filtros: {filter_text}   ·   Total: {alerts.count()} alertas"
    ws["A2"].font = Font(italic=True, size=10, color="666666")

    ws.merge_cells("A3:I3")
    ws["A3"] = order_text
    ws["A3"].font = Font(italic=True, size=9, color="0D6EFD")

    # --- Encabezados ---
    # "Equipo" → "Regla de alerta".
    headers = ["ID", "Fecha", "Hora", "Severidad", "Tipo",
               "Regla de alerta", "Mensaje", "Valor", "Estado"]
    ws.append([])  # fila vacía.
    ws.append(headers)
    header_row = 5
    header_fill = PatternFill("solid", fgColor="E7F1FF")
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_num)
        cell.font = Font(bold=True, color="0D6EFD")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = Border(
            bottom=Side(style="thin", color="0D6EFD"),
        )

    # --- Datos ---
    for alert in alerts:
        local_dt = timezone.localtime(alert.created_at)
        ws.append([
            alert.id,
            local_dt.strftime("%d/%m/%Y"),
            local_dt.strftime("%H:%M:%S"),
            alert.get_severity_display(),
            alert.get_alert_type_display() if hasattr(alert, "get_alert_type_display")
                else alert.alert_type,
            # Snapshot de la regla (reemplaza a `alert.device.name`).
            alert.rule_name or "—",
            alert.message or "",
            float(alert.value_observed) if alert.value_observed is not None else "",
            alert.get_status_display(),
        ])

    # --- Estilos de datos ---
    severity_colors = {
        "Crítica":    "FFE5E5",
        "Advertencia":"FFF5CC",
        "Info":       "E5F3FF",
    }
    status_colors = {
        "Activa":      "FFD5D5",
        "Reconocida":  "FFF0C2",
        "Resuelta":    "D5F5D5",
    }

    for row_num in range(header_row + 1, header_row + 1 + alerts.count()):
        severity_cell = ws.cell(row=row_num, column=4)
        if severity_cell.value in severity_colors:
            severity_cell.fill = PatternFill("solid", fgColor=severity_colors[severity_cell.value])

        status_cell = ws.cell(row=row_num, column=9)
        if status_cell.value in status_colors:
            status_cell.fill = PatternFill("solid", fgColor=status_colors[status_cell.value])

        # Wrap en mensaje.
        ws.cell(row=row_num, column=7).alignment = Alignment(wrap_text=True, vertical="top")

    # --- Anchos de columna ---
    # "Regla de alerta" hereda el ancho de "Equipo" (20).
    widths = [8, 12, 10, 14, 26, 20, 60, 12, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # --- Congelar paneles ---
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    # --- Guardar ---
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ============================================================
# PDF
# ============================================================
def export_pdf(request):
    """
    Genera un PDF (A4 landscape) con las alertas filtradas.

    A partir de la v4, la columna "Equipo" se reemplaza por
    "Regla de alerta" (usa `alert.rule_name`). El resto del layout
    (colores por severidad, encabezados repetidos, footer) se
    mantiene idéntico.
    """
    alerts, filters = _get_alerts(request)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle", parent=styles["Title"],
        fontSize=16, textColor=colors.HexColor("#0D6EFD"),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "CustomSubtitle", parent=styles["Normal"],
        fontSize=9, textColor=colors.HexColor("#666666"),
        spaceAfter=6,
    )
    order_style = ParagraphStyle(
        "OrderStyle", parent=styles["Normal"],
        fontSize=8, textColor=colors.HexColor("#0D6EFD"),
        spaceAfter=12,
    )

    sort_key = request.GET.get("sort", "fecha")
    order = request.GET.get("order", "desc")
    order_label = "↓" if order == "desc" else "↑"
    sort_labels = {
        "fecha": "Fecha", "severidad": "Severidad", "tipo": "Tipo",
        "regla": "Regla de alerta", "mensaje": "Mensaje",
        "valor": "Valor", "estado": "Estado",
    }

    story = []
    story.append(Paragraph("Reporte de Alertas - Comfutech Monitor", title_style))
    story.append(Paragraph(
        f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}   ·   "
        f"Total: {alerts.count()} alertas",
        subtitle_style
    ))
    story.append(Paragraph(
        f"Ordenado por: {sort_labels.get(sort_key, sort_key)} {order_label}",
        order_style
    ))

    # --- Encabezados ---
    # "Equipo" → "Regla de alerta".
    headers = ["ID", "Fecha/Hora", "Sev.", "Tipo", "Regla de alerta", "Mensaje", "Valor", "Estado"]
    data = [headers]

    for alert in alerts:
        local_dt = timezone.localtime(alert.created_at)
        severity_short = {
            "critical": "CRIT",
            "warning":  "WARN",
            "info":     "INFO",
        }.get(alert.severity, alert.severity)

        message = alert.message or ""
        if len(message) > 70:
            message = message[:67] + "..."

        data.append([
            str(alert.id),
            local_dt.strftime("%d/%m %H:%M"),
            severity_short,
            alert.alert_type[:18],
            # Snapshot de la regla (reemplaza a `alert.device.name`).
            (alert.rule_name or "—")[:22],
            Paragraph(message, styles["Normal"]),
            f"{float(alert.value_observed):.2f}" if alert.value_observed is not None else "—",
            alert.get_status_display(),
        ])

    # --- Estilos de la tabla ---
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        # Encabezado
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D6EFD")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 9),
        ("ALIGN",      (0, 0), (-1, 0), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),

        # Cuerpo
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("VALIGN",   (0, 1), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),

        # Grid
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DEE2E6")),
    ]))

    story.append(table)

    # --- Footer ---
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<i>Generado por Comfutech Monitor</i>",
        ParagraphStyle("Footer", parent=styles["Normal"],
                       fontSize=7, textColor=colors.HexColor("#999999"))
    ))

    doc.build(story)
    buf.seek(0)
    return buf