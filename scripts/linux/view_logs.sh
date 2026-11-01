#!/usr/bin/env bash
# ============================================================
# view_logs.sh - Muestra los últimos logs de los servicios
# ============================================================
set -euo pipefail

echo "=== Django (últimas 30 líneas) ==="
journalctl -u ComfutechDjango -n 30 --no-pager || echo "  (sin log)"

echo
echo "=== Monitor (últimas 30 líneas) ==="
journalctl -u ComfutechMonitor -n 30 --no-pager || echo "  (sin log)"