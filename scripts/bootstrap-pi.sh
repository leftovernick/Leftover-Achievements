#!/usr/bin/env bash
set -Eeuo pipefail

NO_REBOOT="${LEFTOVER_ACHIEVEMENTS_NO_REBOOT:-0}"
REBOOT_DELAY_SECONDS="${LEFTOVER_REBOOT_DELAY_SECONDS:-10}"
TEMP_DIR=""
CURRENT=""
INSTALL_USER=""

usage() {
  echo "Usage: bootstrap-pi.sh [--no-reboot]"
}

parse_arguments() {
  while (( $# > 0 )); do
    case "$1" in
      --no-reboot) NO_REBOOT=1 ;;
      -h|--help) usage; return 2 ;;
      *) echo "Error: unknown option: $1" >&2; usage >&2; return 2 ;;
    esac
    shift
  done
  [[ "$NO_REBOOT" == 0 || "$NO_REBOOT" == 1 ]] || {
    echo "Error: LEFTOVER_ACHIEVEMENTS_NO_REBOOT must be 0 or 1." >&2
    return 2
  }
  [[ "$REBOOT_DELAY_SECONDS" =~ ^[0-9]+$ ]] || {
    echo "Error: reboot delay must be a non-negative integer." >&2
    return 2
  }
}

cleanup_bootstrap_temp() {
  if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
    rm -rf -- "$TEMP_DIR"
    TEMP_DIR=""
  fi
}

install_leftover_achievements() {
  local repository api_url install_home install_root data_dir
  local release_json installer version asset_name asset_url archive legacy release_selection
  repository="${LEFTOVER_GITHUB_REPOSITORY:-leftovernick/Leftover-Achievements}"
  api_url="https://api.github.com/repos/$repository/releases/latest"
  INSTALL_USER="${SUDO_USER:-$(id -un)}"
  install_home="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
  install_root="$install_home/.local/share/LeftoverAchievements"
  data_dir="$install_root/data"

  if [[ "$(id -u)" -eq 0 || "$INSTALL_USER" == root ]]; then
    echo "Error: run this bootstrap as the normal Raspberry Pi user, not with sudo." >&2
    return 1
  fi
  if [[ "$(uname -m)" != aarch64 ]]; then
    echo "Error: the Raspberry Pi ARM64 package requires aarch64 Raspberry Pi OS." >&2
    return 1
  fi
  if [[ ! -r /proc/device-tree/model ]] || ! grep -aq "Raspberry Pi" /proc/device-tree/model; then
    echo "Error: this bootstrap is only supported on Raspberry Pi hardware." >&2
    return 1
  fi

  echo "Installing bootstrap prerequisites ..."
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl python3 python3-venv chromium

  TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/leftover-bootstrap.XXXXXX")"
  trap cleanup_bootstrap_temp EXIT
  release_json="$TEMP_DIR/release.json"
  curl --fail --location --retry 3 --silent --show-error \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "$api_url" -o "$release_json"

  installer="$TEMP_DIR/pi_package.py"
  curl --fail --location --retry 3 --silent --show-error \
    "https://raw.githubusercontent.com/$repository/main/scripts/pi_package.py" \
    -o "$installer"
  local -a release_details
  release_selection="$(python3 "$installer" select "$release_json")"
  readarray -t release_details <<< "$release_selection"
  version="${release_details[0]}"
  asset_name="${release_details[1]}"
  asset_url="${release_details[2]}"
  archive="$TEMP_DIR/$asset_name"

  echo "Downloading $asset_name ..."
  curl --fail --location --retry 3 --silent --show-error "$asset_url" -o "$archive"
  [[ -s "$archive" ]] || { echo "Error: Pi release download is empty." >&2; return 1; }
  curl --fail --location --retry 3 --silent --show-error \
    "https://raw.githubusercontent.com/$repository/$version/scripts/pi_package.py" \
    -o "$installer"

  python3 "$installer" validate "$archive" "$version"
  python3 "$installer" stage "$archive" "$version" "$install_root"

  for legacy in "$install_home/Leftover-Achievements" "$install_home/LeftoverAchievements"; do
    if [[ -d "$legacy" && "$legacy" != "$install_root/app/current" ]]; then
      echo "Migrating persistent data from $legacy ..."
      python3 "$installer" migrate-data "$legacy" "$data_dir"
    fi
  done
  mkdir -p "$data_dir/audio" "$data_dir/logs"
  [[ -e "$data_dir/.env" ]] || install -m 0600 /dev/null "$data_dir/.env"
  python3 "$installer" activate "$install_root" "$version"

  CURRENT="$install_root/app/current"
  echo "Raspberry Pi boot configuration left unchanged."
  sudo "$CURRENT/scripts/configure-pi-appliance-session.sh" enable "$INSTALL_USER" "$CURRENT"
  sudo install -m 0755 "$CURRENT/scripts/pi-privileged-helper.sh" \
    /usr/local/sbin/leftover-achievements-migrate
  sudo /usr/local/sbin/leftover-achievements-migrate install "$INSTALL_USER"
  sudo systemctl restart leftover-achievements.service
}

validate_installation() {
  echo "Validating backend service and kiosk configuration ..."
  sudo systemctl is-active --quiet leftover-achievements.service
  sudo "$CURRENT/scripts/configure-pi-appliance-session.sh" status "$INSTALL_USER" "$CURRENT"
  curl --fail --silent --show-error --retry 10 --retry-connrefused \
    --retry-delay 1 --max-time 5 http://127.0.0.1:8000/display -o /dev/null
  echo "Backend service and kiosk configuration validated."
}

print_manual_reboot() {
  echo "Installation complete."
  echo "Reboot later with:"
  echo "sudo reboot"
}

AUTO_REBOOT_CANCELLED=0
cancel_auto_reboot() {
  AUTO_REBOOT_CANCELLED=1
}

finish_installation() {
  # All extraction, migration, configuration, validation, and temporary-file
  # cleanup have completed before this function is called.
  sync
  echo
  echo "LeftoverAchievements installation complete."
  echo "Dedicated LeftoverAchievements kiosk session enabled."
  echo "Dashboard: http://$(hostname).local:8000/"

  if [[ "$NO_REBOOT" == 1 ]]; then
    echo "Automatic reboot disabled."
    print_manual_reboot
    return 0
  fi

  echo
  echo "The Raspberry Pi will reboot in $REBOOT_DELAY_SECONDS seconds to start appliance mode."
  echo "Press Ctrl+C to cancel the automatic reboot."

  AUTO_REBOOT_CANCELLED=0
  trap cancel_auto_reboot INT
  local remaining="$REBOOT_DELAY_SECONDS"
  while (( remaining > 0 && AUTO_REBOOT_CANCELLED == 0 )); do
    printf '\rRebooting in %2d seconds... ' "$remaining"
    sleep 1 || AUTO_REBOOT_CANCELLED=1
    remaining=$((remaining - 1))
  done
  trap - INT
  printf '\r%*s\r' 32 ''

  if (( AUTO_REBOOT_CANCELLED )); then
    print_manual_reboot
    return 0
  fi

  echo "Rebooting now."
  sudo reboot
}

run_bootstrap() {
  parse_arguments "$@"
  install_leftover_achievements
  validate_installation
  cleanup_bootstrap_temp
  trap - EXIT
  finish_installation
}

if [[ "${LEFTOVER_BOOTSTRAP_LIBRARY_ONLY:-0}" != 1 ]]; then
  run_bootstrap "$@"
fi
