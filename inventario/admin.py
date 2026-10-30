# inventario/admin.py
"""
Admin de la app `inventario`.

Solo visible para el superadministrador.

Incluye:
  - DeviceModelAdmin: modelos de equipos con OIDs.
  - DeviceAdmin: equipos (con inline de interfaces).
  - InterfaceAdmin: interfaces individuales.
"""
from django.contrib import admin

from .models import Device, DeviceModel, Interface


# ============================================================
# MODELOS DE EQUIPO
# ============================================================
@admin.register(DeviceModel)
class DeviceModelAdmin(admin.ModelAdmin):
    list_display = (
        "id", "vendor", "name", "has_interfaces",
        "is_wireless_link", "has_custom_oids", "has_radio_oids", "active",
    )
    list_filter = ("vendor", "has_interfaces", "is_wireless_link", "active")
    search_fields = ("vendor", "name", "description")
    list_editable = ("active",)
    list_display_links = ("id", "name")

    fieldsets = (
        ("Identificación", {
            "fields": ("vendor", "name", "description", "active")
        }),
        ("Capacidades", {
            "fields": ("has_interfaces", "is_wireless_link"),
            "description": (
                "<strong>Interfaces SNMP:</strong> expone IF-MIB. "
                "<br><strong>Radio-enlace:</strong> es un equipo wireless "
                "(habilita polling de RF y clientes AP)."
            ),
        }),
        ("OIDs de chasis", {
            "fields": ("oids",),
            "description": (
                "JSON con OIDs de CPU, memoria, temperatura, uptime. "
                "Vacío = usa los del fabricante (ver `chassis_oids.py`)."
            ),
        }),
        ("OIDs de radiofrecuencia", {
            "fields": ("radio_oids",),
            "description": (
                "JSON con OIDs de frecuencia, señal, CCQ, tasas. "
                "Solo aplica si `is_wireless_link=True`."
            ),
        }),
        ("Auditoría", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("created_at", "updated_at")

    def has_custom_oids(self, obj):
        return bool(obj.oids)
    has_custom_oids.boolean = True
    has_custom_oids.short_description = "OIDs chasis"

    def has_radio_oids(self, obj):
        return bool(obj.radio_oids)
    has_radio_oids.boolean = True
    has_radio_oids.short_description = "OIDs RF"


# ============================================================
# EQUIPOS
# ============================================================
class InterfaceInline(admin.TabularInline):
    """Inline de interfaces dentro del detalle de equipo."""
    model = Interface
    extra = 0
    fields = (
        "if_index", "if_name", "if_alias",
        "speed_display", "if_type", "oper_status", "monitored",
    )
    readonly_fields = (
        "if_index", "if_name", "if_alias",
        "speed_display", "if_type", "oper_status",
    )
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def speed_display(self, obj):
        if not obj.if_speed_bps:
            return "N/A"
        return f"{obj.if_speed_bps / 1_000_000:.0f} Mbps"
    speed_display.short_description = "Velocidad"


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "ip", "device_type", "device_role",
        "vendor", "device_model", "location",
        "monitor_interfaces", "monitor_health", "active",
    )
    list_filter = (
        "device_role", "vendor", "device_type",
        "monitor_interfaces", "monitor_health", "active",
    )
    search_fields = ("name", "ip", "location")
    list_editable = ("active",)
    list_display_links = ("id", "name")
    inlines = [InterfaceInline]
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("device_model", "dashboard_interface")

    fieldsets = (
        ("Identificación", {
            "fields": (
                "name", "ip", "device_type", "device_role",
                "vendor", "device_model", "location",
            )
        }),
        ("Credenciales SNMP", {
            "fields": (
                "snmp_version", "snmp_community",
                "snmp_user", "snmp_auth", "snmp_priv",
            )
        }),
        ("Monitoreo", {
            "fields": (
                "tcp_ports",
                "monitor_interfaces", "monitor_health",
                "dashboard_interface",
                "active",
            ),
            "description": (
                "<strong>Interfaces:</strong> habilita SNMP Tráfico. "
                "<br><strong>Health:</strong> habilita CPU/Mem/Temp. "
                "<br><strong>Interfaz destacada:</strong> la que se "
                "muestra en la card del dashboard."
            ),
        }),
        ("Auditoría", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


# ============================================================
# INTERFACES
# ============================================================
@admin.register(Interface)
class InterfaceAdmin(admin.ModelAdmin):
    list_display = (
        "id", "device", "if_index", "if_name", "if_alias",
        "speed_display", "oper_status", "monitored",
    )
    list_filter = ("monitored", "oper_status", "device__device_role")
    search_fields = ("device__name", "if_name", "if_alias")
    list_editable = ("monitored",)
    list_display_links = ("id", "if_name")
    raw_id_fields = ("device",)

    def speed_display(self, obj):
        if not obj.if_speed_bps:
            return "N/A"
        return f"{obj.if_speed_bps / 1_000_000:.0f} Mbps"
    speed_display.short_description = "Velocidad"