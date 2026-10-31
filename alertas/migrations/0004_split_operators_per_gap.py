# alertas/migrations/0004_split_operators_per_gap.py
"""
Convierte `group.operator` (string uniforme) a `group.operators` (lista N-1).

Antes:
    {"operator": "AND", "conditionals": [c1, c2, c3]}
Después:
    {"operators": ["AND", "AND"], "conditionals": [c1, c2, c3]}

Idempotente: si ya existe `operators`, no toca el grupo.
"""
from django.db import migrations


def migrate_to_operators_list(apps, schema_editor):
    AlertRule = apps.get_model("alertas", "AlertRule")
    for rule in AlertRule.objects.all():
        cond = rule.conditionals
        if not isinstance(cond, dict) or "groups" not in cond:
            continue

        changed = False
        for g in cond["groups"]:
            conds_count = len(g.get("conditionals", []))

            if "operators" not in g:
                old_op = g.get("operator", "AND")
                if old_op not in ("AND", "OR", "XOR"):
                    old_op = "AND"
                g["operators"] = [old_op] * max(0, conds_count - 1)
                changed = True

            if "operator" in g:
                del g["operator"]
                changed = True

        if changed:
            rule.conditionals = cond
            rule.save(update_fields=["conditionals"])


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("alertas", "0003_alter_alertrule_conditionals_and_more"),
    ]
    operations = [
        migrations.RunPython(migrate_to_operators_list, reverse_noop),
    ]