#!/usr/bin/env bash
# ============================================================
# instalador.sh - Instalador completo de Comfutech Monitor (Linux)
#
# Pasos:
#   1. Verificar permisos de root.
#   2. Detectar la distribución e instalar dependencias del sistema
#      (build-essential, python3-dev, libmysqlclient-dev, etc.).
#   3. Detectar Python (>=3.11). Si no está, compilar Python 3.15.1.
#   4. Crear el entorno virtual en bin/python_local.
#   5. Instalar las dependencias de requeriments.txt.
#   6. Instalar los servicios systemd.
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
# 2. Detectar la distribución e instalar dependencias del sistema
# ------------------------------------------------------------
#    mysqlclient requiere compilador C, headers de Python y la
#    librería de desarrollo de MySQL/MariaDB. pkg-config y libssl-dev
#    también son necesarios en muchos casos.
# ------------------------------------------------------------
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        echo "${ID:-unknown}"
    else
        echo "unknown"
    fi
}

install_system_deps() {
    local distro
    distro=$(detect_distro)
    echo "  Distribución detectada: $distro"
    echo "  Instalando dependencias del sistema (build tools, Python dev, MySQL dev)..."

    case "$distro" in
        ubuntu|debian|linuxmint|pop)
            apt-get update -y
            apt-get install -y \
                build-essential \
                python3-dev \
                default-libmysqlclient-dev \
                pkg-config \
                libssl-dev \
                zlib1g-dev \
                libffi-dev \
                wget \
                curl \
                git \
                libjpeg-dev \
                libxml2-dev \
                libxslt1-dev \
                libpq-dev \
                sqlite3 \
                libsqlite3-dev \
                mariadb-client \
                mariadb-server \
                nginx \
                logrotate \
                systemd
            ;;
        rhel|centos|fedora|rocky|almalinux)
            if command -v dnf &>/dev/null; then
                dnf install -y \
                    gcc gcc-c++ make \
                    python3-devel \
                    mariadb-devel \
                    pkgconfig \
                    openssl-devel \
                    zlib-devel \
                    libffi-devel \
                    wget \
                    curl \
                    git \
                    libjpeg-turbo-devel \
                    libxml2-devel \
                    libxslt-devel \
                    postgresql-devel \
                    sqlite \
                    sqlite-devel \
                    mariadb \
                    mariadb-server \
                    nginx \
                    logrotate \
                    systemd
            else
                yum install -y \
                    gcc gcc-c++ make \
                    python3-devel \
                    mariadb-devel \
                    pkgconfig \
                    openssl-devel \
                    zlib-devel \
                    libffi-devel \
                    wget \
                    curl \
                    git \
                    libjpeg-turbo-devel \
                    libxml2-devel \
                    libxslt-devel \
                    postgresql-devel \
                    sqlite \
                    sqlite-devel \
                    mariadb \
                    mariadb-server \
                    nginx \
                    logrotate \
                    systemd
            fi
            ;;
        arch|manjaro)
            pacman -Sy --noconfirm \
                base-devel \
                python \
                mariadb-libs \
                pkgconf \
                openssl \
                zlib \
                libffi \
                wget \
                curl \
                git \
                libjpeg-turbo \
                libxml2 \
                libxslt \
                postgresql-libs \
                sqlite \
                mariadb \
                nginx \
                logrotate \
                systemd
            ;;
        *)
            echo "[ADVERTENCIA] Distribución '$distro' no reconocida."
            echo "  Asegúrate de tener instalados: build-essential, python3-dev,"
            echo "  libmysqlclient-dev (o mariadb-devel), pkg-config, libssl-dev."
            ;;
    esac
}

install_system_deps

# --- Verificar que mysql_config esté disponible ---
if ! command -v mysql_config &>/dev/null; then
    echo "[ERROR] 'mysql_config' no está en el PATH."
    echo "  Esto indica que las librerías de desarrollo de MySQL/MariaDB"
    echo "  no se instalaron correctamente. Revisa los mensajes anteriores."
    exit 1
fi
echo "  mysql_config encontrado: $(command -v mysql_config)"

# ------------------------------------------------------------
# 3. Detectar Python
# ------------------------------------------------------------
PYTHON_CMD=""
PYTHON_VERSION=""

if command -v python3 &>/dev/null; then
    PYTHON_VERSION="$(python3 --version 2>&1 | awk '{print $2}')"
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

    # Dependencias de compilación (ya instaladas en el paso 2, pero por si acaso)
    if command -v apt-get &>/dev/null; then
        apt-get install -y build-essential zlib1g-dev libssl-dev libbz2-dev \
            libreadline-dev libsqlite3-dev libffi-dev liblzma-dev \
            libncurses5-dev libgdbm-dev tk-dev
    elif command -v dnf &>/dev/null; then
        dnf install -y gcc gcc-c++ make zlib-devel openssl-devel bzip2-devel \
            readline-devel sqlite-devel libffi-devel xz-devel ncurses-devel \
            gdbm-devel tk-devel
    elif command -v pacman &>/dev/null; then
        pacman -S --noconfirm base-devel zlib openssl bzip2 readline sqlite libffi xz ncurses gdbm tk
    fi

    PYTHON_TGZ="Python-3.15.1.tgz"
    PYTHON_URL="https://www.python.org/ftp/python/3.15.1/Python-3.15.1.tgz"
    echo "  Descargando $PYTHON_URL ..."
    wget -q "$PYTHON_URL"
    tar xf "$PYTHON_TGZ"
    cd "Python-3.15.1"
    echo "  Configurando y compilando (esto puede tardar varios minutos)..."
    ./configure --enable-optimizations --prefix=/usr/local
    make -j"$(nproc)"
    make altinstall
    cd "$PROJECT_ROOT"
    rm -rf "Python-3.15.1" "$PYTHON_TGZ"

    PYTHON_CMD="python3.15"
    PYTHON_VERSION="3.15.1"
    echo "  Python 3.15.1 instalado correctamente."
fi

# ------------------------------------------------------------
# 4. Crear entorno virtual en bin/python_local
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
# 5. Instalar dependencias
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
# 6. Instalar servicios systemd
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