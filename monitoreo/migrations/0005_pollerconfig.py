# monitoreo/migrations/0005_pollerconfig.py

import tomllib
from pathlib import Path

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


def import_toml_intervals(apps, schema_editor):
    PollerConfig = apps.get_model("monitoreo", "PollerConfig")
    defaults = {
        "snmp_poll_interval": 60,
        "health_poll_interval": 120,
        "icmp_poll_interval": 120,
        "radio_poll_interval": 120,
        "ap_clients_poll_interval": 120,
    }
    config_path = Path(
        getattr(settings, "COMFUTECH_CONFIG_FILE", settings.BASE_DIR / "config.toml")
    )
    try:
        with config_path.open("rb") as config_file:
            monitor = tomllib.load(config_file).get("monitor", {})
        for key, default in defaults.items():
            try:
                defaults[key] = max(10, min(3600, int(monitor.get(key, default))))
            except (TypeError, ValueError):
                defaults[key] = default
    except (OSError, tomllib.TOMLDecodeError):
        pass
    PollerConfig.objects.using(schema_editor.connection.alias).update_or_create(
        pk=1, defaults=defaults
    )


class Migration(migrations.Migration):

    dependencies = [
        ("monitoreo", "0004_rename_telegram_co_last_se_7a3b1c_idx_telegram_co_last_se_c815ad_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="PollerConfig",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("snmp_poll_interval", models.PositiveIntegerField(default=60, validators=[MinValueValidator(10), MaxValueValidator(3600)], verbose_name="Intervalo SNMP (s)")),
                ("health_poll_interval", models.PositiveIntegerField(default=120, validators=[MinValueValidator(10), MaxValueValidator(3600)], verbose_name="Intervalo Health (s)")),
                ("icmp_poll_interval", models.PositiveIntegerField(default=120, validators=[MinValueValidator(10), MaxValueValidator(3600)], verbose_name="Intervalo ICMP (s)")),
                ("radio_poll_interval", models.PositiveIntegerField(default=120, validators=[MinValueValidator(10), MaxValueValidator(3600)], verbose_name="Intervalo Radio (s)")),
                ("ap_clients_poll_interval", models.PositiveIntegerField(default=120, validators=[MinValueValidator(10), MaxValueValidator(3600)], verbose_name="Intervalo clientes AP (s)")),
            ],
            options={
                "verbose_name": "Configuración de Pollers",
                "verbose_name_plural": "Configuración de Pollers",
                "db_table": "monitor_poller_config",
            },
        ),
        migrations.RunPython(import_toml_intervals, migrations.RunPython.noop),
    ]