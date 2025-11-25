#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_BIN="$ROOT_DIR/.venv/bin"
PYTHON_BIN=""

# Prefer the virtualenv interpreter, then fall back to system Python.
for candidate in \
    "$VENV_BIN/python3.10" \
    "$VENV_BIN/python3" \
    "$VENV_BIN/python" \
    python3.10 \
    python3 \
    python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "Python interpreter not found. Please install Python 3.x." >&2
    exit 1
fi

# Uncomment the scenario you want to run.
"$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/random_wp_collision_handshake_demo.json"
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/random_wp_test_bounded.json"
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/random_wp_test_unbounded.json"
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/random_wp_message_cleanup.json"
"$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/spin_model_test_selection_bounded.json"
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/spin_model_test_flocking_bounded.json"
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/spin_model_test_flocking_unbounded.json"
# "$PYTHON_BIN" "$ROOT_DIR/src/main.py" -c "$ROOT_DIR/config/random_wp_hierarchy_bounded.json"