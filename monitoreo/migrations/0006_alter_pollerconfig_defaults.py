# monitoreo/migrations/0006_alter_pollerconfig_defaults.py
"""
Actualiza los defaults de `PollerConfig` a los nuevos valores
operativos y migra la fila existente (pk=1) SOLO si aún tiene los
defaults antiguos.

Reglas:
  - Si la fila tiene los defaults viejos (60/120/120/120/120), se
    actualiza a los nuevos (30/60/30/60/60).
  - Si el usuario ya cambió algún valor manualmente desde la UI o
    desde el shell, se respeta su cambio y no se sobreescribe.

Esto garantiza que el despliegue no pise configuraciones en curso,
pero sí aplique los nuevos valores por defecto a las instalaciones
que aún no los hayan tocado.
"""
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


# Valores operativos nuevos (según la configuración actual del proyecto).
NEW_DEFAULTS = {
    "snmp_poll_interval": 30,
    "health_poll_interval": 60,
    "icmp_poll_interval": 30,
    "radio_poll_interval": 60,
    "ap_clients_poll_interval": 60,
}

# Defaults anteriores (para detectar filas que nunca se tocaron).
OLD_DEFAULTS = {
    "snmp_poll_interval": 60,
    "health_poll_interval": 120,
    "icmp_poll_interval": 120,
    "radio_poll_interval": 120,
    "ap_clients_poll_interval": 120,
}


def forwards_update_existing_row(apps, schema_editor):
    """
    Actualiza la fila existente (pk=1) SOLO si los valores actuales
    coinciden con los defaults antiguos.

    Si el usuario ya los cambió manualmente, se respeta su cambio.
    """
    PollerConfig = apps.get_model("monitoreo", "PollerConfig")
    db_alias = schema_editor.connection.alias
    config = PollerConfig.objects.using(db_alias).filter(pk=1).first()

    if not config:
        return

    update_fields = []
    for field, old_value in OLD_DEFAULTS.items():
        if getattr(config, field) == old_value:
            setattr(config, field, NEW_DEFAULTS[field])
            update_fields.append(field)

    if update_fields:
        config.save(update_fields=update_fields, using=db_alias)


def reverse_noop(apps, schema_editor):
    """No reversible de forma fiable (no se guarda el estado anterior)."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("monitoreo", "0005_pollerconfig"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pollerconfig",
            name="snmp_poll_interval",
            field=models.PositiveIntegerField(
                default=30,
                validators=[MinValueValidator(10), MaxValueValidator(3600)],
                verbose_name="Intervalo SNMP (s)",
            ),
        ),
        migrations.AlterField(
            model_name="pollerconfig",
            name="health_poll_interval",
            field=models.PositiveIntegerField(
                default=60,
                validators=[MinValueValidator(10), MaxValueValidator(3600)],
                verbose_name="Intervalo Health (s)",
            ),
        ),
        migrations.AlterField(
            model_name="pollerconfig",
            name="icmp_poll_interval",
            field=models.PositiveIntegerField(
                default=30,
                validators=[MinValueValidator(10), MaxValueValidator(3600)],
                verbose_name="Intervalo ICMP (s)",
            ),
        ),
        migrations.AlterField(
            model_name="pollerconfig",
            name="radio_poll_interval",
            field=models.PositiveIntegerField(
                default=60,
                validators=[MinValueValidator(10), MaxValueValidator(3600)],
                verbose_name="Intervalo Radio (s)",
            ),
        ),
        migrations.AlterField(
            model_name="pollerconfig",
            name="ap_clients_poll_interval",
            field=models.PositiveIntegerField(
                default=60,
                validators=[MinValueValidator(10), MaxValueValidator(3600)],
                verbose_name="Intervalo clientes AP (s)",
            ),
        ),
        migrations.RunPython(
            forwards_update_existing_row,
            reverse_noop,
        ),
    ]