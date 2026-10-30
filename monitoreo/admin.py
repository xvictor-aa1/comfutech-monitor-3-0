# monitoreo/admin.py
"""
Admin de la app `monitoreo`.

Solo visible para el superadministrador.

Los modelos son de auditoría/estado:
  - DiscoveryJob: registro de ejecuciones del discovery.
  - MonitorStatus: estado del proceso monitor (singleton).

Ambos son de solo lectura desde el admin — se llenan por el propio
sistema, no por operación manual.
"""
from django.contrib import admin

from .models import DiscoveryJob, MonitorStatus


# ============================================================
# DISCOVERY JOBS
# ============================================================
@admin.register(DiscoveryJob)
class DiscoveryJobAdmin(admin.ModelAdmin):
    list_display = (
        "id", "device", "status", "interfaces_found",
        "interfaces_created", "interfaces_updated",
        "interfaces_deleted", "duration_ms", "started_at",
    )
    list_filter = ("status", "started_at", "device__device_role")
    search_fields = ("device__name", "device__ip", "error_message")
    raw_id_fields = ("device", "triggered_by")
    readonly_fields = (
        "device", "status",
        "interfaces_found", "interfaces_up",
        "interfaces_created", "interfaces_updated", "interfaces_deleted",
        "started_at", "finished_at", "duration_ms",
        "error_message", "triggered_by",
    )
    date_hierarchy = "started_at"

    fieldsets = (
        ("Ejecución", {
            "fields": ("device", "status", "triggered_by")
        }),
        ("Métricas", {
            "fields": (
                "interfaces_found", "interfaces_up",
                "interfaces_created", "interfaces_updated",
                "interfaces_deleted",
            )
        }),
        ("Timing", {
            "fields": ("started_at", "finished_at", "duration_ms")
        }),
        ("Error", {
            "fields": ("error_message",),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        """No se crean jobs manualmente."""
        return False


# ============================================================
# MONITOR STATUS (singleton)
# ============================================================
@admin.register(MonitorStatus)
class MonitorStatusAdmin(admin.ModelAdmin):
    """Estado del monitor (singleton). Solo lectura."""

    list_display = (
        "id", "status", "hostname", "pid", "last_heartbeat",
        "last_traffic_run", "last_health_run", "last_icmp_run",
        "last_radio_run", "last_ap_clients_run",
    )
    readonly_fields = (
        "id", "last_heartbeat", "status", "hostname", "pid",
        "last_traffic_run", "last_health_run",
        "last_icmp_run", "last_radio_run", "last_ap_clients_run",
        "last_error",
    )

    fieldsets = (
        ("Servicio", {
            "fields": ("id", "status", "hostname", "pid", "last_heartbeat")
        }),
        ("Últimos runs", {
            "fields": (
                "last_traffic_run", "last_health_run",
                "last_icmp_run", "last_radio_run",
                "last_ap_clients_run",
            )
        }),
        ("Último error", {
            "fields": ("last_error",),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        """Singleton — no se crea otro."""
        return False

    def has_delete_permission(self, request, obj=None):
        """No se elimina."""
        return False