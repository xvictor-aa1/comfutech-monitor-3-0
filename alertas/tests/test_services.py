# alertas/tests/test_services.py
from django.test import TestCase
from unittest.mock import patch, MagicMock
from alertas.models import AlertRule, Alert
from monitoreo.services import alerts as alerts_service
from inventario.models import Device

class AlertEngineTests(TestCase):
    """Pruebas para la lógica de evaluación del motor de alertas."""

    @classmethod
    def setUpTestData(cls):
        """Crea datos de prueba una sola vez para toda la clase."""
        cls.device = Device.objects.create(name="Router-Test", ip="10.0.0.1")
        # Regla: CPU > 80 Y Memoria > 90 durante 1 segundo (para el test)
        cls.rule = AlertRule.objects.create(
            name="Test CPU & Mem",
            conditionals={
                "version": 2,
                "groups": [{
                    "logic": None, "negate": False, "operators": ["AND"],
                    "conditionals": [
                        {"device_id": cls.device.id, "metric": "cpu_pct", "operator": "gte", "threshold": 80, "duration_sec": 1, "negate": False},
                        {"device_id": cls.device.id, "metric": "mem_pct", "operator": "gte", "threshold": 90, "duration_sec": 1, "negate": False}
                    ]
                }]
            },
            severity="critical",
            telegram_enabled=True,
        )
        # Aseguramos que el estado del monitor está "caliente"
        alerts_service.reset_startup_time()
        import time; time.sleep(1.1) # Esperar a que pase el warm-up

    def test_rule_fires_when_conditions_are_met(self):
        """La regla debe disparar una alerta cuando ambas condiciones se cumplen."""
        # Al no haber alertas activas, el motor debería crear una.
        metrics = {"cpu_pct": 85.0, "mem_pct": 95.0}
        
        # Simulamos el envío de Telegram para no hacer una llamada real.
        with patch.object(alerts_service.telegram, 'send_alert') as mock_send:
            alerts_service.evaluate_metrics(self.device, metrics)
            mock_send.assert_called_once() # Verifica que se intentó notificar

        # Verifica que se creó la alerta en la base de datos
        self.assertEqual(Alert.objects.filter(status="activa").count(), 1)
        alert = Alert.objects.first()
        self.assertIn("CPU", alert.message)

    def test_rule_does_not_fire_if_condition_is_not_met(self):
        """La regla no debe disparar si una condición no se cumple."""
        metrics = {"cpu_pct": 85.0, "mem_pct": 85.0} # Memoria no supera el umbral
        alerts_service.evaluate_metrics(self.device, metrics)
        self.assertEqual(Alert.objects.count(), 0)

    def test_active_alert_is_auto_resolved(self):
        """Una alerta activa debe resolverse cuando la condición deja de cumplirse."""
        # Primero, forzamos el disparo de la alerta
        metrics_fire = {"cpu_pct": 90.0, "mem_pct": 95.0}
        with patch.object(alerts_service.telegram, 'send_alert'):
            alerts_service.evaluate_metrics(self.device, metrics_fire)
        self.assertEqual(Alert.objects.filter(status="activa").count(), 1)
        
        # Ahora, enviamos métricas que NO cumplen la condición
        metrics_ok = {"cpu_pct": 10.0, "mem_pct": 20.0}
        alerts_service.evaluate_metrics(self.device, metrics_ok)
        
        # La alerta debe haberse resuelto automáticamente
        self.assertEqual(Alert.objects.filter(status="activa").count(), 0)
        self.assertEqual(Alert.objects.filter(status="resuelta").count(), 1)
