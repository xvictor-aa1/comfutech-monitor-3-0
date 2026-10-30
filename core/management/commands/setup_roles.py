# core/management/commands/setup_roles.py
"""Comando para crear los grupos de roles del sistema."""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from core.roles import GROUP_ADMIN, GROUP_USER


class Command(BaseCommand):
    help = "Crea los grupos de roles del sistema Comfutech"

    def handle(self, *args, **options):
        """
        Crea los grupos 'Administrador' y 'Usuario' si no existen.
        El rol 'superadmin' se maneja con is_superuser=True (no es grupo).
        """
        for name in (GROUP_ADMIN, GROUP_USER):
            group, created = Group.objects.get_or_create(name=name)
            if created:
                self.stdout.write(self.style.SUCCESS(f"[+] Grupo '{name}' creado"))
            else:
                self.stdout.write(self.style.WARNING(f"[=] Grupo '{name}' ya existía"))

        self.stdout.write(self.style.SUCCESS(
            "\nRoles configurados. Los superusuarios (is_superuser=True) "
            "tienen el rol 'superadmin' automáticamente."
        ))