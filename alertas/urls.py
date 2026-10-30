# alertas/urls.py
"""
Rutas URL de la app `alertas`.

Incluye:
  - Alertas (listado, acciones, exportación).
  - Reglas de alerta (CRUD + duplicar + bulk).
"""
from django.urls import path

from . import views

app_name = "alertas"

urlpatterns = [
    # ============================================================
    # ALERTAS
    # ============================================================
    path("", views.alert_list, name="alert_list"),
    path("export/excel/", views.export_alerts_excel, name="export_excel"),
    path("export/pdf/", views.export_alerts_pdf, name="export_pdf"),
    path("<int:alert_id>/reconocer/", views.alert_acknowledge, name="alert_acknowledge"),
    path("<int:alert_id>/resolver/", views.alert_resolve, name="alert_resolve"),
    path("<int:alert_id>/eliminar/", views.alert_delete, name="alert_delete"),

    # ============================================================
    # REGLAS
    # ============================================================
    path("reglas/", views.rule_list, name="rule_list"),
    path("reglas/nueva/", views.rule_create, name="rule_create"),
    path("reglas/<int:rule_id>/editar/", views.rule_edit, name="rule_edit"),
    path("reglas/<int:rule_id>/eliminar/", views.rule_delete, name="rule_delete"),
    path("reglas/<int:rule_id>/toggle/", views.rule_toggle, name="rule_toggle"),
    path("reglas/<int:rule_id>/duplicar/", views.rule_duplicate, name="rule_duplicate"),
    path("reglas/bulk/", views.rule_bulk, name="rule_bulk"),
]