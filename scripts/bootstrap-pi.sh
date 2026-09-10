#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${LEFTOVER_GITHUB_REPOSITORY:-leftovernick/Leftover-Achievements}"
API_URL="https://api.github.com/repos/$REPOSITORY/releases/latest"
INSTALL_USER="${SUDO_USER:-$(id -un)}"
INSTALL_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
INSTALL_ROOT="$INSTALL_HOME/.local/share/LeftoverAchievements"
DATA_DIR="$INSTALL_ROOT/data"

if [[ "$(id -u)" -eq 0 || "$INSTALL_USER" == root ]]; then
  echo "Error: run this bootstrap as the normal Raspberry Pi user, not with sudo." >&2
  exit 1
fi
if [[ "$(uname -m)" != aarch64 ]]; then
  echo "Error: the Raspberry Pi ARM64 package requires aarch64 Raspberry Pi OS." >&2
  exit 1
fi
if [[ ! -r /proc/device-tree/model ]] || ! grep -aq "Raspberry Pi" /proc/device-tree/model; then
  echo "Error: this bootstrap is only supported on Raspberry Pi hardware." >&2
  exit 1
fi

echo "Installing bootstrap prerequisites ..."
sudo apt-get update
sudo apt-get install -y ca-certificates curl python3 python3-venv chromium

TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/leftover-bootstrap.XXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT
RELEASE_JSON="$TEMP_DIR/release.json"
curl --fail --location --retry 3 --silent --show-error \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  "$API_URL" -o "$RELEASE_JSON"

INSTALLER="$TEMP_DIR/pi_package.py"
curl --fail --location --retry 3 --silent --show-error \
  "https://raw.githubusercontent.com/$REPOSITORY/main/scripts/pi_package.py" \
  -o "$INSTALLER"
readarray -t RELEASE_DETAILS < <(python3 "$INSTALLER" select "$RELEASE_JSON")
VERSION="${RELEASE_DETAILS[0]}"
ASSET_NAME="${RELEASE_DETAILS[1]}"
ASSET_URL="${RELEASE_DETAILS[2]}"
ARCHIVE="$TEMP_DIR/$ASSET_NAME"

echo "Downloading $ASSET_NAME ..."
curl --fail --location --retry 3 --silent --show-error "$ASSET_URL" -o "$ARCHIVE"
[[ -s "$ARCHIVE" ]] || { echo "Error: Pi release download is empty." >&2; exit 1; }
curl --fail --location --retry 3 --silent --show-error \
  "https://raw.githubusercontent.com/$REPOSITORY/$VERSION/scripts/pi_package.py" \
  -o "$INSTALLER"

python3 "$INSTALLER" validate "$ARCHIVE" "$VERSION"
python3 "$INSTALLER" stage "$ARCHIVE" "$VERSION" "$INSTALL_ROOT"

for legacy in "$INSTALL_HOME/Leftover-Achievements" "$INSTALL_HOME/LeftoverAchievements"; do
  if [[ -d "$legacy" && "$legacy" != "$INSTALL_ROOT/app/current" ]]; then
    echo "Migrating persistent data from $legacy ..."
    python3 "$INSTALLER" migrate-data "$legacy" "$DATA_DIR"
  fi
done
mkdir -p "$DATA_DIR/audio" "$DATA_DIR/logs"
[[ -e "$DATA_DIR/.env" ]] || install -m 0600 /dev/null "$DATA_DIR/.env"
python3 "$INSTALLER" activate "$INSTALL_ROOT" "$VERSION"

CURRENT="$INSTALL_ROOT/app/current"
sudo "$CURRENT/scripts/configure-pi-boot-branding.sh" enable
sudo "$CURRENT/scripts/configure-pi-appliance-session.sh" enable "$INSTALL_USER" "$CURRENT"
sudo install -m 0755 "$CURRENT/scripts/pi-privileged-helper.sh" \
  /usr/local/sbin/leftover-achievements-migrate
sudo /usr/local/sbin/leftover-achievements-migrate install "$INSTALL_USER"
sudo systemctl restart leftover-achievements.service

echo
echo "LeftoverAchievements installed."
echo
echo "Dashboard:"
echo "http://$(hostname).local:8000/"
echo
echo "Reboot to start appliance mode."
