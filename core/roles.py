# core/roles.py
"""
Sistema de roles basado en grupos de Django.

Roles disponibles:
  - superadmin: superusuario de Django (is_superuser=True).
  - administrador: grupo "Administrador".
  - usuario: grupo "Usuario".

Reglas:
  - Solo puede existir un superadmin (el primero se crea en setup).
  - Los admins no pueden crear/editar/eliminar a otros admins o superadmins.
  - Los admins no pueden asignar el rol de superadmin.
"""
from django.contrib.auth.models import Group

# Nombres de rol internos
ROLE_SUPERADMIN = "superadmin"
ROLE_ADMIN = "administrador"
ROLE_USER = "usuario"

# Nombres de los grupos de Django
GROUP_ADMIN = "Administrador"
GROUP_USER = "Usuario"


def get_user_role(user):
    """Devuelve el rol lógico de un usuario."""
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return ROLE_SUPERADMIN
    if user.groups.filter(name=GROUP_ADMIN).exists():
        return ROLE_ADMIN
    if user.groups.filter(name=GROUP_USER).exists():
        return ROLE_USER
    return "sin_rol"


def get_role_display(role):
    """Devuelve la etiqueta legible del rol."""
    return {
        ROLE_SUPERADMIN: "Superadministrador",
        ROLE_ADMIN: "Administrador",
        ROLE_USER: "Usuario",
        "sin_rol": "Sin rol",
    }.get(role, role or "—")


def set_user_role(user, role):
    """
    Asigna un rol a un usuario.
    Solo puede haber un rol a la vez. El superadmin se marca con
    is_superuser=True.
    """
    user.groups.clear()
    if role == ROLE_SUPERADMIN:
        user.is_superuser = True
        user.is_staff = True
    elif role == ROLE_ADMIN:
        user.is_superuser = False
        user.is_staff = True
        user.groups.add(Group.objects.get(name=GROUP_ADMIN))
    elif role == ROLE_USER:
        user.is_superuser = False
        user.is_staff = False
        user.groups.add(Group.objects.get(name=GROUP_USER))
    user.save()


def can_manage_users(actor, target=None):
    """
    ¿Puede `actor` gestionar usuarios?

    Args:
        actor: usuario que realiza la acción.
        target: usuario objetivo (None para acceso general al listado).

    Returns:
        bool: True si tiene permisos.
    """
    if not actor or not actor.is_authenticated:
        return False

    actor_role = get_user_role(actor)

    if actor_role == ROLE_SUPERADMIN:
        return True

    if actor_role == ROLE_ADMIN:
        if target is None:
            return True
        target_role = get_user_role(target)
        return target_role == ROLE_USER

    return False


def assignable_roles(actor):
    """
    Devuelve los roles que `actor` puede asignar desde el formulario.

    NUNCA incluye superadmin, ya que solo puede existir uno, creado
    en el setup inicial.
    """
    if not actor or not actor.is_authenticated:
        return []

    actor_role = get_user_role(actor)

    if actor_role == ROLE_SUPERADMIN:
        return [ROLE_ADMIN, ROLE_USER]

    if actor_role == ROLE_ADMIN:
        return [ROLE_USER]

    return []