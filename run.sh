#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_BIN="$ROOT_DIR/.venv/bin"
PYTHON_BIN=""
MIN_PYTHON="3.10"

is_compatible_python() {
    "$1" - <<'PY' >/dev/null 2>&1
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY
}

# Prefer the virtualenv interpreter, then fall back to system Python.
for candidate in \
    "$VENV_BIN/python3.12" \
    "$VENV_BIN/python3.11" \
    "$VENV_BIN/python3.10" \
    "$VENV_BIN/python3" \
    "$VENV_BIN/python" \
    python3.12 \
    python3.11 \
    python3.10 \
    python3 \
    python; do
    if { [ -x "$candidate" ] || command -v "$candidate" >/dev/null 2>&1; } && is_compatible_python "$candidate"; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "Python interpreter not found or too old. Please install Python >= $MIN_PYTHON." >&2
    exit 1
fi


# Uncomment the scenario you want to run.
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/random_wp_test_bounded_plugin_ex.json"
"$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/random_wp_test_bounded.json"
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/random_wp_test_unbounded.json"
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/spin_model_test_selection_bounded.json"
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/spin_model_test_flocking_bounded.json"
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/spin_model_test_flocking_unbounded.json"
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/random_wp_minimal_setting.json"
