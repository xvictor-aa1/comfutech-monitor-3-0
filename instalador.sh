#!/usr/bin/env bash
# ============================================================
# instalador.sh - Instalador completo de Comfutech Monitor (Linux)
#
# Pasos:
#   1. Verificar permisos de root.
#   2. Detectar Python (>=3.11). Si no está, descargar y compilar
#      Python 3.15.1 desde fuente.
#   3. Crear el entorno virtual en bin/python_local.
#   4. Instalar las dependencias de requeriments.txt.
#   5. Instalar los servicios systemd.
# ============================================================
set -euo pipefail

# --- Detectar raíz del proyecto (el script está en la raíz) ---
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "============================================================"
echo "  INSTALADOR DE COMFUTECH MONITOR (Linux)"
echo "============================================================"
echo "  Raíz del proyecto: $PROJECT_ROOT"
echo

# ------------------------------------------------------------
# 1. Verificar permisos de root
# ------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] Este script debe ejecutarse como root (usa sudo)."
    exit 1
fi

# ------------------------------------------------------------
# 2. Detectar Python
# ------------------------------------------------------------
PYTHON_CMD=""
PYTHON_VERSION=""

# Buscar python3
if command -v python3 &>/dev/null; then
    PYTHON_VERSION="$(python3 --version 2>&1 | awk '{print $2}')"
    # Comprobar que sea >= 3.11 (comparación de versiones)
    if printf '%s\n' "3.11" "$PYTHON_VERSION" | sort -V | head -n1 | grep -q "^3.11$"; then
        PYTHON_CMD="python3"
        echo "  Python detectado: $PYTHON_VERSION (comando: python3)"
    fi
fi

if [[ -z "$PYTHON_CMD" ]]; then
    echo
    echo "  Python 3.11+ no encontrado."
    read -rp "  ¿Descargar y compilar Python 3.15.1 desde fuente? (s/N): " RESP
    if [[ ! "$RESP" =~ ^[sS]$ ]]; then
        echo "[ERROR] Python 3.11+ es necesario. Instálalo manualmente y vuelve a ejecutar."
        exit 1
    fi

    # --- Instalar dependencias de compilación (Debian/Ubuntu) ---
    if command -v apt-get &>/dev/null; then
        echo "  Instalando dependencias de compilación..."
        apt-get update -y
        apt-get install -y build-essential zlib1g-dev libssl-dev libbz2-dev \
            libreadline-dev libsqlite3-dev libffi-dev liblzma-dev \
            libncurses5-dev libgdbm-dev tk-dev wget curl
    else
        echo "[ERROR] No se detectó apt-get. Instala las dependencias de compilación manualmente."
        exit 1
    fi

    # --- Descargar y compilar Python 3.15.1 ---
    PYTHON_TGZ="Python-3.15.1.tgz"
    PYTHON_URL="https://www.python.org/ftp/python/3.15.1/Python-3.15.1.tgz"
    echo "  Descargando $PYTHON_URL ..."
    wget -q "$PYTHON_URL"
    tar xf "$PYTHON_TGZ"
    cd "Python-3.15.1"
    echo "  Configurando y compilando (esto puede tardar varios minutos)..."
    ./configure --enable-optimizations --prefix=/usr/local
    make -j"$(nproc)"
    make altinstall   # instala como python3.15, sin reemplazar python3
    cd "$PROJECT_ROOT"
    rm -rf "Python-3.15.1" "$PYTHON_TGZ"

    PYTHON_CMD="python3.15"
    PYTHON_VERSION="3.15.1"
    echo "  Python 3.15.1 instalado correctamente."
fi

# ------------------------------------------------------------
# 3. Crear entorno virtual en bin/python_local
# ------------------------------------------------------------
echo
echo "=== Creando entorno virtual en bin/python_local ==="
mkdir -p "$PROJECT_ROOT/bin"

if [[ -x "$PROJECT_ROOT/bin/python_local/bin/python" ]]; then
    echo "  El entorno virtual ya existe. Se omite la creación."
else
    "$PYTHON_CMD" -m venv "$PROJECT_ROOT/bin/python_local"
    echo "  Entorno virtual creado."
fi

VENV_PYTHON="$PROJECT_ROOT/bin/python_local/bin/python"
VENV_PIP="$PROJECT_ROOT/bin/python_local/bin/pip"

# ------------------------------------------------------------
# 4. Instalar dependencias
# ------------------------------------------------------------
echo
echo "=== Instalando dependencias de requeriments.txt ==="

if [[ ! -f "$PROJECT_ROOT/requeriments.txt" ]]; then
    echo "[ERROR] No se encontró requeriments.txt en la raíz del proyecto."
    exit 1
fi

"$VENV_PIP" install --upgrade pip
"$VENV_PIP" install -r "$PROJECT_ROOT/requeriments.txt"
echo "  Dependencias instaladas correctamente."

# ------------------------------------------------------------
# 5. Instalar servicios systemd
# ------------------------------------------------------------
echo
echo "=== Instalando servicios systemd ==="
bash "$PROJECT_ROOT/scripts/linux/install_services.sh"

echo
echo "============================================================"
echo "  INSTALACIÓN COMPLETA"
echo
echo "  Servicios instalados:"
echo "    - ComfutechDjango  (Waitress en :8000)"
echo "    - ComfutechMonitor (Scheduler de polling)"
echo
echo "  Accede a: http://localhost:8000/"
echo "  Logs:     journalctl -u ComfutechDjango -f"
echo "            journalctl -u ComfutechMonitor -f"
echo "============================================================"