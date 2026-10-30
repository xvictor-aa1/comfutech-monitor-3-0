# alertas/models.py
"""
Modelos de la app `alertas`.

Incluye:
  - AlertRule: regla configurable con 1-5 grupos de 1-5 condicionales
    lógicos cada uno, combinables con AND / OR / XOR y negación NOT.
  - Alert: alerta generada por una regla.
  - Threshold: umbral legacy (mantenido por compatibilidad).
"""
from django.contrib.auth.models import User
from django.db import models


class AlertRule(models.Model):
    """
    Regla de alerta configurable.

    Una regla combina 1-5 **grupos**. Cada grupo contiene 1-5
    **condicionales** lógicos combinables con un operador interno
    (AND / OR / XOR). Los grupos se combinan entre sí con un operador
    externo (AND / OR / XOR). Tanto los grupos como los condicionales
    pueden negarse individualmente con NOT.

    Los condicionales se guardan como un dict v2 en `conditionals`:

        {
          "version": 2,
          "groups": [
            {
              "logic": null,           # el primer grupo no tiene lógica
              "negate": false,         # NOT aplicado al grupo entero
              "operator": "AND",       # operador entre condicionales del grupo
              "conditionals": [
                {
                  "device_id": 1,
                  "metric": "cpu_pct",
                  "operator": "gte",
                  "threshold": 75.0,
                  "duration_sec": 60,
                  "negate": false
                },
                {
                  "device_id": 1,
                  "metric": "mem_pct",
                  "operator": "gte",
                  "threshold": 85.0,
                  "duration_sec": 60,
                  "negate": false
                }
              ]
            },
            {
              "logic": "OR",           # operador con el grupo anterior
              "negate": true,          # NOT (grupo entero)
              "operator": "XOR",       # operador entre condicionales
              "conditionals": [ ... ]
            }
          ]
        }

    Se evalúa como:
        NOT (c1 XOR c2) OR NOT NOT (c3 XOR c4) → ...
        Evaluación de izquierda a derecha entre grupos.

    Las métricas de radiofrecuencia se evalúan solo en equipos con
    modelo wireless (is_wireless_link=True).
    """

    # ============================================================
    # LÍMITES DEL SISTEMA DE CONDICIONALES v2
    # ============================================================
    MAX_GROUPS = 5
    MAX_CONDITIONALS_PER_GROUP = 5
    MAX_TOTAL_CONDITIONALS = 10

    # ============================================================
    # CHOICES
    # ============================================================
    LOGIC_CHOICES = [
        ("AND", "AND (todas)"),
        ("OR",  "OR (al menos una)"),
        ("XOR", "XOR (una u otra, no ambas)"),
    ]

    METRIC_CHOICES = [
        # --- Métricas de disponibilidad ---
        ("device_down",      "Caída del dispositivo (sin ICMP)"),
        ("latency_ms",       "Latencia ICMP (ms)"),
        ("packet_loss_pct",  "Pérdida de paquetes (%)"),
        # --- Métricas de tráfico ---
        ("utilization_pct",  "Utilización de enlace (%)"),
        # --- Métricas de chasis ---
        ("cpu_pct",          "CPU (%)"),
        ("mem_pct",          "Memoria (%)"),
        ("temp_c",           "Temperatura (°C)"),
        # --- Métricas de radiofrecuencia (wireless) ---
        ("wl_signal",        "Señal de radio (dBm)"),
        ("wl_noise_floor",   "Piso de ruido (dBm)"),
        ("wl_ccq",           "CCQ - Calidad de enlace (%)"),
        ("wl_tx_rate",       "Tasa de TX (kbps)"),
        ("wl_rx_rate",       "Tasa de RX (kbps)"),
        ("airmax_quality",   "Calidad airMAX (%)"),
        ("airmax_capacity",  "Capacidad airMAX (%)"),
    ]

    OPERATOR_CHOICES = [
        ("gt",  "Mayor que (>)"),
        ("gte", "Mayor o igual (>=)"),
        ("lt",  "Menor que (<)"),
        ("lte", "Menor o igual (<=)"),
        ("eq",  "Igual a (=)"),
    ]

    SEVERITY_CHOICES = [
        ("info",     "Información"),
        ("warning",  "Advertencia"),
        ("critical", "Crítica"),
    ]

    # ------------------------------------------------------------
    # IDENTIFICACIÓN
    # ------------------------------------------------------------
    name = models.CharField(max_length=150, verbose_name="Nombre")
    description = models.TextField(blank=True, verbose_name="Descripción")

    # ------------------------------------------------------------
    # CONDICIONALES (JSON v2)
    # ------------------------------------------------------------
    conditionals = models.JSONField(
        default=dict,
        verbose_name="Condicionales",
        help_text=(
            "Estructura v2: {'version': 2, 'groups': [...]}. "
            "Cada grupo tiene 1-5 condicionales, hasta 5 grupos, "
            "10 condicionales totales máximo."
        ),
    )

    # ------------------------------------------------------------
    # COMPORTAMIENTO
    # ------------------------------------------------------------
    severity = models.CharField(
        max_length=20, choices=SEVERITY_CHOICES, default="warning",
        verbose_name="Prioridad",
    )
    custom_message = models.TextField(
        blank=True, verbose_name="Mensaje personalizado",
        help_text=(
            "Si está vacío, se genera un mensaje automático mostrando "
            "la estructura de grupos. "
            "Placeholders: {rule_name}, {severity}, {timestamp}, "
            "{conditionals_count}, {groups_count}, {device}, {ip}, "
            "{metric}, {value}, {threshold}, {device1}..{device10}, "
            "{metric1}..{metric10}, {value1}..{value10}, etc."
        ),
    )

    # Telegram
    telegram_enabled = models.BooleanField(
        default=True, verbose_name="Notificar por Telegram",
    )
    telegram_cooldown_sec = models.PositiveIntegerField(
        default=600, verbose_name="Cooldown Telegram (s)",
    )

    # Modos de disparo
    fire_once = models.BooleanField(
        default=False, verbose_name="Disparar solo una vez",
    )
    skip_on_startup = models.BooleanField(
        default=False, verbose_name="Omitir al iniciar el monitor",
    )

    # Estado
    enabled = models.BooleanField(default=True, verbose_name="Activa")

    # ------------------------------------------------------------
    # AUDITORÍA
    # ------------------------------------------------------------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="alert_rules_created",
    )

    class Meta:
        db_table = "alert_rules"
        ordering = ["-updated_at"]
        verbose_name = "Regla de alerta"
        verbose_name_plural = "Reglas de alerta"

    def __str__(self):
        return f"{self.name} ({self.groups_count} grupo(s), {self.conditionals_count} cond.)"

    # ============================================================
    # GRUPOS (v2)
    # ============================================================
    def get_groups(self) -> list:
        """
        Devuelve los grupos de la regla.

        Returns:
            list: [{logic, negate, operator, conditionals: [...]}, ...]
                  Lista vacía si el campo no tiene el formato v2.
        """
        cond = self.conditionals
        if isinstance(cond, dict) and "groups" in cond:
            return cond.get("groups", [])
        return []

    @property
    def conditionals_count(self) -> int:
        """Total de condicionales en todos los grupos."""
        return sum(len(g.get("conditionals", [])) for g in self.get_groups())

    @property
    def groups_count(self) -> int:
        """Número de grupos."""
        return len(self.get_groups())

    @property
    def device_ids(self) -> list:
        """IDs únicos de equipos involucrados en cualquier condicional."""
        ids = []
        for g in self.get_groups():
            for c in g.get("conditionals", []):
                did = c.get("device_id")
                if did and did not in ids:
                    ids.append(did)
        return ids

    @property
    def primary_device_id(self):
        """ID del primer equipo (primer condicional del primer grupo)."""
        groups = self.get_groups()
        if not groups or not groups[0].get("conditionals"):
            return None
        return groups[0]["conditionals"][0].get("device_id")

    @property
    def primary_device(self):
        """Instancia del primer equipo."""
        from inventario.models import Device
        did = self.primary_device_id
        if not did:
            return None
        return Device.objects.filter(pk=did).first()

    @property
    def active_alerts_count(self) -> int:
        """Alertas activas generadas por esta regla."""
        return self.alerts.filter(status="activa").count()

    @property
    def last_fired_at(self):
        """Fecha de la última alerta disparada."""
        last = self.alerts.order_by("-created_at").first()
        return last.created_at if last else None

    @property
    def total_fired_count(self) -> int:
        """Total histórico de alertas disparadas por esta regla."""
        return self.alerts.count()

    # ============================================================
    # HELPERS DE FORMULARIO
    # ============================================================
    @staticmethod
    def get_valid_operators(metric: str) -> list:
        """
        Devuelve los operadores válidos para una métrica.
        El primero es el default.
        """
        valid_map = {
            "device_down":      ["eq"],
            "latency_ms":       ["gte", "gt"],
            "packet_loss_pct":  ["gte", "gt"],
            "utilization_pct":  ["gte", "gt"],
            "cpu_pct":          ["gte", "gt"],
            "mem_pct":          ["gte", "gt"],
            "temp_c":           ["gte", "gt"],
            # RF: señal y CCQ alertan con <, ruido y tasas con >
            "wl_signal":        ["lte", "lt"],
            "wl_noise_floor":   ["gte", "gt"],
            "wl_ccq":           ["lte", "lt"],
            "wl_tx_rate":       ["lte", "lt"],
            "wl_rx_rate":       ["lte", "lt"],
            "airmax_quality":   ["lte", "lt"],
            "airmax_capacity":  ["lte", "lt"],
        }
        ops = valid_map.get(metric, ["gte", "gt", "lt", "lte", "eq"])
        labels = dict(AlertRule.OPERATOR_CHOICES)
        return [(op, labels[op]) for op in ops if op in labels]

    def get_conditionals_with_devices(self) -> list:
        """
        Devuelve los grupos con conditionals enriquecidos para templates.

        Returns:
            list: [{index, logic, negate, operators, conditionals: [...]}, ...]
                  `operators` es la lista de N-1 operadores entre
                  condicionales consecutivos del grupo.
                  Cada condicional incluye device, labels legibles y
                  `global_index` (posición global entre todos los grupos).
        """
        from inventario.models import Device

        groups = self.get_groups()

        all_dev_ids = set()
        for g in groups:
            for c in g.get("conditionals", []):
                did = c.get("device_id")
                if did:
                    all_dev_ids.add(did)

        devices_map = {
            d.id: d for d in Device.objects.filter(id__in=all_dev_ids)
        }

        metric_labels = dict(self.METRIC_CHOICES)
        operator_labels = dict(self.OPERATOR_CHOICES)
        logic_labels = dict(self.LOGIC_CHOICES)

        result = []
        global_idx = 0
        for gi, g in enumerate(groups):
            enriched_conds = []
            for ci, c in enumerate(g.get("conditionals", [])):
                global_idx += 1
                did = c.get("device_id")
                metric = c.get("metric", "")
                operator = c.get("operator", "")
                enriched_conds.append({
                    "global_index": global_idx,
                    "group_index": gi + 1,
                    "cond_index": ci + 1,
                    "device": devices_map.get(did),
                    "metric": metric,
                    "metric_display": metric_labels.get(metric, metric),
                    "operator": operator,
                    "operator_display": operator_labels.get(operator, operator),
                    "threshold": c.get("threshold"),
                    "duration_sec": c.get("duration_sec"),
                    "negate": bool(c.get("negate", False)),
                })

            # Lista de operadores entre condicionales del grupo
            operators = g.get("operators") or []
            if not isinstance(operators, list):
                operators = []

            result.append({
                "index": gi + 1,
                "logic": g.get("logic"),
                "logic_display": logic_labels.get(g.get("logic"), "") if g.get("logic") else "",
                "negate": bool(g.get("negate", False)),
                "operators": operators,
                "conditionals": enriched_conds,
            })
        return result


class Alert(models.Model):
    """Alerta generada por una regla."""

    SEVERITY_CHOICES = [
        ("info", "Info"),
        ("warning", "Advertencia"),
        ("critical", "Crítica"),
    ]
    STATUS_CHOICES = [
        ("activa", "Activa"),
        ("reconocida", "Reconocida"),
        ("resuelta", "Resuelta"),
    ]

    device = models.ForeignKey(
        "inventario.Device", on_delete=models.SET_NULL,
        null=True, blank=True, db_column="device_id",
        related_name="alerts",
    )
    interface = models.ForeignKey(
        "inventario.Interface", on_delete=models.SET_NULL,
        null=True, blank=True, db_column="interface_id",
        related_name="alerts",
    )
    rule = models.ForeignKey(
        AlertRule, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="alerts",
    )
    alert_type = models.CharField(max_length=50)
    severity = models.CharField(
        max_length=20, choices=SEVERITY_CHOICES, default="warning",
    )
    message = models.TextField()
    value_observed = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True,
    )
    threshold_value = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True,
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="activa",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "alerts"
        ordering = ["-created_at"]
        verbose_name = "Alerta"
        verbose_name_plural = "Alertas"

    def __str__(self):
        return f"[{self.severity}] {self.alert_type} - {self.device or 'N/A'}"