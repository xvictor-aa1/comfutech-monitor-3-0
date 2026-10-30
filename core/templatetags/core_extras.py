# core/templatetags/core_extras.py
"""Filtros de template personalizados."""
from django import template

register = template.Library()


@register.filter
def has_group(user, group_name):
    """
    Devuelve True si el usuario pertenece al grupo indicado.

    Uso en template: {% if user|has_group:"Administrador" %}
    """
    if not user or not user.is_authenticated:
        return False
    return user.groups.filter(name=group_name).exists()