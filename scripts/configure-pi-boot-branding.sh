#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SPLASH_IMAGE="$PROJECT_ROOT/deploy/boot/leftover-achievements-splash.tga"
CONFIG_BEGIN="# BEGIN LeftoverAchievements boot branding"
CONFIG_END="# END LeftoverAchievements boot branding"
ACTION="${1:-enable}"

if [[ -f /boot/firmware/config.txt ]]; then
  BOOT_CONFIG=/boot/firmware/config.txt
elif [[ -f /boot/config.txt ]]; then
  BOOT_CONFIG=/boot/config.txt
else
  BOOT_CONFIG=""
fi

usage() {
  echo "Usage: sudo $0 [enable|disable|status]"
}

require_pi() {
  if [[ ! -r /proc/device-tree/model ]] || ! grep -aq "Raspberry Pi" /proc/device-tree/model; then
    echo "Error: boot branding can only be configured on Raspberry Pi hardware." >&2
    exit 1
  fi
  if [[ -z "$BOOT_CONFIG" ]]; then
    echo "Error: Raspberry Pi boot config was not found in /boot/firmware or /boot." >&2
    exit 1
  fi
}

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Error: this command changes boot files and must be run with sudo." >&2
    exit 1
  fi
}

remove_config_block() {
  local source_file="$1"
  local destination_file="$2"
  awk -v begin="$CONFIG_BEGIN" -v end="$CONFIG_END" '
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    !managed { print }
  ' "$source_file" > "$destination_file"
}

enable_branding() {
  require_root
  if [[ ! -f "$SPLASH_IMAGE" ]]; then
    echo "Error: branded splash asset is missing: $SPLASH_IMAGE" >&2
    exit 1
  fi

  if ! command -v configure-splash >/dev/null 2>&1; then
    echo "Installing Raspberry Pi's supported splash-screen helper ..."
    apt-get update
    apt-get install -y rpi-splash-screen-support
  fi

  local filtered_config new_config
  filtered_config="$(mktemp)"
  new_config="$(mktemp)"
  remove_config_block "$BOOT_CONFIG" "$filtered_config"
  {
    cat "$filtered_config"
    echo
    echo "$CONFIG_BEGIN"
    echo "# Suppress the firmware rainbow screen; the branded kernel splash follows."
    echo "[all]"
    echo "disable_splash=1"
    echo "$CONFIG_END"
  } > "$new_config"
  install -m 0644 "$new_config" "$BOOT_CONFIG"
  rm -f "$filtered_config" "$new_config"

  # This official Raspberry Pi OS tool validates the TGA, updates cmdline.txt,
  # embeds it in the initramfs, and preserves its own cmdline.txt.bak backup.
  configure-splash "$SPLASH_IMAGE"
  echo "LeftoverAchievements boot branding enabled. Reboot to apply it."
}

disable_branding() {
  require_root
  local filtered_config
  filtered_config="$(mktemp)"
  remove_config_block "$BOOT_CONFIG" "$filtered_config"
  install -m 0644 "$filtered_config" "$BOOT_CONFIG"
  rm -f "$filtered_config"

  local cmdline_file
  cmdline_file="$(dirname "$BOOT_CONFIG")/cmdline.txt"
  if [[ -f "$cmdline_file" ]]; then
    local cmdline
    cmdline="$(tr '\r\n' ' ' < "$cmdline_file")"
    cmdline="$(printf '%s' "$cmdline" | sed -E \
      -e 's/(^| )fullscreen_logo=[^ ]*//g' \
      -e 's/(^| )fullscreen_logo_name=[^ ]*//g' \
      -e 's/(^| )vt\.global_cursor_default=[^ ]*//g' \
      -e 's/  +/ /g' -e 's/^ //; s/ $//')"
    [[ " $cmdline " == *" console=tty1 "* ]] || cmdline="$cmdline console=tty1"
    [[ " $cmdline " == *" quiet "* ]] || cmdline="$cmdline quiet"
    printf '%s\n' "$cmdline" | install -m 0644 /dev/stdin "$cmdline_file"
  fi

  rm -f /etc/initramfs-tools/hooks/splash-screen-hook.sh
  if command -v update-initramfs >/dev/null 2>&1; then
    update-initramfs -k all -u
  fi
  echo "LeftoverAchievements boot branding disabled. Reboot to apply it."
}

show_status() {
  if grep -Fqx "$CONFIG_BEGIN" "$BOOT_CONFIG"; then
    echo "LeftoverAchievements firmware splash suppression: enabled"
  else
    echo "LeftoverAchievements firmware splash suppression: disabled"
  fi
  local cmdline_file
  cmdline_file="$(dirname "$BOOT_CONFIG")/cmdline.txt"
  if [[ -f "$cmdline_file" ]] && grep -Eq '(^| )fullscreen_logo=1( |$)' "$cmdline_file"; then
    echo "LeftoverAchievements early boot splash: enabled"
  else
    echo "LeftoverAchievements early boot splash: disabled"
  fi
}

case "$ACTION" in
  enable)
    require_pi
    enable_branding
    ;;
  disable)
    require_pi
    disable_branding
    ;;
  status)
    require_pi
    show_status
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
