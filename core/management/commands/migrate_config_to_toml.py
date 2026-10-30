# core/management/commands/migrate_config_to_toml.py
"""
Migra la configuración de la BD (SystemConfig + EmailConfig) a config.toml.

Uso:
    python manage.py migrate_config_to_toml
    python manage.py migrate_config_to_toml --backup-bd

Si existe un config.ini legacy, este comando NO lo toca — la migración
INI → TOML es automática cuando config.toml no existe y config.ini sí
(ver core/config_ini._migrate_from_ini_if_needed).

Después de ejecutar este comando, puedes dejar de usar los modelos
`SystemConfig` y `EmailConfig` (quedan deprecated). Los datos en BD
NO se eliminan; se conservan por si necesitas revertir.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from core import config_ini
from core.models import SystemConfig, EmailConfig


class Command(BaseCommand):
    help = "Migra la configuración de la BD a config.toml"

    def add_arguments(self, parser):
        parser.add_argument(
            "--backup-bd", action="store_true",
            help="Guarda un backup JSON de la config actual de la BD",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== Migración de configuración BD → config.toml ===\n"
        ))

        # ------------------------------------------------------------
        # Backup de la BD (opcional)
        # ------------------------------------------------------------
        if options["backup_bd"]:
            try:
                sc = SystemConfig.get()
                ec = EmailConfig.get()
                backup = {
                    "system_config": {
                        "influx_url": sc.influx_url,
                        "influx_token": sc.influx_token,
                        "influx_org": sc.influx_org,
                        "influx_bucket": sc.influx_bucket,
                        "grafana_url": sc.grafana_url,
                        "telegram_bot_token": sc.telegram_bot_token,
                        "telegram_chat_id": sc.telegram_chat_id,
                        "telegram_enabled": sc.telegram_enabled,
                        "monitor_enabled": sc.monitor_enabled,
                        "snmp_poll_interval": sc.snmp_poll_interval,
                        "health_poll_interval": sc.health_poll_interval,
                        "icmp_poll_interval": sc.icmp_poll_interval,
                    },
                    "email_config": {
                        "email_host": ec.email_host,
                        "email_port": ec.email_port,
                        "email_use_tls": ec.email_use_tls,
                        "email_use_ssl": ec.email_use_ssl,
                        "email_host_user": ec.email_host_user,
                        "email_host_password": ec.email_host_password,
                        "default_from_email": ec.default_from_email,
                    },
                }
                out = Path("backups") / "config_backup_bd.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(
                    json.dumps(backup, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                self.stdout.write(self.style.SUCCESS(
                    f"✓ Backup BD guardado en {out}"
                ))
            except Exception as e:
                self.stdout.write(self.style.WARNING(
                    f"⚠️ No se pudo crear backup: {e}"
                ))

        # ------------------------------------------------------------
        # Leer BD
        # ------------------------------------------------------------
        try:
            sc = SystemConfig.get()
        except Exception:
            sc = None
        try:
            ec = EmailConfig.get()
        except Exception:
            ec = None

        if not sc and not ec:
            self.stdout.write(self.style.WARNING(
                "No hay config en BD. Nada que migrar."
            ))
            return

        # ------------------------------------------------------------
        # Construir updates
        # ------------------------------------------------------------
        updates = {}

        if sc:
            updates["influxdb"] = {
                "url": sc.influx_url or "http://localhost:8086",
                "token": sc.influx_token or "",
                "org": sc.influx_org or "comfutech",
                "bucket": sc.influx_bucket or "metricas_red",
            }
            updates["grafana"] = {
                "url": sc.grafana_url or "http://localhost:3000",
            }
            updates["telegram"] = {
                "enabled": bool(sc.telegram_enabled),
                "bot_token": sc.telegram_bot_token or "",
                "chat_id": sc.telegram_chat_id or "",
            }
            updates["monitor"] = {
                "enabled": bool(sc.monitor_enabled),
                "snmp_poll_interval": sc.snmp_poll_interval or 60,
                "health_poll_interval": sc.health_poll_interval or 120,
                "icmp_poll_interval": sc.icmp_poll_interval or 120,
                "radio_poll_interval": sc.health_poll_interval or 120,
                "ap_clients_poll_interval": sc.health_poll_interval or 120,
            }

        if ec:
            updates["email"] = {
                "host": ec.email_host or "smtp.gmail.com",
                "port": ec.email_port or 587,
                "use_tls": bool(ec.email_use_tls),
                "use_ssl": bool(ec.email_use_ssl),
                "host_user": ec.email_host_user or "",
                "host_password": ec.email_host_password or "",
                "default_from": (
                    ec.default_from_email
                    or "Comfutech Monitor <noreply@comfutech.local>"
                ),
            }

        # ------------------------------------------------------------
        # Escribir
        # ------------------------------------------------------------
        try:
            config_ini.write_sections(updates, updated_by="migrate_command")
            self.stdout.write(self.style.SUCCESS(
                f"✓ Configuración migrada a {config_ini.CONFIG_PATH}"
            ))
            self.stdout.write("\nSecciones escritas:")
            for section, values in updates.items():
                self.stdout.write(f"  • [{section}] ({len(values)} campos)")
            self.stdout.write("\n" + self.style.WARNING(
                "⚠️ Los modelos SystemConfig y EmailConfig quedan "
                "deprecated. NO se eliminan automáticamente."
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f"❌ Error escribiendo config.toml: {e}"
            ))