# core/context_processors.py
"""
Context processors que inyectan variables globales en todos los templates.

Inyecta:
  - grafana_url: URL del dashboard de Grafana (validada).
  - grafana_available: True si la URL de Grafana responde o no está configurada.
  - is_superadmin: True si el usuario es superadmin.
  - is_admin: True si el usuario es admin o superadmin.
"""
import logging
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)

# Tiempo en segundos para cachear el resultado del chequeo de Grafana
GRAFANA_CACHE_SECONDS = 300


def _is_grafana_available(url: str) -> bool:
    """
    Comprueba si la URL de Grafana responde.

    Se cachea el resultado por GRAFANA_CACHE_SECONDS segundos para no
    golpear la URL en cada request.

    Args:
        url: URL de Grafana a comprobar.

    Returns:
        bool: True si responde con status < 400.
    """
    if not url:
        return False

    # Validar formato mínimo
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
    except Exception:
        return False

    cache_key = f"grafana_available::{url}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        import requests
        r = requests.get(url, timeout=2, allow_redirects=True)
        available = r.status_code < 400
    except Exception:
        available = False

    cache.set(cache_key, available, GRAFANA_CACHE_SECONDS)
    return available


def comfutech_context(request):
    """
    Inyecta variables globales útiles en cada template:
      - grafana_url: URL de Grafana (o vacío si no configurada).
      - grafana_available: True si la URL responde correctamente.
      - is_superadmin / is_admin: roles del usuario.
    """
    user = request.user

    is_superadmin = user.is_authenticated and user.is_superuser
    is_admin = False
    if user.is_authenticated:
        is_admin = (
            user.is_superuser
            or user.groups.filter(name="Administrador").exists()
        )

    # Obtener URL de Grafana desde runtime_config
    try:
        from core.runtime_config import get_grafana_url
        grafana_url = get_grafana_url()
    except Exception:
        grafana_url = getattr(settings, "GRAFANA_URL", "")

    # Validar disponibilidad (cacheado)
    grafana_available = _is_grafana_available(grafana_url)

    return {
        "grafana_url": grafana_url,
        "grafana_available": grafana_available,
        "is_superadmin": is_superadmin,
        "is_admin": is_admin,
    }