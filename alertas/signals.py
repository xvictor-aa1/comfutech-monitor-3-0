# alertas/signals.py
"""
Signals de la app `alertas`.

Invalida el índice en memoria del motor de alertas cuando se crea,
actualiza o elimina una AlertRule.
"""
import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import AlertRule

log = logging.getLogger(__name__)


@receiver(post_save, sender=AlertRule)
@receiver(post_delete, sender=AlertRule)
def _invalidate_alerts_cache(sender, **kwargs):
    """Invalida el índice de reglas del motor de alertas."""
    try:
        from monitoreo.services.alerts import invalidate_rules_cache
        invalidate_rules_cache()
        log.debug("Índice de reglas invalidado (signal).")
    except Exception as e:
        log.warning("No se pudo invalidar el índice de reglas: %s", e)