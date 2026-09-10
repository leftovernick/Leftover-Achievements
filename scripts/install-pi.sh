#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Error: this installer is intended for Raspberry Pi OS or another Linux system." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
INSTALL_USER="${SUDO_USER:-$(id -un)}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required. Install it with:" >&2
  echo "  sudo apt update && sudo apt install -y python3 python3-venv" >&2
  exit 1
fi

mkdir -p "$PROJECT_ROOT/database"
chmod +x "$PROJECT_ROOT/scripts/start-backend.sh" \
  "$PROJECT_ROOT/scripts/start-kiosk.sh" \
  "$PROJECT_ROOT/scripts/run-kiosk-session.sh" \
  "$PROJECT_ROOT/scripts/configure-pi-boot-branding.sh" \
  "$PROJECT_ROOT/scripts/configure-pi-appliance-session.sh" \
  "$PROJECT_ROOT/scripts/install-pi.sh" \
  "$PROJECT_ROOT/scripts/update-app.sh"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Creating Python virtual environment at $VENV_DIR ..."
  if ! python3 -m venv "$VENV_DIR"; then
    echo "Error: could not create the virtual environment." >&2
    echo "Install venv support with: sudo apt install -y python3-venv" >&2
    exit 1
  fi
else
  echo "Using existing Python virtual environment at $VENV_DIR."
fi

echo "Installing Python requirements ..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_ROOT/requirements.txt"

if [[ ! -e "$PROJECT_ROOT/.env" ]]; then
  cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
  echo "Created $PROJECT_ROOT/.env from .env.example."
else
  echo "Keeping existing $PROJECT_ROOT/.env unchanged."
fi

missing_packages=()
if ! command -v curl >/dev/null 2>&1; then
  missing_packages+=(curl)
fi
if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
  missing_packages+=(chromium)
fi

echo
echo "Initial application setup is complete."
if (( ${#missing_packages[@]} > 0 )); then
  echo "Install required system packages with:"
  echo "  sudo apt update && sudo apt install -y ${missing_packages[*]}"
else
  echo "Required system commands (curl and Chromium) are available."
fi

if [[ -r /proc/device-tree/model ]] && grep -aq "Raspberry Pi" /proc/device-tree/model; then
  echo
  echo "Raspberry Pi boot configuration left unchanged."
  echo
  echo "Configuring the dedicated LeftoverAchievements labwc session ..."
  sudo "$PROJECT_ROOT/scripts/configure-pi-appliance-session.sh" enable "$INSTALL_USER" "$PROJECT_ROOT"
  echo
  echo "Verifying Raspberry Pi appliance configuration ..."
  sudo "$PROJECT_ROOT/scripts/configure-pi-appliance-session.sh" status "$INSTALL_USER" "$PROJECT_ROOT" || true
fi
echo
echo "Next steps:"
echo "  1. Add your RA_API_KEY to $PROJECT_ROOT/.env"
echo "  2. Install and enable deploy/leftover-achievements.service as documented in README.md"
echo "  3. Install the narrow update sudoers rule documented in README.md"
echo "  4. Reboot the Raspberry Pi (required after session configuration)"
