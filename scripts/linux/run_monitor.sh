#!/usr/bin/env bash
# ============================================================
# run_monitor.sh - Arranca el monitor (modo manual)
# ============================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/scripts/linux/_detect_venv.sh"
if [[ $? -ne 0 ]]; then exit 1; fi

"$PYTHON_EXE" manage.py run_monitor