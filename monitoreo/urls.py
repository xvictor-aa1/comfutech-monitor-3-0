# monitoreo/urls.py
"""
Rutas URL de la app `monitoreo`.

Vistas separadas:
  - /monitoreo/status/       → estado del servicio
  - /monitoreo/live/         → monitoreo en vivo
  - /monitoreo/api/...       → endpoints JSON
  - /monitoreo/device/...    → discovery por equipo
"""
from django.urls import path

from . import views

app_name = "monitoreo"

urlpatterns = [
    # Estado del servicio
    path("status/", views.monitor_status, name="monitor_status"),

    # Monitoreo en vivo
    path("live/", views.monitor_live, name="monitor_live"),

    # API JSON
    path("api/devices-live/", views.monitor_devices_live, name="devices_live"),
    path("api/discover-all/", views.run_discovery_all, name="discover_all"),

    # Discovery por equipo
    path("device/<int:device_id>/discover/", views.run_discovery, name="run_discovery"),
    path("device/<int:device_id>/history/", views.discovery_history, name="discovery_history"),
    path("device/<int:device_id>/discover-ap/", views.run_ap_discovery, name="run_ap_discovery"),

    # Dashboard — sparkline
    path("api/sparkline/", views.dashboard_sparkline, name="dashboard_sparkline"),
]