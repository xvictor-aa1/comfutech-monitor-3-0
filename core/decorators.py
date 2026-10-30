# core/decorators.py
"""
Decoradores de permisos.

Uso correcto (SIEMPRE con paréntesis):

    @require_admin_or_super()
    def mi_vista(request):
        ...

    @require_superadmin()
    def mi_vista(request):
        ...

    @require_role(ROLE_ADMIN, ROLE_SUPERADMIN)
    def mi_vista(request):
        ...
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .roles import get_user_role, ROLE_SUPERADMIN, ROLE_ADMIN


def require_role(*allowed_roles):
    """
    Fábrica de decoradores que restringe el acceso según el rol.

    Args:
        *allowed_roles: roles permitidos para acceder.

    Returns:
        decorator: un decorador listo para aplicar a una vista.
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            role = get_user_role(request.user)
            if role not in allowed_roles:
                raise PermissionDenied("No tienes permisos para esta sección.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_admin_or_super():
    """
    Fábrica de decoradores para roles Admin o Superadmin.

    Uso: @require_admin_or_super()
    """
    return require_role(ROLE_SUPERADMIN, ROLE_ADMIN)


def require_superadmin():
    """
    Fábrica de decoradores solo para Superadmin.

    Uso: @require_superadmin()
    """
    return require_role(ROLE_SUPERADMIN)