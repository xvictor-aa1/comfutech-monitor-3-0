# monitoreo/services/alerts.py
"""
Motor de alertas basado en AlertRule (formato v2 con grupos).

Cada poller llama a `evaluate_metrics(device, {metric: value})` y el
motor evalúa las reglas que contienen ese device en alguno de sus
condicionales.

Soporta reglas con 1-5 grupos de 1-5 condicionales lógicos cada uno,
combinables con AND / OR / XOR y negación NOT a nivel de grupo y de
condicional.

Estado interno por condicional:
    _cond_states = {
        (rule_id, group_index, cond_index): {
            "first_seen": float,
            "last_seen": float,      # NEW: para detectar stale
            "last_value": float,
        }
    }

Estado de reglas disparadas (para fire_once y auto-resolve):
    _rule_fired = {rule_id: True}
    - Se inicializa desde BD al arrancar (`initialize_rule_state`).
    - Se limpia cuando la regla deja de cumplirse.

Índice de reglas en memoria:
    _rules_index = {
        "loaded_at": float,
        "all_rules": [AlertRule, ...],
        "all_rules_by_id": {rule_id: AlertRule},
        "by_device_metric": {(device_id, metric): [AlertRule, ...]},
    }
    - Reconstruido cuando cambia una AlertRule (signal) o por TTL (60s).
"""
import logging
import math
import re
import time
from threading import Lock
from typing import Optional

from django.utils import timezone

from alertas.models import Alert, AlertRule

log = logging.getLogger(__name__)

# ============================================================
# CONSTANTES
# ============================================================
# TTL de valores cacheados de OTROS devices.
# Si un device no reporta en este tiempo, su valor se considera stale
# y se ignora al evaluar reglas multi-equipo.
CACHE_TTL_SEC = 300  # 5 minutos

# TTL del índice de reglas en memoria (safety net si falla el signal).
RULES_CACHE_TTL_SEC = 60

# TTL para limpiar estados huérfanos de _cond_states.
STALE_STATE_MAX_AGE = 3600  # 1 hora

WARMUP_SECONDS = 120


# ============================================================
# ESTADO GLOBAL
# ============================================================
# Estado por condicional
_cond_states: dict = {}
_rule_lock = Lock()

# Reglas disparadas actualmente (para fire_once + auto-resolve)
_rule_fired: dict = {}

# Marca de tiempo de arranque del monitor (warm-up)
_monitor_start_time = time.time()

# Índice de reglas en memoria (para O(K) en vez de O(N×M))
_rules_index = {
    "loaded_at": 0.0,
    "all_rules": [],
    "all_rules_by_id": {},
    "by_device_metric": {},
}
_rules_index_lock = Lock()


# ============================================================
# HELPERS
# ============================================================
def _safe_number(v):
    """Convierte a float seguro, descartando NaN/Inf/fuera de rango."""
    if v is None:
        return None
    try:
        f = float(v)
    except (ValueError, TypeError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    if abs(f) > 1e15:
        return None
    return f


def _is_monitor_warming_up() -> bool:
    """¿Estamos dentro de la ventana de warm-up?"""
    return (time.time() - _monitor_start_time) < WARMUP_SECONDS


def _check_operator(value: float, operator: str, threshold: float) -> bool:
    """Aplica un operador de comparación entre value y threshold."""
    if operator == "gt":  return value > threshold
    if operator == "gte": return value >= threshold
    if operator == "lt":  return value < threshold
    if operator == "lte": return value <= threshold
    if operator == "eq":  return abs(value - threshold) < 0.001
    return False


def _apply_logic(op: str, a: bool, b: bool) -> bool:
    """Aplica un operador lógico entre dos booleanos."""
    op = (op or "AND").upper()
    if op == "AND": return a and b
    if op == "OR":  return a or b
    if op == "XOR": return a != b
    return a


# ============================================================
# INICIALIZACIÓN DE ESTADO
# ============================================================
def initialize_rule_state() -> None:
    """
    Carga en `_rule_fired` los rule_ids que tienen alertas activas en BD.

    Motivo: al reiniciar el monitor, `_rule_fired` es un dict vacío. Si
    había alertas activas que ahora deberían resolverse (porque la
    condición desapareció), el motor no las cierra porque no "recuerda"
    haberlas disparado.

    Solución: al arrancar, leer de BD qué reglas tienen alertas activas
    y marcarlas como "fired". Así el primer ciclo de evaluación que
    detecte `final_ready=False` las resolverá correctamente.
    """
    try:
        active_rule_ids = set(
            Alert.objects.filter(status="activa")
            .exclude(rule__isnull=True)
            .values_list("rule_id", flat=True)
            .distinct()
        )
        with _rule_lock:
            _rule_fired.clear()
            for rid in active_rule_ids:
                _rule_fired[rid] = True
        log.info(
            "Estado de reglas inicializado: %d regla(s) con alertas activas.",
            len(_rule_fired),
        )
    except Exception as e:
        log.error("Error inicializando estado de reglas: %s", e)


def reset_startup_time() -> None:
    """
    Reinicia el warm-up y recarga el estado de reglas.

    Llamado por el scheduler al arrancar el monitor.
    """
    global _monitor_start_time
    _monitor_start_time = time.time()
    log.info("Warm-up del monitor reiniciado (%ds).", WARMUP_SECONDS)
    # FIX BUG #1: cargar estado de reglas con alertas activas
    initialize_rule_state()
    # Resetear índice de reglas por si cambió algo mientras estaba apagado
    invalidate_rules_cache()


# ============================================================
# ÍNDICE DE REGLAS (FIX BUG #3)
# ============================================================
def invalidate_rules_cache() -> None:
    """
    Invalida el índice de reglas. Se llama desde el signal cuando se
    guarda/elimina una AlertRule, y al arrancar el monitor.
    """
    with _rules_index_lock:
        _rules_index["loaded_at"] = 0.0


def _get_rules_index() -> dict:
    """
    Devuelve el índice de reglas (reconstruido si es stale).

    Returns:
        dict con "all_rules", "all_rules_by_id", "by_device_metric".
    """
    now = time.time()
    with _rules_index_lock:
        if (
            _rules_index["all_rules"]
            and (now - _rules_index["loaded_at"]) < RULES_CACHE_TTL_SEC
        ):
            return _rules_index

    # Reconstruir
    try:
        rules = list(AlertRule.objects.filter(enabled=True))
    except Exception as e:
        log.error("Error cargando reglas para el índice: %s", e)
        return _rules_index

    by_dm: dict = {}
    by_id: dict = {}
    for rule in rules:
        by_id[rule.id] = rule
        seen_pairs: set = set()
        try:
            groups = rule.get_groups()
        except Exception as e:
            log.warning("Regla '%s' tiene estructura inválida: %s", rule.name, e)
            continue
        for g in groups:
            for cond in g.get("conditionals", []):
                did = cond.get("device_id")
                metric = cond.get("metric")
                if not did or not metric:
                    continue
                pair = (did, metric)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                by_dm.setdefault(pair, []).append(rule)

    with _rules_index_lock:
        _rules_index["all_rules"] = rules
        _rules_index["all_rules_by_id"] = by_id
        _rules_index["by_device_metric"] = by_dm
        _rules_index["loaded_at"] = now

    log.debug(
        "Índice de reglas reconstruido: %d regla(s), %d par(es) (device,metric).",
        len(rules), len(by_dm),
    )
    return _rules_index


# ============================================================
# LIMPIEZA DE ESTADOS HUÉRFANOS
# ============================================================
def cleanup_stale_states() -> int:
    """
    Elimina estados de `_cond_states` que llevan más de STALE_STATE_MAX_AGE
    sin actualizarse (reglas eliminadas o viejas).

    Llamar periódicamente (ej. desde el heartbeat del scheduler).

    Returns:
        int: número de estados eliminados.
    """
    now = time.time()
    removed = 0
    with _rule_lock:
        stale_keys = [
            k for k, v in _cond_states.items()
            if (now - v.get("last_seen", v.get("first_seen", 0))) > STALE_STATE_MAX_AGE
        ]
        for k in stale_keys:
            del _cond_states[k]
            removed += 1
    if removed:
        log.debug("Limpiados %d estado(s) huérfano(s) de condicionales.", removed)
    return removed


# ============================================================
# CONSTRUCCIÓN DE MENSAJES
# ============================================================
def _build_placeholders(rule, all_conds_flat, all_values_flat):
    """Construye el diccionario de placeholders para el mensaje."""
    groups = rule.get_groups()
    placeholders = {
        "rule_name": rule.name,
        "severity": rule.get_severity_display(),
        "conditionals_count": str(len(all_conds_flat)),
        "groups_count": str(len(groups)),
        "timestamp": timezone.localtime().strftime("%d/%m/%Y %H:%M:%S"),
    }

    metric_labels = dict(AlertRule.METRIC_CHOICES)
    operator_labels = dict(AlertRule.OPERATOR_CHOICES)

    for i, (cond, val) in enumerate(zip(all_conds_flat, all_values_flat)):
        idx = i + 1
        device = cond.get("device")
        metric = cond.get("metric", "")
        operator = cond.get("operator", "")
        threshold = cond.get("threshold")

        device_name = device.name if device else "—"
        device_ip = device.ip if device else "—"

        placeholders[f"device{idx}"] = device_name
        placeholders[f"ip{idx}"] = device_ip
        placeholders[f"metric{idx}"] = metric_labels.get(metric, metric)
        placeholders[f"operator{idx}"] = operator_labels.get(operator, operator)
        placeholders[f"threshold{idx}"] = (
            f"{threshold:.2f}" if threshold is not None else "—"
        )
        placeholders[f"value{idx}"] = f"{val:.2f}" if val is not None else "—"

        if i == 0:
            placeholders["device"] = device_name
            placeholders["ip"] = device_ip
            placeholders["metric"] = metric_labels.get(metric, metric)
            placeholders["operator"] = operator_labels.get(operator, operator)
            placeholders["threshold"] = (
                f"{threshold:.2f}" if threshold is not None else "—"
            )
            placeholders["value"] = f"{val:.2f}" if val is not None else "—"

    return placeholders


def _build_message(rule, groups, all_conds_flat, all_values_flat) -> str:
    """Construye el mensaje con estructura de grupos."""
    if rule.custom_message and rule.custom_message.strip():
        placeholders = _build_placeholders(rule, all_conds_flat, all_values_flat)
        def _replace(match):
            key = match.group(1)
            return placeholders.get(key, match.group(0))
        return re.sub(r"\{(\w+)\}", _replace, rule.custom_message)

    metric_labels = dict(AlertRule.METRIC_CHOICES)
    operator_labels = dict(AlertRule.OPERATOR_CHOICES)

    idx = 0
    group_strs = []
    for g in groups:
        parts = []
        for c in g.get("conditionals", []):
            flat = all_conds_flat[idx] if idx < len(all_conds_flat) else {}
            val = all_values_flat[idx] if idx < len(all_values_flat) else None
            idx += 1

            device = flat.get("device")
            metric = c.get("metric", "")
            operator = c.get("operator", "")
            threshold = c.get("threshold", 0)

            device_name = device.name if device else "—"
            metric_disp = metric_labels.get(metric, metric)
            op_disp = operator_labels.get(operator, operator)
            val_str = f"{val:.2f}" if val is not None else "—"

            prefix = "NOT " if c.get("negate") else ""
            parts.append(
                f"{prefix}[{device_name}] {metric_disp} {op_disp} "
                f"{threshold} (valor: {val_str})"
            )

        operators = g.get("operators") or []
        if not isinstance(operators, list) or len(operators) != len(parts) - 1:
            operators = ["AND"] * max(0, len(parts) - 1)

        joined = parts[0] if parts else ""
        for i in range(1, len(parts)):
            op = operators[i - 1] if i - 1 < len(operators) else "AND"
            joined += f" {op} {parts[i]}"

        if g.get("negate"):
            joined = f"NOT ({joined})"
        elif len(parts) > 1:
            joined = f"({joined})"

        group_strs.append(joined)

    if not group_strs:
        return f"Alerta: {rule.name}"

    result = group_strs[0]
    for i in range(1, len(group_strs)):
        logic = groups[i].get("logic") or "AND"
        result += f" {logic} {group_strs[i]}"
    return result


# ============================================================
# ALERTAS — CRUD
# ============================================================
def has_active_alert_for_rule(device_id: int, rule_id: int) -> bool:
    """¿Existe una alerta activa de esta regla para este device?"""
    return Alert.objects.filter(
        device_id=device_id, rule_id=rule_id, status="activa",
    ).exists()


def _resolve_all_alerts_for_rule(rule) -> int:
    """
    Marca TODAS las alertas activas de la regla como resueltas
    (independientemente del device).

    FIX BUG #1 + #4: reemplaza el `_resolve_alert(rule, device)` anterior,
    que solo resolvía el device primario. Ahora se resuelven todas las
    alertas activas de la regla, sin importar de qué device sean.
    """
    updated = Alert.objects.filter(
        rule=rule, status="activa",
    ).update(status="resuelta", resolved_at=timezone.now())
    if updated:
        log.info(
            "Auto-resueltas %d alerta(s) de la regla '%s'.",
            updated, rule.name,
        )
    return updated


def _create_alerts_for_rule(
    rule, groups, all_conds_flat, all_values_flat, cond_ready
):
    """
    Crea alertas para una regla disparada.

    FIX BUG #4: crea una alerta por cada dispositivo cuyos condicionales
    contribuyeron al disparo (con `cond_ready[i] == True`). Antes se
    creaba una sola alerta en el device del primer condicional, dejando
    invisibles las alertas para los otros devices.

    Args:
        rule, groups, all_conds_flat, all_values_flat: contexto.
        cond_ready: lista de bool indicando si el condicional i está
            listo (cumplió duración y está actualmente satisfecho).

    Returns:
        list[Alert]: alertas creadas.
    """
    # Determinar devices involucrados (con al menos un condicional ready)
    involved_device_ids = []
    for i, ready in enumerate(cond_ready):
        if not ready:
            continue
        device = all_conds_flat[i].get("device")
        if device and device.id not in involved_device_ids:
            involved_device_ids.append(device.id)

    if not involved_device_ids:
        return []

    # Construir mensaje y tipo (igual para todas las alertas de la regla)
    message = _build_message(rule, groups, all_conds_flat, all_values_flat)
    alert_type = (
        all_conds_flat[0].get("metric", "unknown")
        if len(all_conds_flat) == 1
        else "multi_conditional"
    )

    created = []
    for did in involved_device_ids:
        # Dedup por (device, rule)
        if has_active_alert_for_rule(did, rule.id):
            continue

        # Buscar la instancia de Device
        device = next(
            (c.get("device") for c in all_conds_flat
             if c.get("device") and c.get("device").id == did),
            None,
        )
        if not device:
            continue

        # Buscar el valor del primer condicional de ESTE device
        device_value = None
        device_threshold = None
        for i, cond in enumerate(all_conds_flat):
            if cond.get("device") and cond.get("device").id == did:
                device_value = all_values_flat[i] if i < len(all_values_flat) else None
                device_threshold = cond.get("threshold")
                break

        alert = Alert.objects.create(
            device=device,
            rule=rule,
            alert_type=alert_type,
            severity=rule.severity,
            message=message,
            value_observed=_safe_number(device_value),
            threshold_value=_safe_number(device_threshold),
            status="activa",
        )
        created.append(alert)
        log.warning(
            "ALERTA %s [%s]: %s",
            rule.severity.upper(), device.name, message,
        )

    # Notificación Telegram: UNA sola por disparo de regla
    if rule.telegram_enabled and created:
        try:
            from . import telegram
            has_custom = bool(rule.custom_message and rule.custom_message.strip())
            primary = created[0]
            telegram.send_alert(
                severity=rule.severity,
                message=primary.message,
                device=primary.device,
                rule=rule,
                append_context=not has_custom,
            )
        except Exception as e:
            log.error("Error enviando alerta a Telegram: %s", e)

    return created


# ============================================================
# EVALUACIÓN DE UNA REGLA
# ============================================================
def _evaluate_rule(rule, device_values):
    """
    Evalúa una regla con estructura de grupos v2.

    Args:
        rule: instancia de AlertRule.
        device_values: dict {device_id: {metric: value}}
    """
    if rule.skip_on_startup and _is_monitor_warming_up():
        return

    groups = rule.get_groups()
    if not groups:
        return

    # Cargar instancias de Device una sola vez
    from inventario.models import Device
    all_dev_ids = set()
    for g in groups:
        for c in g.get("conditionals", []):
            did = c.get("device_id")
            if did:
                all_dev_ids.add(did)
    devices_map = {d.id: d for d in Device.objects.filter(id__in=all_dev_ids)}

    now = time.time()

    group_ready = []
    all_conds_flat = []
    all_values_flat = []

    for gi, g in enumerate(groups):
        conds = g.get("conditionals", [])
        if not conds:
            group_ready.append(False)
            continue

        cond_ready = []

        for ci, c in enumerate(conds):
            did = c.get("device_id")
            metric = c.get("metric")
            operator = c.get("operator")
            threshold = float(c.get("threshold", 0))
            duration_sec = int(c.get("duration_sec", 60))
            c_negate = bool(c.get("negate", False))

            values_for_device = device_values.get(did, {})
            value = values_for_device.get(metric)

            satisfied = False
            if value is not None:
                satisfied = _check_operator(value, operator, threshold)

            if c_negate:
                satisfied = not satisfied

            # Estado por (rule, gi, ci)
            key = (rule.id, gi, ci)
            with _rule_lock:
                state = _cond_states.get(key)
                if satisfied:
                    if state is None:
                        _cond_states[key] = {
                            "first_seen": now,
                            "last_seen": now,
                            "last_value": value,
                        }
                        state = _cond_states[key]
                    else:
                        state["last_seen"] = now
                        state["last_value"] = value
                else:
                    _cond_states.pop(key, None)
                    state = None

            if state and (now - state["first_seen"]) >= duration_sec:
                cond_ready.append(True)
            else:
                cond_ready.append(False)

            all_conds_flat.append({
                "device": devices_map.get(did),
                "metric": metric,
                "operator": operator,
                "threshold": threshold,
                "duration_sec": duration_sec,
                "negate": c_negate,
                "group_index": gi + 1,
                "cond_index": ci + 1,
            })
            all_values_flat.append(value)

        # Combinar condicionales del grupo (izquierda a derecha por gap)
        operators = g.get("operators") or []
        if not isinstance(operators, list) or len(operators) != len(cond_ready) - 1:
            operators = ["AND"] * max(0, len(cond_ready) - 1)

        g_ready = cond_ready[0]
        for i in range(1, len(cond_ready)):
            op = operators[i - 1] if i - 1 < len(operators) else "AND"
            g_ready = _apply_logic(op, g_ready, cond_ready[i])

        # Aplicar NOT del grupo
        if g.get("negate", False):
            g_ready = not g_ready

        group_ready.append(g_ready)

    # Combinar grupos (izquierda a derecha)
    if not group_ready:
        return

    # Combinar grupos entre sí
    final_ready = group_ready[0]
    for i in range(1, len(group_ready)):
        logic = groups[i].get("logic") or "AND"
        final_ready = _apply_logic(logic, final_ready, group_ready[i])

    # ------------------------------------------------------------
    # Disparar / auto-resolver
    # ------------------------------------------------------------
    if final_ready:
        # fire_once
        if rule.fire_once and _rule_fired.get(rule.id):
            return

        _create_alerts_for_rule(
            rule, groups, all_conds_flat, all_values_flat, cond_ready,
        )

        with _rule_lock:
            _rule_fired[rule.id] = True
    else:
        # FIX BUG #1 + #4: resolver TODAS las alertas activas de la regla
        # (independientemente del device) sin depender de `_rule_fired`.
        # `_resolve_all_alerts_for_rule` es idempotente: solo actúa si hay
        # alertas activas en BD. Esto cubre también el caso de reinicio
        # del monitor (donde `_rule_fired` se carga vía
        # `initialize_rule_state()`, pero por robustez lo llamamos igual).
        try:
            resolved = _resolve_all_alerts_for_rule(rule)
        except Exception as e:
            log.error("Error auto-resolviendo alertas de '%s': %s", rule.name, e)
            resolved = 0

        # Resetear fire_once tracking
        with _rule_lock:
            _rule_fired.pop(rule.id, None)


# ============================================================
# EVALUACIÓN DE MÚLTIPLES MÉTRICAS
# ============================================================
def evaluate_metrics(device, metrics: dict):
    """
    Evalúa las reglas que contienen este device en algún condicional
    contra las métricas dadas.

    FIX BUG #3: usa el índice en memoria `by_device_metric` en vez de
    iterar TODAS las reglas activas. Con N reglas y M devices, pasa de
    O(N×M) a O(K) por ciclo, donde K = reglas que tocan (device, metric).

    FIX BUG #2: al construir `device_values` para OTROS devices, se
    verifica que el valor cacheado tenga menos de CACHE_TTL_SEC segundos
    de antigüedad. Si está stale, se trata como None.

    Args:
        device: instancia de Device.
        metrics: dict {metric: value} de este device.
    """
    if not metrics:
        return

    metric_names = [k for k, v in metrics.items() if v is not None]
    if not metric_names:
        return

    # Obtener índice de reglas
    index = _get_rules_index()
    by_dm = index["by_device_metric"]
    by_id = index["all_rules_by_id"]

    # Encontrar reglas que tocan (device, metric) para al menos una métrica
    matching_rule_ids = set()
    for metric_name in metric_names:
        key = (device.id, metric_name)
        for rule in by_dm.get(key, []):
            matching_rule_ids.add(rule.id)

    if not matching_rule_ids:
        return

    now = time.time()

    # Evaluar cada regla
    for rule_id in matching_rule_ids:
        rule = by_id.get(rule_id)
        if not rule or not rule.enabled:
            continue

        try:
            device_values = {device.id: metrics}

            # FIX BUG #2: leer valores cacheados de otros devices
            # aplicando TTL (CACHE_TTL_SEC).
            groups = rule.get_groups()
            for gi, group in enumerate(groups):
                for ci, cond in enumerate(group.get("conditionals", [])):
                    did = cond.get("device_id")
                    if did == device.id:
                        continue
                    if did in device_values:
                        continue
                    key = (rule.id, gi, ci)
                    with _rule_lock:
                        st = _cond_states.get(key)
                    if st and st.get("last_value") is not None:
                        last_seen = st.get("last_seen", 0)
                        age = now - last_seen
                        if age <= CACHE_TTL_SEC:
                            # Valor fresco: usar
                            device_values.setdefault(did, {})
                            device_values[did][cond.get("metric")] = st["last_value"]
                        else:
                            # Valor stale: tratar como ausente (None)
                            # Esto hará que el condicional evalúe False
                            log.debug(
                                "Regla '%s': valor cacheado stale (%.0fs) "
                                "para device=%s metric=%s",
                                rule.name, age, did, cond.get("metric"),
                            )
                            device_values.setdefault(did, {})
                            device_values[did][cond.get("metric")] = None

            _evaluate_rule(rule, device_values)
        except Exception as e:
            log.exception("Error evaluando regla '%s': %s", rule.name, e)


# ============================================================
# COMPATIBILIDAD CON API VIEJA
# ============================================================
def evaluate(device, metric: str, value: Optional[float], *args, **kwargs):
    """Compatibilidad: evalúa una sola métrica."""
    evaluate_metrics(device, {metric: value})


def has_active_alert(device_id: int, alert_type: str) -> bool:
    """Compatibilidad: existe alerta activa por tipo."""
    return Alert.objects.filter(
        device_id=device_id, alert_type=alert_type, status="activa",
    ).exists()


def load_thresholds_for(device):
    """Compatibilidad legacy."""
    return {}