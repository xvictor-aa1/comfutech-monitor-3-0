# monitoreo/migrations/0002_monitorstatus_last_errors.py
"""
Añade `MonitorStatus.last_errors` (JSONField) para guardar el último
error por poller.

A partir de aqui, en lugar de un único `last_error` (que solo guardaba
el último error global), se mantiene un diccionario 
`{"poller": {"msg": "...", "ts": "..."}}` con el error más reciente
de cada poller. Se limpia automáticamente cuando el poller recupera.

`last_error` se conserva (deprecado) por compatibilidad con datos
históricos y migraciones previas. Se eliminará en una versión futura.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitoreo", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitorstatus",
            name="last_errors",
            field=models.JSONField(
                default=dict, blank=True,
                verbose_name="Últimos errores por poller",
                help_text=(
                    "Diccionario {poller: {msg, ts}} con el último error de "
                    "cada poller. Se limpia automáticamente cuando el poller "
                    "vuelve a tener éxito."
                ),
            ),
        ),
    ]