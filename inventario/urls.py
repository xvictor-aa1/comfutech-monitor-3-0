# inventario/urls.py
"""
Rutas URL de la app `inventario`.

Incluye:
  - Equipos (Device): lista, detalle, crear, editar, eliminar,
    gestionar interfaces.
  - Modelos de equipo (DeviceModel): lista, crear, editar, eliminar,
    toggle activo/inactivo. Función de Exportar / Importar
    configuraciones via un archivo .json
  - API: modelos filtrados por fabricante.
"""
from django.urls import path
from . import views

app_name = "inventario"

urlpatterns = [
    # ============================================================
    # EQUIPOS
    # ============================================================
    path("", views.device_list, name="device_list"),
    path("nuevo/", views.device_create, name="device_create"),
    path("api/models/", views.api_models, name="api_models"),
    path("<int:device_id>/", views.device_detail, name="device_detail"),
    path("<int:device_id>/editar/", views.device_edit, name="device_edit"),
    path("<int:device_id>/eliminar/", views.device_delete, name="device_delete"),
    path("<int:device_id>/interfaces/", views.device_interfaces, name="device_interfaces"),
    path("<int:device_id>/interface/<int:interface_id>/set-dashboard/", views.device_interface_set_dashboard, name="device_interface_set_dashboard"),
    # ============================================================
    # EQUIPOS — IMPORT / EXPORT
    # ============================================================
    path("<int:device_id>/export/", views.device_export, name="device_export"),
    path("import/check/", views.device_import_check, name="device_import_check"),
    path("export-bulk/", views.device_export_bulk, name="device_export_bulk"),
    path("import-bulk/", views.device_import_bulk, name="device_import_bulk"),
    # ============================================================
    # MODELOS DE EQUIPO
    # ============================================================
    path("modelos/", views.device_model_list, name="device_model_list"),
    path("modelos/nuevo/", views.device_model_create, name="device_model_create"),
    path("modelos/<int:model_id>/editar/", views.device_model_edit, name="device_model_edit"),
    path("modelos/<int:model_id>/eliminar/", views.device_model_delete, name="device_model_delete"),
    path("modelos/<int:model_id>/toggle/", views.device_model_toggle, name="device_model_toggle"),
    # ============================================================
    # MODELOS — IMPORT / EXPORT
    # ============================================================
    path("modelos/<int:model_id>/export/", views.device_model_export, name="device_model_export"),
    path("modelos/import/", views.device_models_import, name="device_models_import"),
    path("modelos/export-bulk/", views.device_models_export_bulk, name="device_models_export_bulk"),
    path("modelos/parse/", views.device_models_parse, name="device_models_parse"),
]