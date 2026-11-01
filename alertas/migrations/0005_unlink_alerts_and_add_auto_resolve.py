# alertas/migrations/0005_unlink_alerts_and_add_auto_resolve.py
"""
Migración v4: desacoplamiento de `Alert` respecto a `Device`,
`Interface` y `AlertRule`, más adición de los campos de
auto-resolución a `AlertRule`.

Pasos:
  1. Añadir a `Alert` el campo `rule_name` (CharField, default "")
     y `rule_id_ref` (IntegerField, null) temporales.
  2. Añadir a `AlertRule`: `auto_resolve_conditionals` (JSON),
     `enable_auto_resolve` (bool), `mark_as_resolved` (bool).
  3. Copiar los datos existentes: `rule_id_ref = rule_id` (FK),
     `rule_name = rule.name`.
  4. Eliminar las FKs `device`, `interface` y `rule` de `Alert`.
  5. Renombrar `rule_id_ref` → `rule_id`.
"""
from django.db import migrations, models


def forwards_copy_rule_data(apps, schema_editor):
    """
    Copia el ID y nombre de la regla desde la FK a los nuevos campos
    planos antes de eliminar la FK.
    """
    Alert = apps.get_model("alertas", "Alert")

    # select_related es válido porque el modelo histórico mantiene la FK
    for alert in Alert.objects.select_related("rule").all():
        if alert.rule_id is not None:
            alert.rule_id_ref = alert.rule_id
            alert.rule_name = alert.rule.name if alert.rule else ""
            alert.save(update_fields=["rule_id_ref", "rule_name"])


def reverse_noop(apps, schema_editor):
    """
    No reversible de forma fiable: reconstruir las FKs perdería
    alertas cuya regla fuera eliminada. En caso de rollback, las
    FKs quedarían en NULL para todas las alertas.
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("alertas", "0004_split_operators_per_gap"),
    ]

    operations = [
        # ------------------------------------------------------------
        # 1. Alert: nuevos campos temporales (snapshot + rule_id plano)
        # ------------------------------------------------------------
        migrations.AddField(
            model_name="alert",
            name="rule_name",
            field=models.CharField(
                blank=True, default="", max_length=150,
                verbose_name="Nombre de la regla (snapshot)",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="alert",
            name="rule_id_ref",
            field=models.IntegerField(
                null=True, blank=True, db_index=True,
                verbose_name="ID de la regla (temporal)",
            ),
        ),

        # ------------------------------------------------------------
        # 2. AlertRule: campos de auto-resolución y mark_as_resolved
        # ------------------------------------------------------------
        migrations.AddField(
            model_name="alertrule",
            name="auto_resolve_conditionals",
            field=models.JSONField(
                default=dict, blank=True,
                verbose_name="Condicionales para resolver la Alerta",
            ),
        ),
        migrations.AddField(
            model_name="alertrule",
            name="enable_auto_resolve",
            field=models.BooleanField(
                default=False,
                verbose_name="Habilitar auto-resolución por condicionales",
            ),
        ),
        migrations.AddField(
            model_name="alertrule",
            name="mark_as_resolved",
            field=models.BooleanField(
                default=False,
                verbose_name="Crear alertas ya resueltas",
            ),
        ),

        # ------------------------------------------------------------
        # 3. Copiar datos de la FK a los nuevos campos planos
        # ------------------------------------------------------------
        migrations.RunPython(forwards_copy_rule_data, reverse_noop),

        # ------------------------------------------------------------
        # 4. Eliminar FKs de Alert
        # ------------------------------------------------------------
        migrations.RemoveField(model_name="alert", name="device"),
        migrations.RemoveField(model_name="alert", name="interface"),
        migrations.RemoveField(model_name="alert", name="rule"),

        # ------------------------------------------------------------
        # 5. Renombrar rule_id_ref → rule_id
        # ------------------------------------------------------------
        migrations.RenameField(
            model_name="alert",
            old_name="rule_id_ref",
            new_name="rule_id",
        ),
    ]