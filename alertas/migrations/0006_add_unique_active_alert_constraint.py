# alertas/migrations/0006_add_unique_active_alert_constraint.py
"""
Añade un UniqueConstraint a `Alert` que garantiza que no haya más de
una alerta activa por regla.

Esto resuelve la race condition entre pollers concurrentes que evalúan
la misma regla: sin constraint, dos pollers podrían crear dos alertas
activas simultáneamente. Con el constraint, el segundo recibe un
`IntegrityError` que `_create_alert_for_rule` captura y maneja como
"ya existe" (no es un error).

IMPORTANTE: antes de aplicar esta migración, verifica que no haya
alertas activas duplicadas por regla en la BD:

    from alertas.models import Alert
    from django.db.models import Count
    dups = (Alert.objects.filter(status="activa")
            .values("rule_id").annotate(c=Count("id")).filter(c__gt=1))
    print(list(dups))

Si hay duplicados, resuélvelos manualmente (deja solo una activa por
regla) antes de migrar.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("alertas", "0005_unlink_alerts_and_add_auto_resolve"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="alert",
            constraint=models.UniqueConstraint(
                fields=["rule_id"],
                condition=models.Q(status="activa"),
                name="unique_active_alert_per_rule",
            ),
        ),
    ]