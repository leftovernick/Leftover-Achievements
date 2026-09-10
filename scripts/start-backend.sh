#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
PYTHON="$VENV_DIR/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "Error: Python virtual environment is missing or incomplete: $VENV_DIR" >&2
  echo "Run $PROJECT_ROOT/scripts/install-pi.sh first." >&2
  exit 1
fi

cd "$PROJECT_ROOT"
# Activating keeps manually launched and systemd-launched environments identical.
source "$VENV_DIR/bin/activate"

# The programmatic server signals long-lived SSE streams before Uvicorn starts
# waiting for connections and enforces an eight-second graceful-shutdown ceiling.
exec "$PYTHON" launcher.py
