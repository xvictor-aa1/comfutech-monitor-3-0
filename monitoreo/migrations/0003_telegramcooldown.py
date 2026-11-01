# monitoreo/migrations/0003_telegramcooldown.py
"""
Crea la tabla `telegram_cooldowns` para persistir el cooldown de
Telegram entre reinicios del monitor.

Antes de v4, el cooldown vivía solo en memoria (`_last_sent` en
`telegram.py`), por lo que se perdía al reiniciar el servicio.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitoreo", "0002_monitorstatus_last_errors"),
    ]

    operations = [
        migrations.CreateModel(
            name="TelegramCooldown",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(db_index=True, max_length=200, unique=True, verbose_name="Clave de cooldown")),
                ("last_sent_at", models.DateTimeField(verbose_name="Último envío")),
            ],
            options={
                "verbose_name": "Cooldown de Telegram",
                "verbose_name_plural": "Cooldowns de Telegram",
                "db_table": "telegram_cooldowns",
                "indexes": [models.Index(fields=["last_sent_at"], name="telegram_co_last_se_7a3b1c_idx")],
            },
        ),
    ]