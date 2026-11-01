# alertas/admin.py
"""
Admin de la app `alertas`.

Solo visible para el superadministrador.

Fix histórico: eliminada la referencia a `Threshold` (modelo removido).

A partir de la v4:
  · `Alert` ya NO tiene ForeignKeys hacia `Device`, `Interface` ni
    `AlertRule`. El admin refleja esto:
      - Se eliminan los `raw_id_fields` de device/interface/rule.
      - Se exponen `rule_id` (IntegerField) y `rule_name` (snapshot)
        como campos de solo lectura para auditoría.
      - El listado y los filtros usan `rule_id` / `rule_name` en
        lugar de FKs.

  · `AlertRule` incorpora tres campos nuevos:
      - `auto_resolve_conditionals` (JSON v2 opcional)
      - `enable_auto_resolve` (bool)
      - `mark_as_resolved` (bool)
    Se añaden a los fieldsets correspondientes y al listado.
"""
from django.contrib import admin
from django.utils import timezone

from .models import Alert, AlertRule


# ============================================================
# ALERTAS
# ============================================================
@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    """
    Admin de alertas generadas.

    A partir de la v4, `Alert` es un registro histórico desacoplado:
      · No hay FKs a Device/Interface/AlertRule.
      · El vínculo lógico con la regla se hace vía `rule_id`
        (IntegerField indexado) + `rule_name` (snapshot).
      · Las consultas y filtros del admin usan esos campos planos.
    """
    list_display = (
        "id", "severity", "alert_type",
        "rule_id", "rule_name",
        "value_observed", "status", "created_at",
    )
    list_filter = (
        "severity", "status", "alert_type",
        "rule_id", "created_at",
    )
    search_fields = (
        "message", "rule_name", "alert_type",
    )
    list_display_links = ("id", "severity")
    readonly_fields = ("created_at", "resolved_at", "rule_id", "rule_name")
    date_hierarchy = "created_at"
    actions = ["mark_resolved", "mark_acknowledged"]

    fieldsets = (
        ("Información", {
            "fields": (
                "rule_id", "rule_name",
                "alert_type", "severity",
            ),
        }),
        ("Detalle", {
            "fields": ("message", "value_observed", "threshold_value"),
        }),
        ("Estado", {
            "fields": ("status", "created_at", "resolved_at"),
        }),
    )

    @admin.action(description="Marcar como resueltas")
    def mark_resolved(self, request, queryset):
        """
        Acción masiva: marcar alertas seleccionadas como resueltas.

        Solo actúa sobre alertas en estado "activa" o "reconocida"
        (no re-resuelve las ya resueltas).
        """
        updated = queryset.filter(status__in=["activa", "reconocida"]).update(
            status="resuelta",
            resolved_at=timezone.now(),
        )
        self.message_user(
            request, f"{updated} alerta(s) marcada(s) como resueltas."
        )

    @admin.action(description="Marcar como reconocidas")
    def mark_acknowledged(self, request, queryset):
        """
        Acción masiva: marcar alertas seleccionadas como reconocidas.

        Solo actúa sobre alertas en estado "activa" (no re-reconoce
        las ya reconocidas o resueltas).
        """
        updated = queryset.filter(status="activa").update(status="reconocida")
        self.message_user(
            request, f"{updated} alerta(s) marcada(s) como reconocidas."
        )


# ============================================================
# REGLAS DE ALERTA (v2 con grupos + auto-resolución)
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

    A partir de la v4, existen DOS bloques de condicionales:
      · `conditionals` — disparo (obligatorio).
      · `auto_resolve_conditionals` — auto-resolución (opcional).

    El bloque de auto-resolución solo se evalúa si
    `enable_auto_resolve=True` y hay al menos un condicional en su JSON.

    Para editar reglas complejas, mejor usa la UI en `/alertas/reglas/`.
    Este admin es para inspección y corrección directa.
    """
    list_display = (
        "id", "name", "severity", "enabled",
        "groups_count_display", "conditionals_count_display",
        "auto_resolve_display",
        "mark_as_resolved",
        "telegram_enabled", "fire_once", "updated_at",
    )
    list_filter = (
        "severity", "enabled", "telegram_enabled",
        "fire_once", "skip_on_startup",
        "enable_auto_resolve", "mark_as_resolved",
        "updated_at",
    )
    search_fields = ("name", "description", "custom_message")
    readonly_fields = (
        "created_at", "updated_at",
        "groups_count_display", "conditionals_count_display",
        "auto_resolve_groups_count_display",
        "auto_resolve_conditionals_count_display",
    )
    raw_id_fields = ("created_by",)
    date_hierarchy = "updated_at"

    fieldsets = (
        ("Identificación", {
            "fields": ("name", "description", "severity", "enabled")
        }),
        ("Condicionales para disparar la Alerta (v2)", {
            "fields": (
                "conditionals",
                "groups_count_display",
                "conditionals_count_display",
            ),
            "description": (
                "Formato: "
                '{"version": 2, "groups": [{...}]}. '
                "Máximo 5 grupos, 5 condicionales por grupo, "
                "10 condicionales totales. "
                "<strong>OBLIGATORIO</strong>: sin ellos la regla no dispara."
            ),
        }),
        ("Condicionales para resolver la Alerta (v2, opcional)", {
            "fields": (
                "enable_auto_resolve",
                "auto_resolve_conditionals",
                "auto_resolve_groups_count_display",
                "auto_resolve_conditionals_count_display",
            ),
            "description": (
                "Mismo formato que el bloque de disparo. Si está vacío "
                "o <code>enable_auto_resolve</code> está desactivado, "
                "el sistema resuelve las alertas cuando las condiciones "
                "de disparo dejen de cumplirse (comportamiento clásico)."
            ),
        }),
        ("Comportamiento al disparar", {
            "fields": ("mark_as_resolved", "fire_once", "skip_on_startup"),
            "description": (
                "<code>mark_as_resolved</code>: crea las alertas ya en "
                "estado 'resuelta' (útil para reglas informativas). "
                "Las alertas creadas así se deduplican como "
                "<code>fire_once</code>."
            ),
        }),
        ("Mensaje y notificación", {
            "fields": (
                "custom_message",
                "telegram_enabled",
                "telegram_cooldown_sec",
            )
        }),
        ("Auditoría", {
            "fields": ("created_by", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    # ------------------------------------------------------------
    # DISPLAY HELPERS
    # ------------------------------------------------------------
    def groups_count_display(self, obj):
        """Número de grupos de condicionales de DISPARO."""
        return obj.groups_count
    groups_count_display.short_description = "Grupos (disparo)"

    def conditionals_count_display(self, obj):
        """Número total de condicionales de DISPARO."""
        return obj.conditionals_count
    conditionals_count_display.short_description = "Cond. (disparo)"

    def auto_resolve_groups_count_display(self, obj):
        """Número de grupos de condicionales de AUTO-RESOLUCIÓN."""
        return obj.auto_resolve_groups_count
    auto_resolve_groups_count_display.short_description = "Grupos (auto)"

    def auto_resolve_conditionals_count_display(self, obj):
        """Número total de condicionales de AUTO-RESOLUCIÓN."""
        return obj.auto_resolve_conditionals_count
    auto_resolve_conditionals_count_display.short_description = "Cond. (auto)"

    def auto_resolve_display(self, obj):
        """
        Indicador visual del estado de auto-resolución.

        Devuelve:
          · "✓ Nc" si está habilitada y tiene N condicionales.
          · "—" si está deshabilitada o el bloque está vacío.
        """
        if obj.has_auto_resolve:
            return f"✓ {obj.auto_resolve_conditionals_count}c"
        return "—"
    auto_resolve_display.short_description = "Auto-resolve"
    auto_resolve_display.admin_order_field = "enable_auto_resolve"