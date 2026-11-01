#!/usr/bin/env bash
# ============================================================
# _detect_venv.sh - Detecta el entorno virtual del proyecto
# Uso: source _detect_venv.sh
# Exporta: PYTHON_EXE, VENV_NAME
# Devuelve 1 si no lo encuentra.
# ============================================================

PYTHON_EXE=""
VENV_NAME=""

# Si no está definido PROJECT_ROOT, se asume que el script está en scripts/linux
if [[ -z "${PROJECT_ROOT:-}" ]]; then
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

# --- Buscar el venv en bin/python_local ---
if [[ -x "$PROJECT_ROOT/bin/python_local/bin/python" ]]; then
    PYTHON_EXE="$PROJECT_ROOT/bin/python_local/bin/python"
    VENV_NAME="bin/python_local"
    export PYTHON_EXE VENV_NAME
    return 0 2>/dev/null || exit 0
fi

# --- Fallback: buscar en la raíz (compatibilidad) ---
for V in python_local venv_django venv .venv env; do
    if [[ -x "$PROJECT_ROOT/$V/bin/python" ]]; then
        PYTHON_EXE="$PROJECT_ROOT/$V/bin/python"
        VENV_NAME="$V"
        export PYTHON_EXE VENV_NAME
        return 0 2>/dev/null || exit 0
    fi
done

# --- No encontrado ---
echo
echo "[ERROR] No se encontró el entorno virtual en:"
echo "        $PROJECT_ROOT/bin/python_local"
echo
echo "        Ejecuta primero: sudo ./instalador.sh"
echo
return 1 2>/dev/null || exit 1