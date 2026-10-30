# inventario/models.py
"""
Modelos de la app `inventario`.

Incluye:
  - DeviceModel: modelo de equipo con OIDs de chasis y de radiofrecuencia.
  - Device:      equipo de red monitoreado.
  - Interface:   interfaz de red de un equipo.
"""
from django.db import models


# ============================================================
# MODELO DE EQUIPO (Fabricante + Modelo + OIDs)
# ============================================================
class DeviceModel(models.Model):
    """
    Modelo específico de un fabricante, con sus OIDs SNMP propios.

    Se usa para que al seleccionar un modelo en un Device, se carguen
    automáticamente las OIDs correctas para el polling de chasis
    (CPU, memoria, temperatura, uptime) y de radiofrecuencia
    (frecuencia, señal, CCQ, tasas, airMAX).

    Los OIDs de chasis y de RF se guardan en dos JSONField separados
    para mantener la claridad y evitar mezclar contextos.
    """
    VENDOR_CHOICES = [
        ("MikroTik",  "MikroTik"),
        ("Ubiquiti",  "Ubiquiti"),
        ("Cambium",   "Cambium Networks"),
        ("Huawei",    "Huawei"),
        ("TP-Link",   "TP-Link"),
        ("Cisco",     "Cisco"),
        ("Mimosa",    "Mimosa Networks"),
        ("Engenius",  "EnGenius"),
        ("Otro",      "Otro"),
    ]

    vendor = models.CharField(
        max_length=50,
        choices=VENDOR_CHOICES,
        verbose_name="Fabricante",
    )
    name = models.CharField(
        max_length=100,
        verbose_name="Modelo",
        help_text="Ej: RB4011iGS+, AirMax LiteBeam M5, ePMP 1000",
    )
    oids = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="OIDs de chasis",
        help_text=(
            "Diccionario de OIDs propios de este modelo. "
            "Claves válidas: cpu_pct, mem_pct, mem_used, mem_size, "
            "mem_free, temp_c, uptime. "
            "Si está vacío, se usarán las OIDs por defecto del fabricante."
        ),
    )
    radio_oids = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="OIDs de radiofrecuencia",
        help_text=(
            "Diccionario de OIDs propios de radiofrecuencia para este modelo. "
            "Claves válidas: radio_freq, radio_txpower, wl_signal, "
            "wl_noise_floor, wl_ccq, wl_tx_rate, wl_rx_rate, "
            "airmax_quality, airmax_capacity, chan_width. "
            "Solo se usa si el modelo está marcado como radio-enlace."
        ),
    )
    has_interfaces = models.BooleanField(
        default=True,
        verbose_name="Tiene interfaces SNMP",
        help_text=(
            "Marcar si el modelo expone la tabla IF-MIB "
            "(interfaces tradicionales: eth0, wlan0, etc.). "
            "Desmarcar para CPEs o equipos sin interfaces monitoreables. "
            "Si está desmarcado, el bloque 'SNMP Tráfico' no se muestra "
            "en el monitoreo en vivo."
        ),
    )
    description = models.TextField(
        blank=True,
        verbose_name="Descripción",
        help_text="Notas opcionales sobre el modelo (firmware, características, etc.)",
    )
    is_wireless_link = models.BooleanField(
        default=False,
        verbose_name="Es radio-enlace",
        help_text=(
            "Marcar si este modelo es un equipo de radio-enlace "
            "(AirMax, Cambium, Mimosa, etc.). Los equipos con este "
            "flag habilitan el monitoreo de Utilización de Enlace y "
            "de parámetros de radiofrecuencia."
        ),
    )
    active = models.BooleanField(
        default=True,
        verbose_name="Activo",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "device_models"
        unique_together = [("vendor", "name")]
        ordering = ["vendor", "name"]
        verbose_name = "Modelo de equipo"
        verbose_name_plural = "Modelos de equipos"

    def __str__(self):
        """Representación legible del modelo."""
        return f"{self.vendor} - {self.name}"

    @property
    def has_radio_oids(self) -> bool:
        """Devuelve True si el modelo define OIDs de radiofrecuencia."""
        return bool(self.radio_oids)

    @property
    def has_chassis_oids(self) -> bool:
        """True si el modelo define OIDs de chasis propias."""
        return bool(self.oids)


# ============================================================
# EQUIPO
# ============================================================
class Device(models.Model):
    """Equipo de red monitoreado (router, switch, CPE, firewall)."""

    TYPE_CHOICES = [
        ("router",    "Router"),
        ("switch",    "Switch"),
        ("cpe",       "CPE"),
        ("firewall",  "Firewall"),
        ("ap",        "Access Point"),
        ("otro",      "Otro"),
    ]

    ROLE_CHOICES = [
        ("core",         "Core"),
        ("distribution", "Distribución"),
        ("access",       "Acceso"),
        ("cpe",          "CPE"),
    ]

    VENDOR_CHOICES = [
        ("MikroTik",  "MikroTik"),
        ("Ubiquiti",  "Ubiquiti"),
        ("Cambium",   "Cambium Networks"),
        ("Huawei",    "Huawei"),
        ("TP-Link",   "TP-Link"),
        ("Cisco",     "Cisco"),
        ("Mimosa",    "Mimosa Networks"),
        ("Engenius",  "EnGenius"),
        ("Otro",      "Otro"),
    ]

    # --- Identificación ---
    name = models.CharField(max_length=100, verbose_name="Nombre")
    ip = models.CharField(max_length=45, unique=True, verbose_name="Dirección IP")
    device_type = models.CharField(
        max_length=50, choices=TYPE_CHOICES,
        default="router", verbose_name="Tipo",
    )
    device_role = models.CharField(
        max_length=20, choices=ROLE_CHOICES,
        default="access", verbose_name="Rol",
    )
    vendor = models.CharField(
        max_length=50, choices=VENDOR_CHOICES,
        default="Otro", verbose_name="Fabricante",
    )
    device_model = models.ForeignKey(
        DeviceModel,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="devices",
        verbose_name="Modelo",
        help_text="Modelo específico del equipo (opcional, mejora el polling).",
    )
    location = models.CharField(
        max_length=100, default="Güigüe", verbose_name="Ubicación",
    )

    # --- SNMP ---
    snmp_version = models.CharField(
        max_length=10, default="2c", verbose_name="Versión SNMP",
    )
    snmp_community = models.CharField(
        max_length=100, default="public", verbose_name="Community",
    )
    snmp_user = models.CharField(
        max_length=100, null=True, blank=True, verbose_name="Usuario SNMPv3",
    )
    snmp_auth = models.CharField(
        max_length=255, null=True, blank=True, verbose_name="Auth Key",
    )
    snmp_priv = models.CharField(
        max_length=255, null=True, blank=True, verbose_name="Priv Key",
    )

    # --- Monitoreo ---
    tcp_ports = models.CharField(
        max_length=255, default="161", verbose_name="Puertos TCP",
        help_text="Separados por coma. Ej: 161,22,80",
    )

    # --- Control manual de monitoreo ---
    monitor_interfaces = models.BooleanField(
        default=True,
        verbose_name="Monitorear interfaces",
        help_text=(
            "Permite habilitar o deshabilitar el monitoreo de tráfico "
            "SNMP de este equipo en particular. Solo aplica si el modelo "
            "soporta interfaces (has_interfaces=True). Útil para excluir "
            "equipos específicos del polling de tráfico sin cambiar el "
            "modelo global."
        ),
    )

    monitor_health = models.BooleanField(
        default=True,
        verbose_name="Monitorear CPU / Mem / Temp",
        help_text=(
            "Permite habilitar o deshabilitar el polling de chasis "
            "(CPU, memoria, temperatura) para este equipo en particular. "
            "Solo aplica si el modelo del equipo tiene OIDs de chasis "
            "definidas (propias o del fabricante)."
        ),
    )

    dashboard_interface = models.ForeignKey(
        "Interface",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dashboard_devices",
        verbose_name="Interfaz destacada del dashboard",
        help_text=(
            "Interfaz que se muestra en la card compacta del dashboard. "
            "Si está vacía, se usa la primera interfaz con tráfico. "
            "Solo aplica a equipos que no son radioenlaces."
        ),
    )

    # --- Interfaces Internas de clientes AP ---
    ap_interfaces = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Clientes AP (JSON)",
        help_text=(
            "Lista de clientes conectados a este equipo cuando opera "
            "en modo Access Point. Se puebla automáticamente con el "
            "Discovery. Solo aplica a modelos wireless. "
            "Formato: [{if_index, mac, ip, essid, hostname, "
            "first_seen, last_seen}, ...]"
        ),
    )

    # --- Estado ---
    active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "devices"
        ordering = ["name"]
        verbose_name = "Equipo"
        verbose_name_plural = "Equipos"

    def __str__(self):
        """Representación legible del equipo."""
        return f"{self.name} ({self.ip})"

    @property
    def has_chassis_monitoring(self) -> bool:
        """Devuelve True si el rol recibe polling de chasis."""
        return self.device_role in ("core", "distribution")

    @property
    def is_wireless_link(self) -> bool:
        """Devuelve True si el equipo es un radio-enlace."""
        return bool(self.device_model and self.device_model.is_wireless_link)

    @property
    def has_interfaces_support(self) -> bool:
        """
        ¿El modelo del equipo soporta interfaces SNMP tradicionales?

        Si no hay modelo asignado, se asume True por compatibilidad.
        """
        if not self.device_model:
            return True
        return self.device_model.has_interfaces

    @property
    def monitored_interfaces_count(self) -> int:
        """Cantidad de interfaces marcadas para monitoreo."""
        return self.interfaces.filter(monitored=True).count()

    @property
    def total_interfaces_count(self) -> int:
        """Cantidad total de interfaces descubiertas."""
        return self.interfaces.count()

    @property
    def effective_oids(self) -> dict:
        """OIDs de chasis efectivas (del modelo, o vacío para fallback)."""
        if self.device_model and self.device_model.oids:
            return dict(self.device_model.oids)
        return {}

    @property
    def effective_radio_oids(self) -> dict:
        """OIDs de RF efectivas (del modelo, o vacío para fallback)."""
        if self.device_model and self.device_model.radio_oids:
            return dict(self.device_model.radio_oids)
        return {}

    @property
    def interfaces_effectively_monitored(self) -> bool:
        """
        ¿Debe el equipo mostrar el bloque de tráfico SNMP y el botón
        de gestión de interfaces?

        Se cumplen las 3 condiciones:
          1. El modelo soporta interfaces (has_interfaces=True o sin modelo).
          2. El usuario habilitó el monitoreo para este equipo específico
             (monitor_interfaces=True).
          3. Hay al menos una interfaz marcada como monitoreada.

        Nota: usa `any()` sobre `self.interfaces.all()` (no
        `.filter().exists()`) para aprovechar el `prefetch_related` del
        queryset en vistas de listado y evitar N+1 queries.
        """
        if not self.has_interfaces_support:
            return False
        if not self.monitor_interfaces:
            return False
        # Aprovecha el prefetch cache si está disponible
        return any(i.monitored for i in self.interfaces.all())

    @property
    def health_effectively_monitored(self) -> bool:
        """
        ¿Debe el equipo mostrar el bloque de Core Health en el monitor?

        Se cumplen las 2 condiciones:
          1. El usuario habilitó monitor_health para este equipo.
          2. El modelo (o el fabricante) define OIDs de chasis válidas.
        """
        if not self.monitor_health:
            return False
        if not self.device_model:
            return False
        # Delegamos la decisión al servicio (única fuente de verdad)
        try:
            from monitoreo.services.chassis_oids import (
                has_meaningful_health_metrics,
            )
            return has_meaningful_health_metrics(self)
        except Exception:
            return False

    @property
    def dashboard_interface_resolved(self):
        """
        Interfaz preferida para el dashboard o fallback a la primera
        con tráfico.

        Prioridad:
          1. `dashboard_interface` si está configurada.
          2. Primera interfaz con `monitored=True` y `oper_status=True`.
          3. None (sin interfaces).
        """
        if self.dashboard_interface_id:
            try:
                return self.dashboard_interface
            except Exception:
                pass
        return self.interfaces.filter(
            monitored=True, oper_status=True
        ).order_by("if_index").first()


# ============================================================
# INTERFAZ
# ============================================================
class Interface(models.Model):
    """Interfaz de red de un equipo."""

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="interfaces",
        verbose_name="Equipo",
    )
    if_index = models.PositiveIntegerField(verbose_name="ifIndex")
    if_name = models.CharField(
        max_length=100, null=True, blank=True, verbose_name="Nombre",
    )
    if_alias = models.CharField(
        max_length=100, null=True, blank=True, verbose_name="Alias",
    )
    if_speed_bps = models.BigIntegerField(
        null=True, blank=True, verbose_name="Velocidad (bps)",
    )
    if_type = models.CharField(
        max_length=50, null=True, blank=True, verbose_name="Tipo",
    )
    admin_status = models.BooleanField(
        default=True, verbose_name="Admin status",
    )
    oper_status = models.BooleanField(
        default=True, verbose_name="Oper status",
    )
    monitored = models.BooleanField(
        default=False, verbose_name="Monitoreada",
        help_text="Si está marcada, su tráfico se consulta vía SNMP.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "interfaces"
        unique_together = [("device", "if_index")]
        ordering = ["device", "if_index"]
        verbose_name = "Interfaz"
        verbose_name_plural = "Interfaces"

    def __str__(self):
        """Representación legible de la interfaz."""
        return f"{self.device.name} - {self.if_name or 'if' + str(self.if_index)}"

    @property
    def speed_mbps(self):
        """Velocidad en Mbps, o None si no está disponible."""
        if not self.if_speed_bps:
            return None
        return int(self.if_speed_bps / 1_000_000)

    @property
    def display_name(self):
        """Nombre a mostrar (nombre + alias si aplica)."""
        if self.if_alias:
            return f"{self.if_name or 'if' + str(self.if_index)} ({self.if_alias})"
        return self.if_name or f"if{self.if_index}"