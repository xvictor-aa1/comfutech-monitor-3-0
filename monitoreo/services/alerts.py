# monitoreo/services/alerts.py
"""
Motor de alertas basado en AlertRule (formato v2 con grupos).

A partir de la v4, el motor soporta DOS bloques de condicionales por
regla:

  · `conditionals` (obligatorio) — define CUÁNDO dispara la alerta.
  · `auto_resolve_conditionals` (opcional) — define CUÁNDO se resuelve
    automáticamente la alerta.

Comportamiento de auto-resolución:
  · Si `enable_auto_resolve=True` Y el bloque de auto-resolución tiene
    al menos un condicional → se evalúa el bloque; si se cumple, se
    resuelven las alertas activas de la regla.
  · En caso contrario (deshabilitado o bloque vacío) → se aplica el
    comportamiento clásico: resolver cuando las condiciones de disparo
    dejan de cumplirse.

Además, `mark_as_resolved=True` crea las alertas directamente en
estado "resuelta" (útil para alertas puramente informativas). Estas
alertas se deduplican como `fire_once` para no generar una alerta
por cada ciclo.

Estado interno por condicional:
    _cond_states = {
        (prefix, rule_id, group_index, cond_index): {
            "first_seen": float,
            "last_seen": float,
            "last_value": float,
        }
    }
    donde `prefix` es "trigger" (disparo) o "auto" (auto-resolución).

Estado de reglas disparadas (para fire_once y dedupe):
    _rule_fired = {rule_id: True}
    - Se inicializa desde BD al arrancar (`initialize_rule_state`).
    - Se limpia cuando la regla deja de cumplirse.

Índice de reglas en memoria:
    _rules_index = {...}
    - Reconstruido cuando cambia una AlertRule (signal) o por TTL (60s).
"""
import logging
import math
import re
import time
from threading import Lock
from typing import Optional

from django.db import IntegrityError
from django.utils import timezone

from alertas.models import Alert, AlertRule

log = logging.getLogger(__name__)

# ============================================================
# CONSTANTES
# ============================================================
# TTL de valores cacheados de OTROS devices.
CACHE_TTL_SEC = 300  # 5 minutos

# TTL del índice de reglas en memoria.
RULES_CACHE_TTL_SEC = 60

# TTL para limpiar estados huérfanos de _cond_states.
STALE_STATE_MAX_AGE = 3600  # 1 hora

WARMUP_SECONDS = 120


# ============================================================
# ESTADO GLOBAL
# ============================================================
# Estado por condicional: la clave incluye un prefijo ("trigger"/"auto")
# para separar el estado del bloque de disparo del de auto-resolución.
_cond_states: dict = {}
_rule_lock = Lock()

# Reglas disparadas actualmente (para fire_once + dedupe mark_as_resolved).
_rule_fired: dict = {}

# Marca de tiempo de arranque del monitor (warm-up).
_monitor_start_time = time.time()

# Índice de reglas en memoria.
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
    """
    try:
        active_rule_ids = set(
            Alert.objects.filter(status="activa")
            .exclude(rule_id__isnull=True)
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
    """Reinicia el warm-up y recarga el estado de reglas."""
    global _monitor_start_time
    _monitor_start_time = time.time()
    log.info("Warm-up del monitor reiniciado (%ds).", WARMUP_SECONDS)
    initialize_rule_state()
    invalidate_rules_cache()


# ============================================================
# ÍNDICE DE REGLAS
# ============================================================
def invalidate_rules_cache() -> None:
    """Invalida el índice de reglas (se llama desde signal y al arrancar)."""
    with _rules_index_lock:
        _rules_index["loaded_at"] = 0.0


def _get_rules_index() -> dict:
    """Devuelve el índice de reglas (reconstruido si es stale)."""
    now = time.time()
    with _rules_index_lock:
        if (
            _rules_index["all_rules"]
            and (now - _rules_index["loaded_at"]) < RULES_CACHE_TTL_SEC
        ):
            return _rules_index

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
    Elimina estados de `_cond_states` con más de STALE_STATE_MAX_AGE
    sin actualizarse. Funciona con cualquier prefijo ("trigger"/"auto").

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
# ALERTAS — CONSULTAS (SIN FK, POR rule_id)
# ============================================================
def has_active_alert_for_rule(rule_id: int) -> bool:
    """
    ¿Existe una alerta activa para esta regla?

    A partir de v4, las alertas NO se vinculan a devices. El dedupe
    es por `rule_id` únicamente.
    """
    return Alert.objects.filter(rule_id=rule_id, status="activa").exists()


def _resolve_all_alerts_for_rule(rule) -> int:
    """
    Marca TODAS las alertas activas de la regla como resueltas.
    """
    updated = Alert.objects.filter(
        rule_id=rule.id, status="activa",
    ).update(status="resuelta", resolved_at=timezone.now())
    if updated:
        log.info(
            "Auto-resueltas %d alerta(s) de la regla '%s'.",
            updated, rule.name,
        )
    return updated


# ============================================================
# CREACIÓN DE ALERTAS
# ============================================================
def _create_alert_for_rule(
    rule, groups, all_conds_flat, all_values_flat, cond_ready,
) -> list:
    """
    Crea UNA alerta para una regla disparada.

    A partir de v4:
      · No se vincula a device (no hay FK).
      · Se guarda `rule_id` + `rule_name` (snapshot).
      · Dedupe por `rule_id` (no por device).
      · Si `rule.mark_as_resolved=True`, la alerta se crea con
        estado "resuelta" y `resolved_at=now()` (útil para Info).
      · Si `mark_as_resolved=True`, se trata como `fire_once` para
        dedupe (evita crear una alerta por cada ciclo).
      · `value_observed` / `threshold_value` se toman del PRIMER
        condicional que efectivamente disparó (`cond_ready[i] == True`),
        no del primero de la lista. Esto da un valor representativo
        cuando la regla tiene varios condicionales.
      · La creación se envuelve en try/except IntegrityError para
        manejar la race condition entre pollers concurrentes que
        evalúan la misma regla (gracias al UniqueConstraint
        `unique_active_alert_per_rule` del modelo Alert).

    Args:
        rule, groups, all_conds_flat, all_values_flat: contexto de la
            evaluación.
        cond_ready: lista de bool (uno por condicional) indicando si
            el condicional cumplió duración y está actualmente
            satisfecho.

    Returns:
        list[Alert]: alertas creadas (0 o 1).
    """
    # Dedupe: si ya hay una alerta activa, no crear otra.
    if has_active_alert_for_rule(rule.id):
        return []

    # Dedupe para mark_as_resolved: tratar como fire_once.
    if rule.mark_as_resolved and _rule_fired.get(rule.id):
        return []

    # Construir mensaje (ya incluye device names vía placeholders).
    message = _build_message(rule, groups, all_conds_flat, all_values_flat)

    alert_type = (
        all_conds_flat[0].get("metric", "unknown")
        if len(all_conds_flat) == 1
        else "multi_conditional"
    )

    # Elegir el condicional que efectivamente disparó para
    # `value_observed`. Si solo hay uno, usar ese. Si hay varios,
    # usar el primero con `cond_ready=True`. Fallback al primero.
    ref_idx = 0
    if len(all_conds_flat) > 1:
        for i, ready in enumerate(cond_ready):
            if ready:
                ref_idx = i
                break

    ref_value = all_values_flat[ref_idx] if all_values_flat else None
    ref_threshold = (
        all_conds_flat[ref_idx].get("threshold")
        if all_conds_flat else None
    )

    # Estado inicial según mark_as_resolved.
    if rule.mark_as_resolved:
        initial_status = "resuelta"
        resolved_at = timezone.now()
    else:
        initial_status = "activa"
        resolved_at = None

    try:
        alert = Alert.objects.create(
            rule_id=rule.id,
            rule_name=rule.name,
            alert_type=alert_type,
            severity=rule.severity,
            message=message,
            value_observed=_safe_number(ref_value),
            threshold_value=_safe_number(ref_threshold),
            status=initial_status,
            resolved_at=resolved_at,
        )
    except IntegrityError:
        # Otra instancia ya creó la alerta activa. No es un error.
        log.debug(
            "Alerta activa ya creada por otro proceso para regla %s (%s).",
            rule.id, rule.name,
        )
        return []

    log.warning(
        "ALERTA %s [rule=%s, name='%s']: %s",
        rule.severity.upper(), rule.id, rule.name, message,
    )

    # Notificación Telegram (una sola por disparo de regla).
    if rule.telegram_enabled:
        try:
            from . import telegram
            has_custom = bool(rule.custom_message and rule.custom_message.strip())
            telegram.send_alert(
                severity=rule.severity,
                message=alert.message,
                device=None,
                rule=rule,
                append_context=not has_custom,
            )
        except Exception as e:
            log.error("Error enviando alerta a Telegram: %s", e)

    return [alert]


# ============================================================
# EVALUACIÓN DE UN BLOQUE DE CONDICIONALES (v2)
# ============================================================
def _evaluate_block(rule, groups, device_values, state_prefix="trigger"):
    """
    Evalúa un bloque de condicionales v2 (trigger o auto_resolve).

    El estado por condicional se guarda bajo la clave
    `(state_prefix, rule.id, gi, ci)`, de modo que el bloque de
    disparo y el de auto-resolución mantienen estados independientes.

    Args:
        rule: instancia de AlertRule.
        groups: lista de grupos v2 (de `conditionals` o
            `auto_resolve_conditionals`).
        device_values: dict {device_id: {metric: value}}.
        state_prefix: "trigger" para disparo, "auto" para auto-resolución.

    Returns:
        tuple:
          - final_ready (bool): resultado combinado del bloque.
          - all_conds_flat (list): aplanado de condicionales.
          - all_values_flat (list): valores observados correspondientes.
          - cond_ready_flat (list): bool por condicional (cumplió duración).
    """
    if not groups:
        return False, [], [], []

    # Cargar instancias de Device una sola vez.
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
    cond_ready_flat = []

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

            # Estado por (prefix, rule, gi, ci)
            key = (state_prefix, rule.id, gi, ci)
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

        # Combinar condicionales del grupo (izquierda a derecha por gap).
        operators = g.get("operators") or []
        if not isinstance(operators, list) or len(operators) != len(cond_ready) - 1:
            operators = ["AND"] * max(0, len(cond_ready) - 1)

        g_ready = cond_ready[0]
        for i in range(1, len(cond_ready)):
            op = operators[i - 1] if i - 1 < len(operators) else "AND"
            g_ready = _apply_logic(op, g_ready, cond_ready[i])

        # Aplicar NOT del grupo.
        if g.get("negate", False):
            g_ready = not g_ready

        group_ready.append(g_ready)
        cond_ready_flat.extend(cond_ready)

    if not group_ready:
        return False, all_conds_flat, all_values_flat, cond_ready_flat

    # Combinar grupos entre sí (izquierda a derecha).
    final_ready = group_ready[0]
    for i in range(1, len(group_ready)):
        logic = groups[i].get("logic") or "AND"
        final_ready = _apply_logic(logic, final_ready, group_ready[i])

    return final_ready, all_conds_flat, all_values_flat, cond_ready_flat


# ============================================================
# EVALUACIÓN DE UNA REGLA
# ============================================================
def _evaluate_rule(rule, device_values):
    """
    Evalúa una regla completa: bloque de disparo + bloque de
    auto-resolución (si aplica).

    Lógica:
      1. Evaluar bloque de disparo (`conditionals`).
      2. Si trigger cumple:
         · `fire_once` / `mark_as_resolved` → dedupe.
         · Crear alerta.
         · Marcar `_rule_fired[rule.id] = True`.
      3. Si trigger NO cumple:
         · Si `enable_auto_resolve=True` Y hay condicionales de
           auto-resolución → evaluar ese bloque; si cumple, resolver.
         · En caso contrario → resolver (comportamiento clásico).
         · Limpiar `_rule_fired[rule.id]`.
    """
    if rule.skip_on_startup and _is_monitor_warming_up():
        return

    groups = rule.get_groups()
    if not groups:
        return

    # --- Evaluar bloque de disparo ---
    final_ready, all_conds_flat, all_values_flat, cond_ready = _evaluate_block(
        rule, groups, device_values, state_prefix="trigger",
    )

    # ------------------------------------------------------------
    # Disparar / auto-resolver
    # ------------------------------------------------------------
    if final_ready:
        # fire_once: ya disparó en este periodo de violación.
        if rule.fire_once and _rule_fired.get(rule.id):
            return

        _create_alert_for_rule(
            rule, groups, all_conds_flat, all_values_flat, cond_ready,
        )

        with _rule_lock:
            _rule_fired[rule.id] = True
    else:
        # Decidir si resolver: por auto-resolución o por comportamiento clásico.
        should_resolve = False

        if rule.has_auto_resolve:
            # Hay bloque de auto-resolución habilitado con condicionales:
            # evaluar por separado con su propio estado.
            auto_groups = rule.get_auto_resolve_groups()
            auto_final, _, _, _ = _evaluate_block(
                rule, auto_groups, device_values, state_prefix="auto",
            )
            should_resolve = auto_final
        else:
            # Comportamiento clásico: resolver cuando trigger deja de cumplirse.
            should_resolve = True

        if should_resolve:
            try:
                _resolve_all_alerts_for_rule(rule)
            except Exception as e:
                log.error(
                    "Error auto-resolviendo alertas de '%s': %s",
                    rule.name, e,
                )

            # Resetear tracking de disparo.
            with _rule_lock:
                _rule_fired.pop(rule.id, None)


# ============================================================
# EVALUACIÓN DE MÚLTIPLES MÉTRICAS
# ============================================================
def evaluate_metrics(device, metrics: dict):
    """
    Evalúa las reglas que contienen este device en algún condicional
    (de disparo) contra las métricas dadas.

    A partir de v4, el índice `by_device_metric` se construye solo con
    los condicionales de DISPARO. Los condicionales de auto-resolución
    pueden incluir el mismo device u otros; sus valores se leen del
    caché de `_cond_states` (con TTL).

    Args:
        device: instancia de Device.
        metrics: dict {metric: value} de este device.
    """
    if not metrics:
        return

    metric_names = [k for k, v in metrics.items() if v is not None]
    if not metric_names:
        return

    # Obtener índice de reglas (construido solo con conditionals de disparo).
    index = _get_rules_index()
    by_dm = index["by_device_metric"]
    by_id = index["all_rules_by_id"]

    # Encontrar reglas que tocan (device, metric) para al menos una métrica.
    matching_rule_ids = set()
    for metric_name in metric_names:
        key = (device.id, metric_name)
        for rule in by_dm.get(key, []):
            matching_rule_ids.add(rule.id)

    if not matching_rule_ids:
        return

    now = time.time()

    # Evaluar cada regla.
    for rule_id in matching_rule_ids:
        rule = by_id.get(rule_id)
        if not rule or not rule.enabled:
            continue

        try:
            device_values = {device.id: metrics}

            # Leer valores cacheados de otros devices con TTL.
            # Se revisan AMBOS bloques (trigger y auto) para poblar
            # `device_values` con todo lo que la regla pueda necesitar
            # al evaluar el bloque de auto-resolución.
            for prefix, groups in (
                ("trigger", rule.get_groups()),
                ("auto", rule.get_auto_resolve_groups()),
            ):
                for gi, group in enumerate(groups):
                    for ci, cond in enumerate(group.get("conditionals", [])):
                        did = cond.get("device_id")
                        if did == device.id:
                            continue
                        if (
                            did in device_values
                            and cond.get("metric") in device_values[did]
                        ):
                            continue
                        key = (prefix, rule.id, gi, ci)
                        with _rule_lock:
                            st = _cond_states.get(key)
                        if st and st.get("last_value") is not None:
                            last_seen = st.get("last_seen", 0)
                            age = now - last_seen
                            if age <= CACHE_TTL_SEC:
                                # Valor fresco: usar.
                                device_values.setdefault(did, {})
                                device_values[did][cond.get("metric")] = st["last_value"]
                            else:
                                # Valor stale: tratar como ausente (None).
                                log.debug(
                                    "Regla '%s' [%s]: valor cacheado stale (%.0fs) "
                                    "para device=%s metric=%s",
                                    rule.name, prefix, age, did, cond.get("metric"),
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
    """
    Compatibilidad: evalúa una sola métrica.

    Mantiene la firma original para no romper llamadores existentes.
    """
    evaluate_metrics(device, {metric: value})