#!/usr/bin/env bash
# ============================================================
# install_services.sh - Instala los servicios systemd
# ============================================================
set -euo pipefail

# --- Detectar raíz del proyecto ---
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "============================================================"
echo "  Instalador de servicios Comfutech"
echo "============================================================"
echo "  Raíz del proyecto: $PROJECT_ROOT"
echo

# --- Verificar permisos de root ---
if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] Este script debe ejecutarse como root (sudo)."
    exit 1
fi

# --- Detectar Python del venv ---
source "$PROJECT_ROOT/scripts/linux/_detect_venv.sh"
if [[ $? -ne 0 ]]; then
    exit 1
fi

echo "  Python: $PYTHON_EXE"
echo "  Venv:   $VENV_NAME"
echo

# --- Verificar manage.py ---
if [[ ! -f "$PROJECT_ROOT/manage.py" ]]; then
    echo "[ERROR] No se encontró manage.py en: $PROJECT_ROOT"
    exit 1
fi

# --- Crear carpeta de logs ---
mkdir -p "$PROJECT_ROOT/logs"

# --- Detener y eliminar servicios previos si existen ---
for SVC in ComfutechDjango ComfutechMonitor; do
    systemctl stop "$SVC" 2>/dev/null || true
    systemctl disable "$SVC" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SVC}.service"
done
systemctl daemon-reload

# ============================================================
# SERVICIO 1: ComfutechDjango (Waitress)
# ============================================================
cat > /etc/systemd/system/ComfutechDjango.service <<EOF
[Unit]
Description=Comfutech Django (Waitress)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_ROOT
ExecStart=$VENV_PYTHON -m waitress --listen=0.0.0.0:8000 --threads=16 sistema.wsgi:application
Restart=always
RestartSec=5
StandardOutput=append:$PROJECT_ROOT/logs/django_out.log
StandardError=append:$PROJECT_ROOT/logs/django_err.log

[Install]
WantedBy=multi-user.target
EOF

# ============================================================
# SERVICIO 2: ComfutechMonitor
# ============================================================
cat > /etc/systemd/system/ComfutechMonitor.service <<EOF
[Unit]
Description=Comfutech Monitor de Red
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_ROOT
ExecStart=$VENV_PYTHON manage.py run_monitor
Restart=always
RestartSec=10
StandardOutput=append:$PROJECT_ROOT/logs/monitor_out.log
StandardError=append:$PROJECT_ROOT/logs/monitor_err.log

[Install]
WantedBy=multi-user.target
EOF

# --- Recargar systemd, habilitar y arrancar ---
echo "=== Recargando systemd ==="
systemctl daemon-reload

echo "=== Habilitando servicios ==="
systemctl enable ComfutechDjango ComfutechMonitor

echo "=== Arrancando servicios ==="
systemctl start ComfutechDjango ComfutechMonitor

sleep 2
echo
echo "=== Estado final ==="
systemctl status ComfutechDjango --no-pager || true
systemctl status ComfutechMonitor --no-pager || true