#!/bin/bash
set -e

# Pick an available Python 3 interpreter (prefers 3.10, then 3.x).
if command -v python3.10 >/dev/null 2>&1; then
    PYTHON_BIN=python3.10
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "Python 3 interpreter not found. Please install Python 3.x." >&2
    exit 1
fi

"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
