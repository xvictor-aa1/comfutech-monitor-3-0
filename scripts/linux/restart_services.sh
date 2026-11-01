#!/usr/bin/env bash
# ============================================================
# restart_services.sh - Reinicia ambos servicios
# ============================================================
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] Ejecutar como root (sudo)."
    exit 1
fi

echo "=== Reiniciando servicios ==="
systemctl restart ComfutechDjango ComfutechMonitor

sleep 2
systemctl status ComfutechDjango --no-pager || true
systemctl status ComfutechMonitor --no-pager || true