#!/usr/bin/env bash
# ============================================================
# deploy.sh - Detiene servicios, migra y reinicia
# ============================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/linux/_detect_venv.sh"
if [[ $? -ne 0 ]]; then exit 1; fi

echo "=== Deteniendo servicios ==="
systemctl stop ComfutechDjango ComfutechMonitor

echo "=== Aplicando migraciones ==="
"$PYTHON_EXE" manage.py migrate

echo "=== Recolectando estáticos ==="
"$PYTHON_EXE" manage.py collectstatic --no-input

echo "=== Reiniciando servicios ==="
systemctl start ComfutechDjango ComfutechMonitor

sleep 2
systemctl status ComfutechDjango --no-pager || true
systemctl status ComfutechMonitor --no-pager || true