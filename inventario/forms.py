# inventario/forms.py
"""
Formularios de la app `inventario`.

Incluye:
  - DeviceForm:      crear/editar equipos de red.
  - DeviceModelForm: crear/editar modelos de equipos con OIDs de chasis
                     y de radiofrecuencia, más un textarea JSON opcional.

Los OIDs del modelo se exponen como campos individuales por clave
conocida (cpu_pct, mem_pct, mem_used, mem_size, mem_free, temp_c,
uptime) en lugar de un textarea JSON crudo. Esto evita errores de
sintaxis y hace la UI mucho más amigable.
"""
import json
import re

from django import forms
from .models import Device, DeviceModel


# ============================================================
# PATRÓN DE VALIDACIÓN DE OID
# ============================================================
# Un OID SNMP es una secuencia de números separados por puntos.
# Ej: 1.3.6.1.2.1.1.3.0
OID_PATTERN = re.compile(r"^[0-9]+(\.[0-9]+)+$")

# Claves de OIDs conocidas por el servicio de chasis (chassis_oids.py).
# Solo estas se muestran como campos en el formulario.
OID_KEYS = [
    "cpu_pct",
    "mem_pct",
    "mem_used",
    "mem_size",
    "mem_free",
    "temp_c",
    "uptime",
]

# Claves de OIDs de chasis
CHASSIS_OID_KEYS = [
    "cpu_pct",
    "mem_pct",
    "mem_used",
    "mem_size",
    "mem_free",
    "temp_c",
    "uptime",
]

# Claves de OIDs de radiofrecuencia
RADIO_OID_KEYS = [
    "radio_freq",
    "radio_txpower",
    "wl_signal",
    "wl_noise_floor",
    "wl_ccq",
    "wl_tx_rate",
    "wl_rx_rate",
    "airmax_quality",
    "airmax_capacity",
    "chan_width",
]


# ============================================================
# HELPER: VALIDACIÓN DE OID
# ============================================================
def _validate_oid(value: str) -> str:
    """
    Valida el formato de un OID SNMP.

    Args:
        value: cadena a validar (puede venir vacía).

    Returns:
        str: el OID limpio (sin espacios) o cadena vacía.

    Raises:
        forms.ValidationError: si el formato no es válido.
    """
    if not value:
        return ""
    value = value.strip()
    if not value:
        return ""
    if not OID_PATTERN.match(value):
        raise forms.ValidationError(
            "El OID debe ser numérico con al menos un punto "
            "(ej: 1.3.6.1.2.1.1.3.0)."
        )
    return value

def _parse_json_dict(raw: str, label: str) -> dict:
    """
    Parsea un textarea JSON y verifica que sea un diccionario.

    Args:
        raw: contenido del textarea.
        label: nombre del campo para mensajes de error.

    Returns:
        dict: diccionario parseado (vacío si raw está vacío).

    Raises:
        forms.ValidationError: si el JSON es inválido o no es un objeto.
    """
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise forms.ValidationError(
            f"JSON inválido en {label}: {e.msg} (línea {e.lineno})."
        )
    if not isinstance(data, dict):
        raise forms.ValidationError(
            f"{label} debe ser un objeto JSON ({{...}}), no una lista."
        )
    for k, v in data.items():
        if not isinstance(k, str):
            raise forms.ValidationError(
                f"Las claves de {label} deben ser texto."
            )
        if not isinstance(v, str):
            raise forms.ValidationError(
                f"El valor de '{k}' en {label} debe ser texto (OID)."
            )
        if v and not OID_PATTERN.match(v.strip()):
            raise forms.ValidationError(
                f"El OID de '{k}' en {label} no es válido."
            )
    return data


# ============================================================
# FORM: EQUIPO (ya existente)
# ============================================================
class DeviceForm(forms.ModelForm):
    """
    Formulario para crear o editar un equipo de red.

    Gestiona el filtrado dinámico de modelos según el fabricante
    seleccionado, la validación de IP única y la coherencia entre
    fabricante y modelo.

    Características:
      - El select de fabricante solo muestra los fabricantes que tienen
        al menos un modelo ACTIVO registrado. Si se edita un equipo cuyo
        fabricante ya no tiene modelos activos, ese fabricante se preserva
        para no perder el valor.
      - El select de modelo se filtra dinámicamente por fabricante
        (AJAX en el frontend).
      - `monitor_interfaces` se deshabilita si el modelo no soporta interfaces.
      - `monitor_health` se deshabilita si el modelo no tiene OIDs de chasis.
      - Validación cruzada de SNMPv3 (user + auth requeridos).
    """

    class Meta:
        model = Device
        fields = [
            "name",
            "ip",
            "device_type",
            "device_role",
            "vendor",
            "device_model",
            "location",
            "snmp_version",
            "snmp_community",
            "snmp_user",
            "snmp_auth",
            "snmp_priv",
            "tcp_ports",
            "monitor_interfaces",
            "monitor_health",
            "active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "autofocus": True,
                "placeholder": "Ej: RB Güigüe",
            }),
            "ip": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "192.168.1.1",
            }),
            "device_type": forms.Select(attrs={
                "class": "form-select",
                "id": "id_device_type",
            }),
            "device_role": forms.Select(attrs={
                "class": "form-select",
                "id": "id_device_role",
            }),
            "vendor": forms.Select(attrs={
                "class": "form-select",
                "id": "id_vendor",
            }),
            "device_model": forms.Select(attrs={
                "class": "form-select",
                "id": "id_device_model",
            }),
            "location": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej: Güigüe",
            }),
            "snmp_version": forms.Select(
                choices=[("1", "SNMPv1"), ("2c", "SNMPv2c"), ("3", "SNMPv3")],
                attrs={"class": "form-select", "id": "id_snmp_version"},
            ),
            "snmp_community": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "public",
                "id": "id_snmp_community",
            }),
            "snmp_user": forms.TextInput(attrs={
                "class": "form-control",
                "id": "id_snmp_user",
            }),
            "snmp_auth": forms.TextInput(attrs={
                "class": "form-control",
                "id": "id_snmp_auth",
            }),
            "snmp_priv": forms.TextInput(attrs={
                "class": "form-control",
                "id": "id_snmp_priv",
            }),
            "tcp_ports": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "443,22,80",
            }),
            "monitor_interfaces": forms.CheckboxInput(attrs={
                "class": "form-check-input",
                "id": "id_monitor_interfaces",
            }),
            "monitor_health": forms.CheckboxInput(attrs={
                "class": "form-check-input",
                "id": "id_monitor_health",
            }),
            "active": forms.CheckboxInput(attrs={
                "class": "form-check-input",
                "id": "id_active",
            }),
        }

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario con filtros dinámicos."""
        super().__init__(*args, **kwargs)

        # 1. Filtrar vendors (solo con modelos activos)
        active_vendors = set(
            DeviceModel.objects.filter(active=True)
            .values_list("vendor", flat=True)
            .distinct()
        )
        if self.instance and self.instance.pk and self.instance.vendor:
            active_vendors.add(self.instance.vendor)

        vendor_labels = dict(Device.VENDOR_CHOICES)
        vendor_choices = [("", "— Seleccione un fabricante —")]
        vendor_choices += [
            (v, vendor_labels.get(v, v)) for v in sorted(active_vendors)
        ]
        self.fields["vendor"].choices = vendor_choices
        self.fields["vendor"].required = True

        # 2. Filtrar modelos por vendor
        self.fields["device_model"].required = True
        self.fields["device_model"].empty_label = "— Seleccione primero un fabricante —"
        self.fields["device_model"].queryset = DeviceModel.objects.none()

        vendor = None
        if self.data.get("vendor"):
            vendor = self.data.get("vendor")
        elif self.instance and self.instance.pk:
            vendor = self.instance.vendor

        if vendor:
            self.fields["device_model"].queryset = DeviceModel.objects.filter(
                vendor=vendor, active=True
            ).order_by("name")

        # 3. Determinar modelo actual
        current_model = None
        if self.data.get("device_model"):
            try:
                current_model = DeviceModel.objects.get(
                    pk=int(self.data["device_model"])
                )
            except (DeviceModel.DoesNotExist, ValueError, TypeError):
                pass
        elif self.instance and self.instance.pk:
            current_model = self.instance.device_model

        # 4. Deshabilitar monitor_interfaces si el modelo no lo soporta
        if current_model and not current_model.has_interfaces:
            self.fields["monitor_interfaces"].disabled = True
            self.fields["monitor_interfaces"].initial = False

        # 5. Deshabilitar monitor_health si el modelo no tiene OIDs de chasis
        if current_model:
            from monitoreo.services.chassis_oids import CHASSIS_OIDS
            vendor_lower = (current_model.vendor or "").lower()
            has_chassis = bool(current_model.oids) or bool(
                CHASSIS_OIDS.get(vendor_lower)
            )
            if not has_chassis:
                self.fields["monitor_health"].disabled = True
                self.fields["monitor_health"].initial = False

    def clean_ip(self):
        """Valida que la IP sea única entre equipos."""
        ip = self.cleaned_data.get("ip", "").strip()
        qs = Device.objects.filter(ip=ip)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Ya existe un equipo con esta IP.")
        return ip

    def clean(self):
        """Valida coherencia fabricante ↔ modelo y campos SNMPv3."""
        cleaned = super().clean()
        vendor = cleaned.get("vendor")
        device_model = cleaned.get("device_model")

        # Coherencia fabricante ↔ modelo
        if vendor and device_model and device_model.vendor != vendor:
            self.add_error(
                "device_model",
                "El modelo seleccionado no pertenece al fabricante elegido.",
            )

        # SNMPv3: user + auth obligatorios
        if cleaned.get("snmp_version") == "3":
            if not cleaned.get("snmp_user"):
                self.add_error("snmp_user", "Requerido para SNMPv3.")
            if not cleaned.get("snmp_auth"):
                self.add_error("snmp_auth", "Requerido para SNMPv3.")

        # Forzar monitores a False si el modelo no los soporta
        if device_model:
            if not device_model.has_interfaces:
                cleaned["monitor_interfaces"] = False

            from monitoreo.services.chassis_oids import CHASSIS_OIDS
            vendor_lower = (device_model.vendor or "").lower()
            has_chassis = bool(device_model.oids) or bool(
                CHASSIS_OIDS.get(vendor_lower)
            )
            if not has_chassis:
                cleaned["monitor_health"] = False

        return cleaned


# ============================================================
# FORM: MODELO DE EQUIPO
# ============================================================
class DeviceModelForm(forms.ModelForm):
    """
    Formulario para crear o editar un modelo de equipo.

    Los OIDs específicos del modelo se editan como **campos individuales
    por clave conocida** (cpu_pct, mem_pct, mem_used, mem_size, mem_free,
    temp_c, uptime), en lugar de exponer un textarea JSON crudo. Al
    guardar, se reconstruye el diccionario y se asigna al campo JSON
    `oids` del modelo.

    Reglas de negocio:
      - Si el modelo ya tiene equipos asociados, NO se permite cambiar
        el fabricante (rompería la consistencia Device.vendor ==
        DeviceModel.vendor).
      - Los OIDs son todos opcionales. Si se dejan vacíos, el poller
        de chasis usará los OIDs por defecto del fabricante
        (`chassis_oids.py`).

    Expone los OIDs como campos individuales agrupados en dos secciones:
      - OIDs de chasis (CPU, memoria, temperatura, uptime).
      - OIDs de radiofrecuencia (frecuencia, potencia, señal, ruido,
        CCQ, tasas TX/RX, calidad/capacidad airMAX, ancho de canal).

    Incluye además dos textareas JSON opcionales que permiten pegar
    directamente un diccionario de OIDs. Si se rellenan, sus claves
    **sobrescriben** los campos individuales.
    """

    # --- Campos auxiliares para cada OID ---
    oid_cpu_pct = forms.CharField(
        required=False,
        label="CPU (%)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.14988.1.1.3.10.0",
        }),
        help_text="OID del porcentaje de uso de CPU.",
    )
    oid_mem_pct = forms.CharField(
        required=False,
        label="Memoria (%)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7.1",
        }),
        help_text="OID del porcentaje de uso de memoria (si existe directo).",
    )
    oid_mem_used = forms.CharField(
        required=False,
        label="Memoria usada",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.2.1.25.2.3.1.6.65536",
        }),
        help_text="OID de bytes usados (se combina con mem_size).",
    )
    oid_mem_size = forms.CharField(
        required=False,
        label="Memoria total",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.2.1.25.2.3.1.5.65536",
        }),
        help_text="OID del tamaño total de memoria.",
    )
    oid_mem_free = forms.CharField(
        required=False,
        label="Memoria libre",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.9.9.48.1.1.1.6.1",
        }),
        help_text="OID de bytes libres (alternativa a mem_used + mem_size).",
    )
    oid_temp_c = forms.CharField(
        required=False,
        label="Temperatura (°C)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.14988.1.1.3.100.1.3.14",
        }),
        help_text="OID de temperatura del chasis.",
    )
    oid_uptime = forms.CharField(
        required=False,
        label="Uptime",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.2.1.1.3.0",
        }),
        help_text="OID de uptime (TimeTicks). Se autocompleta si se deja vacío.",
    )

    # --- Campos auxiliares de radiofrecuencia ---
    oid_radio_freq = forms.CharField(
        required=False,
        label="Frecuencia RF (MHz)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.41112.1.4.1.1.4.1",
        }),
        help_text="Frecuencia de operación actual del radio (MHz).",
    )
    oid_radio_txpower = forms.CharField(
        required=False,
        label="TX Power (dBm)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.41112.1.4.1.1.6.1",
        }),
        help_text="Potencia de transmisión configurada (dBm).",
    )
    oid_wl_signal = forms.CharField(
        required=False,
        label="Signal (dBm)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.41112.1.4.5.1.5.1",
        }),
        help_text="Nivel de señal recibida (dBm). Típico: -40 a -80 dBm.",
    )
    oid_wl_noise_floor = forms.CharField(
        required=False,
        label="Noise Floor (dBm)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.41112.1.4.5.1.8.1",
        }),
        help_text="Nivel de ruido en el canal (dBm). Típico: -95 a -80 dBm.",
    )
    oid_wl_ccq = forms.CharField(
        required=False,
        label="CCQ (%)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.41112.1.4.5.1.7.1",
        }),
        help_text="Calidad del enlace (%). Valores >80% son buenos.",
    )
    oid_wl_tx_rate = forms.CharField(
        required=False,
        label="TX Rate (bps)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.41112.1.4.5.1.9.1",
        }),
        help_text="Tasa de transmisión actual en bits por segundo (bps).",
    )
    oid_wl_rx_rate = forms.CharField(
        required=False,
        label="RX Rate (bps)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.41112.1.4.5.1.10.1",
        }),
        help_text="Tasa de recepción actual en bits por segundo (bps).",
    )
    oid_airmax_quality = forms.CharField(
        required=False,
        label="airMAX Quality (%)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.41112.1.4.6.1.4.1",
        }),
        help_text="Calidad global del enlace airMAX (%).",
    )
    oid_airmax_capacity = forms.CharField(
        required=False,
        label="airMAX Capacity (%)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.41112.1.4.6.1.5.1",
        }),
        help_text="Capacidad estimada del enlace airMAX (%).",
    )
    oid_chan_width = forms.CharField(
        required=False,
        label="Ancho de canal (MHz)",
        widget=forms.TextInput(attrs={
            "class": "form-control font-monospace form-control-sm",
            "placeholder": "1.3.6.1.4.1.41112.1.4.5.1.14.1",
        }),
        help_text="Ancho del canal configurado (MHz). Ej: 10, 20, 40, 80.",
    )

    # --- Textareas JSON opcionales ---
    chassis_oids_json = forms.CharField(
        required=False,
        label="OIDs de chasis (JSON avanzado)",
        widget=forms.Textarea(attrs={
            "class": "form-control font-monospace",
            "rows": 3,
            "placeholder": '{"cpu_pct": "1.3.6...", "mem_pct": "1.3.6..."}',
        }),
        help_text="Opcional. Si lo rellenas, sobrescribe los campos individuales.",
    )
    radio_oids_json = forms.CharField(
        required=False,
        label="OIDs de radiofrecuencia (JSON avanzado)",
        widget=forms.Textarea(attrs={
            "class": "form-control font-monospace",
            "rows": 4,
            "placeholder": '{"radio_freq": "1.3.6...", "wl_signal": "1.3.6..."}',
        }),
        help_text="Opcional. Si lo rellenas, sobrescribe los campos individuales.",
    )

    class Meta:
        model = DeviceModel
        fields = [
            "vendor",
            "name",
            "description",
            "is_wireless_link",
            "has_interfaces", 
            "active",
        ]
        widgets = {
            "vendor": forms.Select(attrs={
                "class": "form-select",
                "autofocus": True,
            }),
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej: RB4011iGS+, AirMax LiteBeam M5",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Notas opcionales sobre el modelo (firmware, características, etc.)",
            }),
            "is_wireless_link": forms.CheckboxInput(attrs={
                "class": "form-check-input",
                "id": "id_is_wireless_link"
            }),
            "has_interfaces": forms.CheckboxInput(attrs={
                "class": "form-check-input",
                "id": "id_has_interfaces",
            }),
            "active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "vendor": "Fabricante",
            "name": "Nombre del modelo",
            "description": "Descripción",
            "is_wireless_link": "Es radio-enlace",
            "has_interfaces": "Tiene interfaces SNMP",
            "active": "Modelo activo",
        }

    def __init__(self, *args, **kwargs):
        """
        Inicializa el formulario.

        - Precarga los valores actuales de OIDs en sus campos
          correspondientes (si es edición).
        - Bloquea el campo `vendor` si el modelo ya tiene equipos
          asociados (para evitar inconsistencias).
        - Precarga textareas JSON si el modelo ya tiene datos.
        """
        super().__init__(*args, **kwargs)

        # Precargar OIDs existentes
        if self.instance and self.instance.pk:
            # Precargar OIDs individuales
            for key in CHASSIS_OID_KEYS:
                field = f"oid_{key}"
                if field in self.fields:
                    val = (self.instance.oids or {}).get(key, "")
                    if val:
                        self.fields[field].initial = val
            for key in RADIO_OID_KEYS:
                field = f"oid_{key}"
                if field in self.fields:
                    val = (self.instance.radio_oids or {}).get(key, "")
                    if val:
                        self.fields[field].initial = val

            # Precargar textareas JSON
            if self.instance.oids:
                self.fields["chassis_oids_json"].initial = json.dumps(
                    self.instance.oids, indent=2, ensure_ascii=False
                )
            if self.instance.radio_oids:
                self.fields["radio_oids_json"].initial = json.dumps(
                    self.instance.radio_oids, indent=2, ensure_ascii=False
                )

            # Bloquear cambio de vendor si hay equipos asociados
            if self.instance.devices.exists():
                self.fields["vendor"].disabled = True
                self.fields["vendor"].help_text = (
                    "No puedes cambiar el fabricante: este modelo ya está "
                    "siendo usado por uno o más equipos."
                )

    # ------------------------------------------------------------
    # VALIDACIÓN INDIVIDUAL DE CADA OID
    # ------------------------------------------------------------

    # --- Validación individual ---
    def clean_oid_cpu_pct(self):
        return _validate_oid(self.cleaned_data.get("oid_cpu_pct"))
    def clean_oid_mem_pct(self):
        return _validate_oid(self.cleaned_data.get("oid_mem_pct"))
    def clean_oid_mem_used(self):
        return _validate_oid(self.cleaned_data.get("oid_mem_used"))
    def clean_oid_mem_size(self):
        return _validate_oid(self.cleaned_data.get("oid_mem_size"))
    def clean_oid_mem_free(self):
        return _validate_oid(self.cleaned_data.get("oid_mem_free"))
    def clean_oid_temp_c(self):
        return _validate_oid(self.cleaned_data.get("oid_temp_c"))
    def clean_oid_uptime(self):
        return _validate_oid(self.cleaned_data.get("oid_uptime"))
    def clean_oid_radio_freq(self):
        return _validate_oid(self.cleaned_data.get("oid_radio_freq"))
    def clean_oid_radio_txpower(self):
        return _validate_oid(self.cleaned_data.get("oid_radio_txpower"))
    def clean_oid_wl_signal(self):
        return _validate_oid(self.cleaned_data.get("oid_wl_signal"))
    def clean_oid_wl_noise_floor(self):
        return _validate_oid(self.cleaned_data.get("oid_wl_noise_floor"))
    def clean_oid_wl_ccq(self):
        return _validate_oid(self.cleaned_data.get("oid_wl_ccq"))
    def clean_oid_wl_tx_rate(self):
        return _validate_oid(self.cleaned_data.get("oid_wl_tx_rate"))
    def clean_oid_wl_rx_rate(self):
        return _validate_oid(self.cleaned_data.get("oid_wl_rx_rate"))
    def clean_oid_airmax_quality(self):
        return _validate_oid(self.cleaned_data.get("oid_airmax_quality"))
    def clean_oid_airmax_capacity(self):
        return _validate_oid(self.cleaned_data.get("oid_airmax_capacity"))
    def clean_oid_chan_width(self):
        return _validate_oid(self.cleaned_data.get("oid_chan_width"))

    # ------------------------------------------------------------
    # VALIDACIÓN DE TEXTAREAS JSON
    # ------------------------------------------------------------
    def clean_chassis_oids_json(self):
        """Parsea y valida el JSON de OIDs de chasis."""
        return _parse_json_dict(
            self.cleaned_data.get("chassis_oids_json", ""),
            "OIDs de chasis",
        )

    def clean_radio_oids_json(self):
        """Parsea y valida el JSON de OIDs de RF."""
        return _parse_json_dict(
            self.cleaned_data.get("radio_oids_json", ""),
            "OIDs de radiofrecuencia",
        )

    # ------------------------------------------------------------
    # VALIDACIÓN CRUZADA
    # ------------------------------------------------------------
    def clean_vendor(self):
        """
        Bloquea el cambio de fabricante si el modelo ya tiene equipos.

        El `disabled=True` en `__init__` ya lo impide en la UI, pero
        esta validación es la red de seguridad del lado servidor.
        """
        vendor = self.cleaned_data.get("vendor")
        if (self.instance and self.instance.pk
            and self.instance.devices.exists()
            and vendor != self.instance.vendor
        ):
            raise forms.ValidationError(
                "No puedes cambiar el fabricante de un modelo que ya está "
                "siendo usado por equipos. Desasócialos primero o crea un "
                "modelo nuevo."
            )
        return vendor

    def clean(self):
        """
        Valida coherencia entre campos de memoria.

        Si el usuario ingresa `mem_pct` Y también `mem_used`/`mem_size`,
        se prioriza `mem_pct` en el poller. No es un error, solo se
        advierte en la UI.
        """
        cleaned = super().clean()
        return cleaned

    # ------------------------------------------------------------
    # GUARDADO
    # ------------------------------------------------------------
    def save(self, commit=True):
        """
        Guarda el modelo, reconstruyendo el dict `oids` a partir de
        los campos auxiliares.

        Si todos los campos de OIDs están vacíos, `oids` queda como
        `{}` (diccionario vacío), lo que activa el fallback a los
        OIDs por defecto del fabricante.

        Guarda el modelo combinando:
          1. OIDs individuales (chasis + RF).
          2. Textareas JSON (sobrescriben los individuales si están presentes).

        Args:
            commit: si True, guarda en BD inmediatamente.

        Returns:
            DeviceModel: la instancia guardada.
        """
        instance = super().save(commit=False)

        # --- Chasis ---
        chassis = {}
        for key in CHASSIS_OID_KEYS:
            val = self.cleaned_data.get(f"oid_{key}")
            if val:
                chassis[key] = val
        json_chassis = self.cleaned_data.get("chassis_oids_json") or {}
        if json_chassis:
            chassis.update(json_chassis)
        instance.oids = chassis

        # --- Radiofrecuencia (solo si es wireless) ---
        radio = {}
        if self.cleaned_data.get("is_wireless_link"):
            for key in RADIO_OID_KEYS:
                val = self.cleaned_data.get(f"oid_{key}")
                if val:
                    radio[key] = val
            json_radio = self.cleaned_data.get("radio_oids_json") or {}
            if json_radio:
                radio.update(json_radio)
        instance.radio_oids = radio

        if commit:
            instance.save()
        return instance