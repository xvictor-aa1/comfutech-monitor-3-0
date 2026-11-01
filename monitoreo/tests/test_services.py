# monitoreo/tests/test_services.py
from django.test import TestCase
from unittest.mock import patch, MagicMock
from monitoreo.services import traffic, health, icmp_tcp
from inventario.models import Device, DeviceModel
from django.utils import timezone

class TrafficPollerTests(TestCase):
    """Pruebas para el poller de tráfico SNMP."""
    
    @classmethod
    def setUpTestData(cls):
        cls.model = DeviceModel.objects.create(vendor="MikroTik", name="RB4011")
        cls.device = Device.objects.create(
            name="RB-Traffic", ip="10.0.0.2", vendor="MikroTik",
            device_model=cls.model, device_role="core"
        )

    @patch('monitoreo.services.traffic.snmp_get_multiple')
    @patch('monitoreo.services.traffic.influx_writer.write_traffic')
    @patch('monitoreo.services.traffic.alerts.evaluate_metrics')
    def test_poll_traffic_calculates_bps_correctly(self, mock_alerts, mock_influx, mock_snmp):
        """Verifica que el cálculo de bps a partir de los contadores SNMP es correcto."""
        # 1. Simular la primera lectura de contadores (ej. en t=0)
        mock_snmp.return_value = [1000000000, 2000000000] # 1GB in, 2GB out
        traffic.poll_traffic()
        
        # 2. Simular una segunda lectura 60 segundos después con más bytes
        mock_snmp.return_value = [1120000000, 2300000000] # +120MB in, +300MB out
        with patch('monitoreo.services.traffic._utcnow') as mock_now:
            mock_now.return_value = timezone.now() + timezone.timedelta(seconds=60)
            traffic.poll_traffic()

        # 3. Verificar que write_traffic fue llamado con los bps correctos
        # El delta de bytes se multiplica por 8 y se divide entre 60 segundos.
        # In: (1120000000 - 1000000000) * 8 / 60 = 16000000 bps (16 Mbps)
        # Out: (2300000000 - 2000000000) * 8 / 60 = 40000000 bps (40 Mbps)
        mock_influx.assert_any_call(
            device_name='RB-Traffic', ip='10.0.0.2', if_index=1,
            if_name=None, role='core', capacity_bps=None,
            in_bps=16000000.0, out_bps=40000000.0,
            utilization=None, rx_octets=1120000000, tx_octets=2300000000,
            timestamp=mock_now.return_value
        )
        # 4. Verificar que se evaluaron las alertas con la utilización (en este caso, None)
        mock_alerts.assert_called()

class HealthPollerTests(TestCase):
    """Pruebas para el poller de Core Health."""
    
    @classmethod
    def setUpTestData(cls):
        # Creamos un modelo con OIDs personalizados
        cls.model = DeviceModel.objects.create(
            vendor="MikroTik", name="RB-Health",
            oids={"cpu_pct": "1.3.6.1.4.1.14988.1.1.3.10.0"} # OID de CPU
        )
        cls.device = Device.objects.create(
            name="RB-Health", ip="10.0.0.3", vendor="MikroTik",
            device_model=cls.model, device_role="core"
        )

    @patch('monitoreo.services.health.snmp_get_multiple')
    @patch('monitoreo.services.health.influx_writer.write_health')
    def test_poll_health_writes_correct_metrics(self, mock_influx, mock_snmp):
        """El poller de health debe leer los OIDs correctos y escribir las métricas."""
        # Simular la respuesta del equipo para los OIDs solicitados
        mock_snmp.return_value = [25.5] # 25.5% de CPU
        
        health.poll_health()
        
        # Verificar que write_health fue llamado con los datos correctos
        mock_influx.assert_called_once()
        args, kwargs = mock_influx.call_args
        self.assertEqual(kwargs['device_name'], 'RB-Health')
        self.assertAlmostEqual(kwargs['metrics']['cpu_pct'], 25.5)

class IcmpTcpPollerTests(TestCase):
    """Pruebas para el poller de ICMP/TCP."""
    
    @classmethod
    def setUpTestData(cls):
        cls.device = Device.objects.create(
            name="CPE-Test", ip="10.0.0.4", device_role="cpe",
            tcp_ports="22,80"
        )
    
    @patch('monitoreo.services.icmp_tcp._icmp_probe')
    @patch('monitoreo.services.icmp_tcp._tcp_check')
    @patch('monitoreo.services.icmp_tcp.influx_writer.write_icmp')
    @patch('monitoreo.services.icmp_tcp.influx_writer.write_tcp')
    def test_poll_icmp_tcp_successful(self, mock_write_tcp, mock_write_icmp, mock_tcp, mock_icmp):
        """Prueba el flujo completo de un sondeo ICMP/TCP exitoso."""
        # Simular que el ping responde con 15ms de latencia y 0% de pérdida
        mock_icmp.return_value = (True, 15.0, 0.0)
        # Simular que ambos puertos TCP están abiertos
        mock_tcp.side_effect = [True, True]
        
        icmp_tcp.poll_icmp_tcp()
        
        # Verificar que se escribió la métrica ICMP
        mock_write_icmp.assert_called_once()
        args_icmp, kwargs_icmp = mock_write_icmp.call_args
        self.assertTrue(kwargs_icmp['alive'])
        self.assertAlmostEqual(kwargs_icmp['avg_rtt'], 15.0)
        
        # Verificar que se escribieron las métricas TCP para ambos puertos
        self.assertEqual(mock_write_tcp.call_count, 2)
        # Se puede inspeccionar las llamadas para verificar los puertos
        call_args_list = mock_write_tcp.call_args_list
        self.assertEqual(call_args_list[0].kwargs['port'], 22)
<<<<<<< HEAD
        self.assertTrue(call_args_list[0].kwargs['is_open'])
=======
        self.assertTrue(call_args_list[0].kwargs['is_open'])
>>>>>>> 52c40f36b6cbf199303952082a1ffe47c0512189
