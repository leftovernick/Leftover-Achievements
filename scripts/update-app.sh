#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${1:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
TARGET_TAG="${2:-}"
ASSET_URL="${3:-}"
INSTALL_ROOT="${LEFTOVER_INSTALL_ROOT:-$HOME/.local/share/LeftoverAchievements}"
DATA_DIR="${LEFTOVER_DATA_DIR:-$INSTALL_ROOT/data}"
STATUS_FILE="$DATA_DIR/update-status"
SERVICE_NAME=leftover-achievements.service
PACKAGE_TOOL="$PROJECT_ROOT/scripts/pi_package.py"

mkdir -p "$DATA_DIR"
set_phase() { printf '%s\n' "$1" > "$STATUS_FILE"; }
abort_update() { set_phase failed; echo "Error: $1" >&2; exit 1; }
fail_update() {
  status=$?
  set_phase failed
  echo "Package update failed near line ${BASH_LINENO[0]} (exit ${status}). The previous release remains available." >&2
  exit "$status"
}
trap fail_update ERR

[[ "$TARGET_TAG" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]] || abort_update "a stable vX.Y.Z release tag is required."
EXPECTED_ASSET="LeftoverAchievements-Pi-arm64-$TARGET_TAG.tar.gz"
[[ "$ASSET_URL" == https://github.com/*/releases/download/*/"$EXPECTED_ASSET" ]] || abort_update "the Pi release asset URL is invalid."
[[ -f "$PACKAGE_TOOL" ]] || abort_update "the Raspberry Pi package installer is missing."
[[ "$(uname -m)" == aarch64 ]] || abort_update "Pi package updates require aarch64."
sudo -n -l /usr/local/sbin/leftover-achievements-migrate apply >/dev/null 2>&1 || abort_update "the narrow system migration helper is not installed."

TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/leftover-update.XXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT
ARCHIVE="$TEMP_DIR/$EXPECTED_ASSET"

set_phase downloading
echo "Downloading Raspberry Pi release $TARGET_TAG."
curl --fail --location --retry 3 --silent --show-error "$ASSET_URL" -o "$ARCHIVE"
[[ -s "$ARCHIVE" ]] || abort_update "the downloaded release package is empty."

set_phase validating
echo "Validating package structure, platform, and embedded version."
"$PROJECT_ROOT/.venv/bin/python" "$PACKAGE_TOOL" validate "$ARCHIVE" "$TARGET_TAG"

set_phase preparing
echo "Preparing versioned release directory."
set_phase installing
echo "Installing release dependencies in the staged directory."
"$PROJECT_ROOT/.venv/bin/python" "$PACKAGE_TOOL" stage "$ARCHIVE" "$TARGET_TAG" "$INSTALL_ROOT"

CURRENT_LINK="$INSTALL_ROOT/app/current"
PREVIOUS_TARGET="$(readlink "$CURRENT_LINK" 2>/dev/null || true)"
PREVIOUS_VERSION="${PREVIOUS_TARGET##*/}"
"$PROJECT_ROOT/.venv/bin/python" "$PACKAGE_TOOL" activate "$INSTALL_ROOT" "$TARGET_TAG"

set_phase applying
echo "Applying vetted LeftoverAchievements system configuration."
if ! sudo -n /usr/local/sbin/leftover-achievements-migrate apply; then
  if [[ "$PREVIOUS_VERSION" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    "$INSTALL_ROOT/app/releases/$TARGET_TAG/.venv/bin/python" \
      "$INSTALL_ROOT/app/releases/$TARGET_TAG/scripts/pi_package.py" \
      activate "$INSTALL_ROOT" "$PREVIOUS_VERSION"
  fi
  abort_update "system migration failed; restored the previous active release."
fi

set_phase restarting
echo "Release activated successfully; restarting $SERVICE_NAME."
if ! sudo -n /usr/bin/systemctl restart "$SERVICE_NAME"; then
  if [[ "$PREVIOUS_VERSION" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    "$INSTALL_ROOT/app/releases/$TARGET_TAG/.venv/bin/python" \
      "$INSTALL_ROOT/app/releases/$TARGET_TAG/scripts/pi_package.py" \
      activate "$INSTALL_ROOT" "$PREVIOUS_VERSION"
    sudo -n /usr/local/sbin/leftover-achievements-migrate apply || true
    sudo -n /usr/bin/systemctl restart "$SERVICE_NAME" || true
  fi
  abort_update "service restart failed; restored the previous active release."
fi
