# alertas/admin.py
"""
Admin de la app `alertas`.

Solo visible para el superadministrador.

Fix histórico: eliminada la referencia a `Threshold` (modelo removido).
Se añade `AlertRuleAdmin` con display resumido de la estructura v2.
"""
from django.contrib import admin
from django.utils import timezone

from .models import Alert, AlertRule


# ============================================================
# ALERTAS
# ============================================================
@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = (
        "id", "severity", "alert_type", "device",
        "value_observed", "status", "created_at",
    )
    list_filter = ("severity", "status", "alert_type", "created_at")
    search_fields = ("message", "device__name", "alert_type", "rule__name")
    list_display_links = ("id", "severity")
    readonly_fields = ("created_at", "resolved_at")
    raw_id_fields = ("device", "interface", "rule")
    date_hierarchy = "created_at"
    actions = ["mark_resolved", "mark_acknowledged"]

    fieldsets = (
        ("Información", {
            "fields": ("device", "interface", "rule", "alert_type", "severity")
        }),
        ("Detalle", {
            "fields": ("message", "value_observed", "threshold_value")
        }),
        ("Estado", {
            "fields": ("status", "created_at", "resolved_at")
        }),
    )

    @admin.action(description="Marcar como resueltas")
    def mark_resolved(self, request, queryset):
        updated = queryset.filter(status__in=["activa", "reconocida"]).update(
            status="resuelta",
            resolved_at=timezone.now(),
        )
        self.message_user(request, f"{updated} alerta(s) marcada(s) como resueltas.")

    @admin.action(description="Marcar como reconocidas")
    def mark_acknowledged(self, request, queryset):
        updated = queryset.filter(status="activa").update(status="reconocida")
        self.message_user(request, f"{updated} alerta(s) marcada(s) como reconocidas.")


# ============================================================
# REGLAS DE ALERTA (v2 con grupos)
# ============================================================
@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    """
    Admin de reglas de alerta (formato v2 con grupos).

    Los condicionales se editan como JSON crudo. El formato es:

        {
          "version": 2,
          "groups": [
            {
              "logic": null,
              "negate": false,
              "operators": ["AND"],
              "conditionals": [
                {"device_id": 1, "metric": "cpu_pct",
                 "operator": "gte", "threshold": 85,
                 "duration_sec": 60, "negate": false}
              ]
            }
          ]
        }

    Para editar reglas complejas, mejor usa la UI en `/alertas/reglas/`.
    Este admin es para inspección y corrección directa.
    """
    list_display = (
        "id", "name", "severity", "enabled",
        "groups_count_display", "conditionals_count_display",
        "telegram_enabled", "fire_once", "updated_at",
    )
    list_filter = (
        "severity", "enabled", "telegram_enabled",
        "fire_once", "skip_on_startup", "updated_at",
    )
    search_fields = ("name", "description", "custom_message")
    readonly_fields = (
        "created_at", "updated_at",
        "groups_count_display", "conditionals_count_display",
    )
    raw_id_fields = ("created_by",)
    date_hierarchy = "updated_at"

    fieldsets = (
        ("Identificación", {
            "fields": ("name", "description", "severity", "enabled")
        }),
        ("Condicionales (v2)", {
            "fields": (
                "conditionals",
                "groups_count_display",
                "conditionals_count_display",
            ),
            "description": (
                "Formato: "
                '{"version": 2, "groups": [{...}]}. '
                "Máximo 5 grupos, 5 condicionales por grupo, "
                "10 condicionales totales."
            ),
        }),
        ("Mensaje y notificación", {
            "fields": (
                "custom_message",
                "telegram_enabled",
                "telegram_cooldown_sec",
            )
        }),
        ("Comportamiento", {
            "fields": ("fire_once", "skip_on_startup")
        }),
        ("Auditoría", {
            "fields": ("created_by", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def groups_count_display(self, obj):
        return obj.groups_count
    groups_count_display.short_description = "Grupos"

    def conditionals_count_display(self, obj):
        return obj.conditionals_count
    conditionals_count_display.short_description = "Condicionales"