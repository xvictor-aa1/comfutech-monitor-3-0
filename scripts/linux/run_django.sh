#!/usr/bin/env bash
# ============================================================
# run_django.sh - Arranca Django con Waitress (modo manual)
# ============================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/linux/_detect_venv.sh"
if [[ $? -ne 0 ]]; then exit 1; fi

"$PYTHON_EXE" -m waitress \
    --listen=0.0.0.0:8000 \
    --threads=16 \
    --channel-timeout=120 \
    sistema.wsgi:application