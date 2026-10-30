# alertas/forms.py
"""
Formularios de la app `alertas`.

Incluye:
  - AlertRuleForm: crear/editar reglas con grupos de condicionales lógicos.
"""
import json
import logging

from django import forms
from django.core.exceptions import ValidationError

from inventario.models import Device
from .models import AlertRule

log = logging.getLogger(__name__)


class AlertRuleForm(forms.Form):
    """
    Formulario para crear o editar una regla de alerta.

    Los grupos de condicionales se envían como un JSON v2 en el campo
    oculto `conditionals_json`, construido por JavaScript desde la UI.
    """

    name = forms.CharField(
        max_length=150, required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control", "autofocus": True,
            "placeholder": "Ej: Alerta de saturación core",
        }),
        label="Nombre de la regla",
    )

    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 2,
            "placeholder": "Describe el propósito de esta regla (opcional)",
        }),
        label="Descripción",
    )

    conditionals_json = forms.CharField(
        widget=forms.HiddenInput(),
        required=True,
    )

    severity = forms.ChoiceField(
        choices=AlertRule.SEVERITY_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Prioridad",
        initial="warning",
    )

    custom_message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 3,
            "id": "id_custom_message",
            "placeholder": "{device1} con {metric1} = {value1} (umbral {threshold1})",
        }),
        label="Mensaje personalizado",
    )

    telegram_enabled = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Notificar por Telegram",
    )

    telegram_cooldown_sec = forms.IntegerField(
        required=False, initial=600, min_value=60, max_value=86400,
        widget=forms.NumberInput(attrs={
            "class": "form-control", "min": 60, "step": 60,
        }),
        label="Cooldown Telegram (s)",
    )

    fire_once = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Disparar solo una vez",
    )

    skip_on_startup = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Omitir al iniciar el monitor",
    )

    enabled = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Regla activa",
    )

    # ============================================================
    # VALIDACIÓN DE CONDICIONALES (v2)
    # ============================================================
    def clean_conditionals_json(self):
        """
        Valida el JSON de condicionales v2 (grupos).

        Reglas:
          - Formato: {"version": 2, "groups": [...]}
          - 1-5 grupos.
          - Cada grupo: 1-5 condicionales.
          - Total: máximo 10 condicionales.
          - `logic`: null (primero) | AND | OR | XOR.
          - `operator` dentro del grupo: AND | OR | XOR.
          - `negate`: bool (grupo o condicional).
          - `device_id` debe existir en la BD.
          - Métrica válida según METRIC_CHOICES.
          - Operador válido según la métrica.
          - `threshold` numérico.
          - `duration_sec` 0-86400.
        """
        raw = self.cleaned_data.get("conditionals_json") or ""

        # Parsear JSON
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            raise ValidationError("Los condicionales no tienen un formato válido.")

        # Debe ser un dict v2
        if not (isinstance(data, dict) and "groups" in data):
            raise ValidationError(
                "Formato inválido. Se esperaba "
                "{'version': 2, 'groups': [...]}."
            )

        groups = data.get("groups", [])
        if not isinstance(groups, list):
            raise ValidationError("'groups' debe ser una lista.")

        if len(groups) == 0:
            raise ValidationError("Debe agregar al menos 1 grupo con condicionales.")

        if len(groups) > AlertRule.MAX_GROUPS:
            raise ValidationError(
                f"Máximo {AlertRule.MAX_GROUPS} grupos permitidos."
            )

        metric_labels = dict(AlertRule.METRIC_CHOICES)
        total_conds = 0
        cleaned_groups = []

        for gi, g in enumerate(groups):
            prefix = f"Grupo {gi+1}: "

            if not isinstance(g, dict):
                raise ValidationError(f"{prefix}formato inválido.")

            conds = g.get("conditionals", [])
            if not isinstance(conds, list):
                raise ValidationError(f"{prefix}'conditionals' debe ser una lista.")
            if len(conds) == 0:
                raise ValidationError(f"{prefix}debe tener al menos 1 condicional.")
            if len(conds) > AlertRule.MAX_CONDITIONALS_PER_GROUP:
                raise ValidationError(
                    f"{prefix}máximo {AlertRule.MAX_CONDITIONALS_PER_GROUP} condicionales."
                )

            total_conds += len(conds)

            # Operadores entre condicionales del grupo (N-1 elementos)
            operators_raw = g.get("operators") or []
            if not isinstance(operators_raw, list):
                operators_raw = []
            expected_count = len(conds) - 1
            operators = []
            for oi in range(expected_count):
                op = operators_raw[oi] if oi < len(operators_raw) else "AND"
                if not isinstance(op, str):
                    op = "AND"
                op = (op or "AND").upper()
                if op not in ("AND", "OR", "XOR"):
                    op = "AND"
                operators.append(op)

            # Lógica hacia el grupo anterior (el primero no tiene)
            logic = g.get("logic")
            if gi == 0:
                logic = None
            elif logic not in ("AND", "OR", "XOR"):
                logic = "AND"

            negate = bool(g.get("negate", False))

            # Validar cada condicional del grupo
            cleaned_conds = []
            for ci, c in enumerate(conds):
                cprefix = f"{prefix}Condicional {ci+1}: "

                if not isinstance(c, dict):
                    raise ValidationError(f"{cprefix}formato inválido.")

                # Device
                device_id = c.get("device_id")
                if not device_id:
                    raise ValidationError(f"{cprefix}debe seleccionar un equipo.")
                try:
                    device_id = int(device_id)
                except (ValueError, TypeError):
                    raise ValidationError(f"{cprefix}ID de equipo inválido.")
                if not Device.objects.filter(pk=device_id).exists():
                    raise ValidationError(f"{cprefix}el equipo no existe.")

                # Metric
                metric = c.get("metric", "")
                if metric not in metric_labels:
                    raise ValidationError(f"{cprefix}métrica inválida.")

                # Operator
                operator = c.get("operator", "")
                valid_ops = [op for op, _ in AlertRule.get_valid_operators(metric)]
                if operator not in valid_ops:
                    operator = valid_ops[0] if valid_ops else "gte"

                # Threshold
                try:
                    threshold = float(c.get("threshold", 0))
                except (ValueError, TypeError):
                    raise ValidationError(f"{cprefix}umbral inválido.")

                if metric == "device_down":
                    operator = "eq"
                    threshold = 1 if int(threshold) == 1 else 0

                # Duration
                try:
                    duration_sec = int(c.get("duration_sec", 60))
                except (ValueError, TypeError):
                    duration_sec = 60
                duration_sec = max(0, min(86400, duration_sec))

                c_negate = bool(c.get("negate", False))

                cleaned_conds.append({
                    "device_id": device_id,
                    "metric": metric,
                    "operator": operator,
                    "threshold": threshold,
                    "duration_sec": duration_sec,
                    "negate": c_negate,
                })

            cleaned_groups.append({
                "logic": logic,
                "negate": negate,
                "operators": operators,
                "conditionals": cleaned_conds,
            })

        if total_conds > AlertRule.MAX_TOTAL_CONDITIONALS:
            raise ValidationError(
                f"Máximo {AlertRule.MAX_TOTAL_CONDITIONALS} condicionales en total "
                f"(tienes {total_conds})."
            )

        return {"version": 2, "groups": cleaned_groups}

    def clean_telegram_cooldown_sec(self):
        """Valida el cooldown mínimo."""
        cd = self.cleaned_data.get("telegram_cooldown_sec")
        if cd is None:
            return 600
        if cd < 60:
            raise ValidationError("El cooldown mínimo es de 60 segundos.")
        return cd

    # ============================================================
    # GUARDAR
    # ============================================================
    def save(self, rule: AlertRule = None, created_by=None) -> AlertRule:
        """
        Crea o actualiza una AlertRule.

        Args:
            rule: instancia existente para editar, o None para crear.
            created_by: usuario que crea la regla.

        Returns:
            AlertRule: la regla guardada.
        """
        data = self.cleaned_data

        if rule is None:
            rule = AlertRule()
            if created_by:
                rule.created_by = created_by

        rule.name = data["name"]
        rule.description = data.get("description", "")
        rule.conditionals = data["conditionals_json"]
        rule.severity = data["severity"]
        rule.custom_message = data.get("custom_message", "") or ""
        rule.telegram_enabled = bool(data.get("telegram_enabled"))
        rule.telegram_cooldown_sec = data.get("telegram_cooldown_sec") or 600
        rule.fire_once = bool(data.get("fire_once"))
        rule.skip_on_startup = bool(data.get("skip_on_startup"))
        rule.enabled = bool(data.get("enabled"))

        rule.save()
        return rule