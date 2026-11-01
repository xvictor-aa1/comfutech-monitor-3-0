# alertas/models.py
"""
Modelos de la app `alertas`.

Incluye:
  - AlertRule: regla configurable con 1-5 grupos de 1-5 condicionales
    lógicos cada uno, combinables con AND / OR / XOR y negación NOT.
    A partir de la v4, incorpora un **segundo bloque opcional** de
    condicionales (`auto_resolve_conditionals`) que define cuándo se
    resuelven automáticamente las alertas emitidas por la regla, más
    dos flags: `enable_auto_resolve` (habilita el nuevo bloque) y
    `mark_as_resolved` (crea alertas ya resueltas, útil para Info).

  - Alert: alerta generada por una regla.

IMPORTANTE (refactor v4):
  El modelo `Alert` **NO tiene ForeignKeys** hacia `Device`, `Interface`
  ni `AlertRule`. Es una decisión arquitectónica intencional:

    · Las alertas son registros históricos y auditables. No deben verse
      afectados por la eliminación de equipos, interfaces o reglas.
    · El `rule_id` se guarda como `IntegerField` plano (`db_index=True`)
      para que el motor de auto-resolución pueda seguir agrupando
      alertas por regla.
    · `rule_name` se guarda como **snapshot** para preservar el nombre
      de la regla incluso si ésta se elimina posteriormente.
    · NO se guardan snapshots de `device_name`, `device_ip` ni
      `interface_name` (serían inconsistentes y redundantes: los
      placeholders de `custom_message` ya incluyen la info de devices
      en el mensaje).

  Como consecuencia:
    · `device.alerts` / `interface.alerts` / `rule.alerts` dejan de
      existir como reverse relations.
    · Las consultas por alerta se hacen por `rule_id` (no por FK).
    · El `device_detail.html` muestra las **reglas vinculadas** al
      equipo (no sus alertas), porque las alertas ya no pertenecen al
      device.
"""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class AlertRule(models.Model):
    """
    Regla de alerta configurable.

    Una regla combina 1-5 **grupos** de disparo. Cada grupo contiene
    1-5 **condicionales** lógicos combinables con un operador interno
    (AND / OR / XOR). Los grupos se combinan entre sí con un operador
    externo (AND / OR / XOR). Tanto los grupos como los condicionales
    pueden negarse individualmente con NOT.

    A partir de la v4, la regla también puede tener un **bloque
    opcional de auto-resolución** (`auto_resolve_conditionals`), con
    la misma estructura de grupos, que define las condiciones bajo
    las cuales las alertas emitidas por la regla se resuelven
    automáticamente. Este bloque es opcional: si está vacío o si
    `enable_auto_resolve=False`, el sistema aplica el comportamiento
    clásico (resolver cuando las condiciones de disparo dejen de
    cumplirse).

    Los condicionales de disparo se guardan como un dict v2 en
    `conditionals`:

        {
          "version": 2,
          "groups": [
            {
              "logic": null,           # el primer grupo no tiene lógica
              "negate": false,         # NOT aplicado al grupo entero
              "operators": ["AND"],    # operadores entre condicionales
              "conditionals": [
                {
                  "device_id": 1,
                  "metric": "cpu_pct",
                  "operator": "gte",
                  "threshold": 75.0,
                  "duration_sec": 60,
                  "negate": false
                },
                ...
              ]
            },
            ...
          ]
        }

    Los condicionales de auto-resolución (`auto_resolve_conditionals`)
    usan exactamente la misma estructura v2, pero se evalúan por
    separado, con su propio estado en `_cond_states`.

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
        ("in_bps",           "Tráfico entrante (bps)"),
        ("out_bps",          "Tráfico saliente (bps)"),
        # --- Métricas de chasis ---
        ("cpu_pct",          "CPU (%)"),
        ("mem_pct",          "Memoria (%)"),
        ("temp_c",           "Temperatura (°C)"),
        ("uptime",           "Uptime (segundos)"),
        # --- Métricas de radiofrecuencia (wireless) ---
        ("wl_signal",        "Señal de radio (dBm)"),
        ("wl_noise_floor",   "Piso de ruido (dBm)"),
        ("wl_ccq",           "CCQ - Calidad de enlace (%)"),
        ("wl_tx_rate",       "Tasa de TX (kbps)"),
        ("wl_rx_rate",       "Tasa de RX (kbps)"),
        ("airmax_quality",   "Calidad airMAX (%)"),
        ("airmax_capacity",  "Capacidad airMAX (%)"),
        ("radio_freq",       "Frecuencia de radio (MHz)"),
        ("radio_txpower",    "Potencia TX (dBm)"),
        ("chan_width",       "Ancho de canal (MHz)"),
        # --- Métricas de clientes AP ---
        ("ap_client_count",  "Clientes AP conectados"),
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
    # CONDICIONALES DE DISPARO (JSON v2) — OBLIGATORIOS
    # ------------------------------------------------------------
    conditionals = models.JSONField(
        default=dict,
        verbose_name="Condicionales para disparar la Alerta",
        help_text=(
            "Estructura v2: {'version': 2, 'groups': [...]}. "
            "Cada grupo tiene 1-5 condicionales, hasta 5 grupos, "
            "10 condicionales totales máximo. "
            "Son OBLIGATORIOS: sin ellos la regla no puede disparar "
            "alertas."
        ),
    )

    # ------------------------------------------------------------
    # CONDICIONALES DE AUTO-RESOLUCIÓN (JSON v2) — OPCIONALES
    # ------------------------------------------------------------
    auto_resolve_conditionals = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Condicionales para resolver la Alerta",
        help_text=(
            "Estructura v2 idéntica a 'conditionals'. Si está vacío "
            "o 'enable_auto_resolve' está desactivado, el sistema "
            "aplica el comportamiento clásico: resuelve las alertas "
            "cuando las condiciones de disparo dejen de cumplirse."
        ),
    )
    enable_auto_resolve = models.BooleanField(
        default=False,
        verbose_name="Habilitar auto-resolución por condicionales",
        help_text=(
            "Si está activo Y existen condicionales de auto-resolución, "
            "se evaluarán para resolver las alertas de esta regla. "
            "Si está desactivado o el bloque JSON está vacío, se usa "
            "el comportamiento clásico."
        ),
    )

    # ------------------------------------------------------------
    # COMPORTAMIENTO AL DISPARAR
    # ------------------------------------------------------------
    mark_as_resolved = models.BooleanField(
        default=False,
        verbose_name="Crear alertas ya resueltas",
        help_text=(
            "Útil para reglas puramente informativas. Las alertas se "
            "crean con estado 'resuelta' en lugar de 'activa', y se "
            "deduplican como 'fire_once' para no generar una alerta "
            "por cada ciclo."
        ),
    )

    # ------------------------------------------------------------
    # SEVERIDAD Y MENSAJE
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

    # ------------------------------------------------------------
    # TELEGRAM
    # ------------------------------------------------------------
    telegram_enabled = models.BooleanField(
        default=True, verbose_name="Notificar por Telegram",
    )
    telegram_cooldown_sec = models.PositiveIntegerField(
        default=600, verbose_name="Cooldown Telegram (s)",
    )

    # ------------------------------------------------------------
    # MODOS DE DISPARO
    # ------------------------------------------------------------
    fire_once = models.BooleanField(
        default=False, verbose_name="Disparar solo una vez",
    )
    skip_on_startup = models.BooleanField(
        default=False, verbose_name="Omitir al iniciar el monitor",
    )

    # ------------------------------------------------------------
    # ESTADO
    # ------------------------------------------------------------
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
    # GRUPOS DE DISPARO (v2)
    # ============================================================
    def get_groups(self) -> list:
        """
        Devuelve los grupos de condicionales de DISPARO.

        Returns:
            list: [{logic, negate, operators, conditionals: [...]}, ...]
                  Lista vacía si el campo no tiene el formato v2.
        """
        cond = self.conditionals
        if isinstance(cond, dict) and "groups" in cond:
            return cond.get("groups", [])
        return []

    # ============================================================
    # GRUPOS DE AUTO-RESOLUCIÓN (v2)
    # ============================================================
    def get_auto_resolve_groups(self) -> list:
        """
        Devuelve los grupos de condicionales de AUTO-RESOLUCIÓN.

        Returns:
            list: [{logic, negate, operators, conditionals: [...]}, ...]
                  Lista vacía si el bloque está vacío o no es v2.
        """
        cond = self.auto_resolve_conditionals
        if isinstance(cond, dict) and "groups" in cond:
            return cond.get("groups", [])
        return []

    @property
    def conditionals_count(self) -> int:
        """Total de condicionales de DISPARO en todos los grupos."""
        return sum(len(g.get("conditionals", [])) for g in self.get_groups())

    @property
    def auto_resolve_conditionals_count(self) -> int:
        """Total de condicionales de AUTO-RESOLUCIÓN."""
        return sum(len(g.get("conditionals", [])) for g in self.get_auto_resolve_groups())

    @property
    def groups_count(self) -> int:
        """Número de grupos de DISPARO."""
        return len(self.get_groups())

    @property
    def auto_resolve_groups_count(self) -> int:
        """Número de grupos de AUTO-RESOLUCIÓN."""
        return len(self.get_auto_resolve_groups())

    @property
    def has_auto_resolve(self) -> bool:
        """
        True si la auto-resolución por condicionales está efectivamente
        habilitada: `enable_auto_resolve=True` Y existe al menos un
        condicional en `auto_resolve_conditionals`.
        """
        return bool(
            self.enable_auto_resolve
            and self.auto_resolve_conditionals_count > 0
        )

    @property
    def device_ids(self) -> list:
        """
        IDs únicos de equipos involucrados en cualquier condicional de
        DISPARO (no incluye auto-resolución). Se usa para búsquedas
        inversas desde `Device`.
        """
        ids = []
        for g in self.get_groups():
            for c in g.get("conditionals", []):
                did = c.get("device_id")
                if did and did not in ids:
                    ids.append(did)
        return ids

    @property
    def all_device_ids(self) -> list:
        """
        IDs únicos de equipos en cualquier condicional (DISPARO +
        AUTO-RESOLUCIÓN). Útil para `device_detail.html` (reglas
        vinculadas).
        """
        ids = list(self.device_ids)
        for g in self.get_auto_resolve_groups():
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
        """Instancia del primer equipo (de disparo)."""
        from inventario.models import Device
        did = self.primary_device_id
        if not did:
            return None
        return Device.objects.filter(pk=did).first()

    # ============================================================
    # CONTADORES DE ALERTAS (por rule_id, sin FK)
    # ============================================================
    @property
    def active_alerts_count(self) -> int:
        """
        Alertas activas generadas por esta regla.

        A partir de v4, no existe FK `alerts`; se consulta por `rule_id`.
        """
        return Alert.objects.filter(
            rule_id=self.id, status="activa",
        ).count()

    @property
    def last_fired_at(self):
        """Fecha de la última alerta disparada por esta regla."""
        last = Alert.objects.filter(rule_id=self.id).order_by("-created_at").first()
        return last.created_at if last else None

    @property
    def total_fired_count(self) -> int:
        """Total histórico de alertas disparadas por esta regla."""
        return Alert.objects.filter(rule_id=self.id).count()

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
            "in_bps":           ["gte", "gt"],
            "out_bps":          ["gte", "gt"],
            "cpu_pct":          ["gte", "gt"],
            "mem_pct":          ["gte", "gt"],
            "temp_c":           ["gte", "gt"],
            "uptime":           ["lte", "lt", "gte", "gt"],
            # RF: señal y CCQ alertan con <, ruido y tasas con >.
            "wl_signal":        ["lte", "lt"],
            "wl_noise_floor":   ["gte", "gt"],
            "wl_ccq":           ["lte", "lt"],
            "wl_tx_rate":       ["lte", "lt"],
            "wl_rx_rate":       ["lte", "lt"],
            "airmax_quality":   ["lte", "lt"],
            "airmax_capacity":  ["lte", "lt"],
            "radio_freq":       ["eq"],
            "radio_txpower":    ["gte", "gt", "lte", "lt"],
            "chan_width":       ["eq"],
            "ap_client_count":  ["lte", "lt", "eq"],
        }
        ops = valid_map.get(metric, ["gte", "gt", "lt", "lte", "eq"])
        labels = dict(AlertRule.OPERATOR_CHOICES)
        return [(op, labels[op]) for op in ops if op in labels]

    def _enrich_groups(self, groups: list) -> list:
        """
        Enriquecer grupos de condicionales con instancias de `Device`,
        etiquetas legibles y `global_index`.

        Helper interno compartido por `get_conditionals_with_devices()`
        y `get_auto_resolve_conditionals_with_devices()`.
        """
        from inventario.models import Device

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

    def get_conditionals_with_devices(self) -> list:
        """
        Devuelve los grupos de DISPARO enriquecidos para templates.
        Estructura: [{index, logic, negate, operators, conditionals: [...]}, ...]
        """
        return self._enrich_groups(self.get_groups())

    def get_auto_resolve_conditionals_with_devices(self) -> list:
        """
        Devuelve los grupos de AUTO-RESOLUCIÓN enriquecidos para templates.
        Estructura idéntica a `get_conditionals_with_devices()`.
        """
        return self._enrich_groups(self.get_auto_resolve_groups())


class Alert(models.Model):
    """
    Alerta generada por una regla.

    IMPORTANTE (refactor v4):
      Este modelo NO tiene ForeignKeys. Es intencional:
        · Las alertas son registros históricos/auditables y no deben
          verse afectados por el borrado de equipos, interfaces o reglas.
        · Se guarda `rule_id` (IntegerField plano, db_index) para que
          el motor de auto-resolución pueda agrupar alertas por regla.
        · Se guarda `rule_name` como snapshot para preservar el nombre
          incluso si la regla se elimina.
        · NO se guardan snapshots de device/interface (son redundantes:
          el mensaje ya incluye la info de devices vía placeholders).
    """

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

    # ------------------------------------------------------------
    # IDENTIFICACIÓN DE LA REGLA (SIN FK)
    # ------------------------------------------------------------
    rule_id = models.IntegerField(
        null=True, blank=True, db_index=True,
        verbose_name="ID de la regla (snapshot)",
        help_text=(
            "ID de la AlertRule que disparó esta alerta. NO es FK: se "
            "guarda como entero plano para desacoplar el histórico."
        ),
    )
    rule_name = models.CharField(
        max_length=150, blank=True,
        verbose_name="Nombre de la regla (snapshot)",
        help_text="Nombre de la regla al momento del disparo.",
    )

    # ------------------------------------------------------------
    # DATOS DEL DISPARO
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # ESTADO
    # ------------------------------------------------------------
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
        constraints = [
            models.UniqueConstraint(
                fields=["rule_id"],
                condition=models.Q(status="activa"),
                name="unique_active_alert_per_rule",
            ),
        ]

    def __str__(self):
        return f"[{self.severity}] {self.alert_type} - {self.rule_name or 'N/A'}"