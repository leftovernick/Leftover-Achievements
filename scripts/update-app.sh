#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${1:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
VENV_DIR="$PROJECT_ROOT/.venv"
STATUS_FILE="$PROJECT_ROOT/.update-status"
SERVICE_NAME="leftover-achievements.service"

set_phase() {
  printf '%s\n' "$1" > "$STATUS_FILE"
}

abort_update() {
  set_phase failed
  echo "Error: $1" >&2
  exit 1
}

fail_update() {
  status=$?
  set_phase failed
  echo "Update failed near line ${BASH_LINENO[0]} (exit ${status})." >&2
  exit "$status"
}
trap fail_update ERR

echo "[$(date --iso-8601=seconds)] Preparing application update."
set_phase preparing
cd "$PROJECT_ROOT"

if [[ "$(git branch --show-current)" != "main" ]]; then
  abort_update "application updates require the main branch."
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  abort_update "tracked local changes are present; refusing to update."
fi
if ! sudo -n -l /usr/bin/systemctl restart "$SERVICE_NAME" >/dev/null 2>&1; then
  abort_update "the service user is not permitted to restart $SERVICE_NAME; install the provided sudoers rule."
fi

git fetch --quiet origin main
if ! git merge-base --is-ancestor HEAD origin/main; then
  abort_update "local main has diverged from origin/main; refusing to update."
fi
if [[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]]; then
  abort_update "no application update is available."
fi

set_phase installing
echo "Fast-forwarding to origin/main."
git merge --ff-only origin/main

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  abort_update "expected virtual environment at $VENV_DIR."
fi
echo "Installing Python requirements."
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_ROOT/requirements.txt"

set_phase restarting
echo "Update installed successfully; restarting $SERVICE_NAME."
sudo -n /usr/bin/systemctl restart "$SERVICE_NAME"
