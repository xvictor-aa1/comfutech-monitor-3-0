# monitoreo/tests.py
from django.test import TestCase
from core.runtime_config import get_monitor_config
from monitoreo.models import PollerConfig


class PollerConfigTests(TestCase):
	def test_monitor_config_reads_intervals_from_database(self):
		PollerConfig.objects.update_or_create(
			pk=1,
			defaults={
				"snmp_poll_interval": 31,
				"health_poll_interval": 62,
				"icmp_poll_interval": 33,
				"radio_poll_interval": 64,
				"ap_clients_poll_interval": 65,
			},
		)

		config = get_monitor_config()

		self.assertEqual(config["snmp_poll_interval"], 31)
		self.assertEqual(config["health_poll_interval"], 62)
		self.assertEqual(config["icmp_poll_interval"], 33)
		self.assertEqual(config["radio_poll_interval"], 64)
		self.assertEqual(config["ap_clients_poll_interval"], 65)
