#!/bin/bash
set -e

MIN_PYTHON="3.10"

is_compatible_python() {
    "$1" - <<'PY' >/dev/null 2>&1
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY
}

# Pick an available Python 3 interpreter (3.10+).
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && is_compatible_python "$candidate"; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "Python interpreter not found or too old. Please install Python >= $MIN_PYTHON." >&2
    exit 1
fi

# Ensure ensurepip is available (python3.X-venv package on Debian/Ubuntu).
if ! "$PYTHON_BIN" -m ensurepip --version >/dev/null 2>&1; then
    echo "The selected interpreter ($PYTHON_BIN) lacks ensurepip. Install the matching python3-venv package (e.g., python3.12-venv) or use an interpreter with ensurepip available." >&2
    exit 1
fi

"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
