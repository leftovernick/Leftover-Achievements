#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SPLASH_IMAGE="$PROJECT_ROOT/deploy/boot/leftover-achievements-splash.tga"
CONFIG_BEGIN="# BEGIN LeftoverAchievements boot branding"
CONFIG_END="# END LeftoverAchievements boot branding"
ACTION="${1:-enable}"

detect_boot_files() {
  if [[ -f /boot/firmware/config.txt && -f /boot/firmware/cmdline.txt ]]; then
    BOOT_CONFIG=/boot/firmware/config.txt
    CMDLINE_FILE=/boot/firmware/cmdline.txt
  elif [[ -f /boot/config.txt && -f /boot/cmdline.txt ]]; then
    BOOT_CONFIG=/boot/config.txt
    CMDLINE_FILE=/boot/cmdline.txt
  else
    BOOT_CONFIG=""
    CMDLINE_FILE=""
  fi
}
detect_boot_files

usage() { echo "Usage: sudo $0 [enable|disable|status]"; }

require_pi() {
  if [[ ! -r /proc/device-tree/model ]] || ! grep -aq "Raspberry Pi" /proc/device-tree/model; then
    echo "Error: boot branding can only be configured on Raspberry Pi hardware." >&2
    exit 1
  fi
  if [[ -z "$BOOT_CONFIG" || -z "$CMDLINE_FILE" ]]; then
    echo "Error: a matching Raspberry Pi config.txt/cmdline.txt pair was not found." >&2
    echo "Checked /boot/firmware (current OS) and /boot (legacy OS)." >&2
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
  awk -v begin="$CONFIG_BEGIN" -v end="$CONFIG_END" '
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    !managed { print }
  ' "$1" > "$2"
}

write_appliance_cmdline() {
  local output token
  output=""
  for token in $(tr '\r\n' ' ' < "$CMDLINE_FILE"); do
    case "$token" in
      console=tty1|quiet|splash|loglevel=*|fullscreen_logo=*|fullscreen_logo_name=*|vt.global_cursor_default=*|systemd.show_status=*|rd.systemd.show_status=*) ;;
      *) output+=" $token" ;;
    esac
  done
  output="${output# }"
  output+=" loglevel=3 fullscreen_logo=1 fullscreen_logo_name=logo.tga"
  output+=" vt.global_cursor_default=0 systemd.show_status=false rd.systemd.show_status=false"
  printf '%s\n' "$output" | install -m 0644 /dev/stdin "$CMDLINE_FILE"
}

enable_branding() {
  require_root
  [[ -f "$SPLASH_IMAGE" ]] || { echo "Error: branded splash asset is missing: $SPLASH_IMAGE" >&2; exit 1; }

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
  [[ -e "$BOOT_CONFIG.leftover-achievements.bak" ]] || cp -a "$BOOT_CONFIG" "$BOOT_CONFIG.leftover-achievements.bak"
  [[ -e "$CMDLINE_FILE.leftover-achievements.bak" ]] || cp -a "$CMDLINE_FILE" "$CMDLINE_FILE.leftover-achievements.bak"
  install -m 0644 "$new_config" "$BOOT_CONFIG"
  rm -f "$filtered_config" "$new_config"

  # configure-splash otherwise hard-codes /boot/firmware/cmdline.txt. Let the
  # supported helper validate/install the image and initramfs hook, then update
  # the detected matching cmdline file ourselves.
  configure-splash "$SPLASH_IMAGE" --no-cmdline
  write_appliance_cmdline
  sync
  echo "Boot config: $BOOT_CONFIG"
  echo "Kernel command line: $CMDLINE_FILE"
  echo "LeftoverAchievements boot branding enabled. Reboot to apply it."
}

disable_branding() {
  require_root
  local filtered_config output token
  filtered_config="$(mktemp)"
  remove_config_block "$BOOT_CONFIG" "$filtered_config"
  install -m 0644 "$filtered_config" "$BOOT_CONFIG"
  rm -f "$filtered_config"

  output=""
  for token in $(tr '\r\n' ' ' < "$CMDLINE_FILE"); do
    case "$token" in
      fullscreen_logo=*|fullscreen_logo_name=*|vt.global_cursor_default=*|systemd.show_status=*|rd.systemd.show_status=*|loglevel=3) ;;
      *) output+=" $token" ;;
    esac
  done
  output="${output# }"
  [[ " $output " == *" console=tty1 "* ]] || output+=" console=tty1"
  [[ " $output " == *" quiet "* ]] || output+=" quiet"
  printf '%s\n' "$output" | install -m 0644 /dev/stdin "$CMDLINE_FILE"

  rm -f /etc/initramfs-tools/hooks/splash-screen-hook.sh
  command -v update-initramfs >/dev/null 2>&1 && update-initramfs -k all -u
  echo "LeftoverAchievements boot branding disabled. Reboot to apply it."
}

has_cmdline_token() { grep -Eq "(^| )$1( |$)" "$CMDLINE_FILE"; }

show_status() {
  local failed=0
  echo "Detected boot config: $BOOT_CONFIG"
  echo "Detected kernel command line: $CMDLINE_FILE"
  if grep -Fqx "$CONFIG_BEGIN" "$BOOT_CONFIG" && grep -Eq '^disable_splash=1([[:space:]]|$)' "$BOOT_CONFIG"; then
    echo "[ok] Firmware/Raspberry Pi splash suppression is configured."
  else
    echo "[warning] Firmware splash suppression is not configured."
    failed=1
  fi
  if has_cmdline_token 'fullscreen_logo=1' && has_cmdline_token 'fullscreen_logo_name=logo\.tga'; then
    echo "[ok] LeftoverAchievements early boot logo is configured."
  else
    echo "[warning] LeftoverAchievements early boot logo is not configured."
    failed=1
  fi
  if has_cmdline_token 'loglevel=3' && ! has_cmdline_token 'quiet' && ! has_cmdline_token 'console=tty1' && ! has_cmdline_token 'splash'; then
    echo "[ok] Visual boot output and the stock Plymouth splash are suppressed."
  else
    echo "[warning] Boot output is not configured for the supported fullscreen-logo mode."
    failed=1
  fi
  if [[ -f /lib/firmware/logo.tga && -f /etc/initramfs-tools/hooks/splash-screen-hook.sh ]]; then
    echo "[ok] Branded logo and initramfs hook are installed."
  else
    echo "[warning] Branded initramfs splash files are missing."
    failed=1
  fi
  return "$failed"
}

case "$ACTION" in
  enable) require_pi; enable_branding ;;
  disable) require_pi; disable_branding ;;
  status|verify) require_pi; show_status ;;
  *) usage >&2; exit 2 ;;
esac
