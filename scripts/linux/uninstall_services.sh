#!/usr/bin/env bash
# ============================================================
# uninstall_services.sh - Desinstala los servicios systemd
# ============================================================
set -euo pipefail

echo "============================================================"
echo "  Desinstalador de servicios Comfutech"
echo "============================================================"
echo

if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] Este script debe ejecutarse como root (sudo)."
    exit 1
fi

read -rp "¿Eliminar los servicios Comfutech? [s/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[sS]$ ]]; then
    echo "Cancelado."
    exit 0
fi

for SVC in ComfutechDjango ComfutechMonitor; do
    echo "=== Deteniendo y eliminando $SVC ==="
    systemctl stop "$SVC" 2>/dev/null || true
    systemctl disable "$SVC" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SVC}.service"
done

systemctl daemon-reload

echo
echo "=== Verificación ==="
for SVC in ComfutechDjango ComfutechMonitor; do
    if systemctl list-unit-files | grep -q "^${SVC}.service"; then
        echo "  $SVC: AÚN EXISTE (revisa manualmente)"
    else
        echo "  $SVC: ELIMINADO"
    fi
done

echo
echo "Desinstalación completa."