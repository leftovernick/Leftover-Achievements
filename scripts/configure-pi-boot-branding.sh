#!/usr/bin/env bash
set -euo pipefail

CONFIG_BEGIN="# BEGIN LeftoverAchievements appliance boot"
CONFIG_END="# END LeftoverAchievements appliance boot"
LEGACY_CONFIG_BEGIN="# BEGIN LeftoverAchievements boot branding"
LEGACY_CONFIG_END="# END LeftoverAchievements boot branding"
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
    echo "Error: appliance boot can only be configured on Raspberry Pi hardware." >&2
    exit 1
  fi
  if [[ -z "$BOOT_CONFIG" || -z "$CMDLINE_FILE" ]]; then
    echo "Error: a matching Raspberry Pi config.txt/cmdline.txt pair was not found." >&2
    echo "Checked /boot/firmware (current OS) and /boot (legacy OS)." >&2
    exit 1
  fi
}

require_root() {
  [[ "$(id -u)" -eq 0 ]] || {
    echo "Error: this command changes boot files and must be run with sudo." >&2
    exit 1
  }
}

remove_managed_config_blocks() {
  awk \
    -v begin="$CONFIG_BEGIN" -v end="$CONFIG_END" \
    -v old_begin="$LEGACY_CONFIG_BEGIN" -v old_end="$LEGACY_CONFIG_END" '
      $0 == begin || $0 == old_begin { managed = 1; next }
      $0 == end || $0 == old_end { managed = 0; next }
      !managed { print }
    ' "$1" > "$2"
}

write_appliance_cmdline() {
  local output token
  output=""
  for token in $(tr '\r\n' ' ' < "$CMDLINE_FILE"); do
    case "$token" in
      console=tty1|quiet|splash|loglevel=*|logo.nologo|fullscreen_logo=*|fullscreen_logo_name=*|vt.global_cursor_default=*|systemd.show_status=*|rd.systemd.show_status=*) ;;
      *) output+=" $token" ;;
    esac
  done
  output="${output# }"
  output+=" quiet loglevel=3 logo.nologo vt.global_cursor_default=0"
  output+=" systemd.show_status=false rd.systemd.show_status=false"
  printf '%s\n' "$output" | install -m 0644 /dev/stdin "$CMDLINE_FILE"
}

enable_appliance_boot() {
  require_root
  local filtered_config new_config
  filtered_config="$(mktemp)"
  new_config="$(mktemp)"
  remove_managed_config_blocks "$BOOT_CONFIG" "$filtered_config"
  {
    cat "$filtered_config"
    echo
    echo "$CONFIG_BEGIN"
    echo "# Suppress the firmware rainbow screen. No userspace/initramfs splash is used."
    echo "[all]"
    echo "disable_splash=1"
    echo "$CONFIG_END"
  } > "$new_config"

  [[ -e "$BOOT_CONFIG.leftover-achievements.bak" ]] || cp -a "$BOOT_CONFIG" "$BOOT_CONFIG.leftover-achievements.bak"
  [[ -e "$CMDLINE_FILE.leftover-achievements.bak" ]] || cp -a "$CMDLINE_FILE" "$CMDLINE_FILE.leftover-achievements.bak"
  install -m 0644 "$new_config" "$BOOT_CONFIG"
  rm -f "$filtered_config" "$new_config"
  write_appliance_cmdline
  sync

  echo "Boot config: $BOOT_CONFIG"
  echo "Kernel command line: $CMDLINE_FILE"
  echo "Safe black/quiet appliance boot enabled; no initramfs splash was configured."
  if [[ -e /etc/initramfs-tools/hooks/splash-screen-hook.sh || -e /lib/firmware/logo.tga ]]; then
    echo "Notice: files from an older early-splash installation remain but are inactive; fullscreen_logo parameters were removed."
  fi
  echo "Reboot to apply the boot changes."
}

disable_appliance_boot() {
  require_root
  local filtered_config output token
  filtered_config="$(mktemp)"
  remove_managed_config_blocks "$BOOT_CONFIG" "$filtered_config"
  install -m 0644 "$filtered_config" "$BOOT_CONFIG"
  rm -f "$filtered_config"

  output=""
  for token in $(tr '\r\n' ' ' < "$CMDLINE_FILE"); do
    case "$token" in
      logo.nologo|fullscreen_logo=*|fullscreen_logo_name=*|vt.global_cursor_default=*|systemd.show_status=*|rd.systemd.show_status=*|loglevel=3) ;;
      *) output+=" $token" ;;
    esac
  done
  output="${output# }"
  [[ " $output " == *" console=tty1 "* ]] || output+=" console=tty1"
  [[ " $output " == *" quiet "* ]] || output+=" quiet"
  printf '%s\n' "$output" | install -m 0644 /dev/stdin "$CMDLINE_FILE"
  echo "LeftoverAchievements appliance boot suppression disabled. Reboot to apply it."
}

has_cmdline_token() { grep -Eq "(^| )$1( |$)" "$CMDLINE_FILE"; }

show_status() {
  local failed=0
  echo "Detected boot config: $BOOT_CONFIG"
  echo "Detected kernel command line: $CMDLINE_FILE"
  if grep -Fqx "$CONFIG_BEGIN" "$BOOT_CONFIG" && grep -Eq '^disable_splash=1([[:space:]]|$)' "$BOOT_CONFIG"; then
    echo "[ok] Firmware rainbow/Raspberry Pi splash suppression is configured."
  else
    echo "[warning] Firmware splash suppression is not configured."
    failed=1
  fi
  if has_cmdline_token 'quiet' && has_cmdline_token 'loglevel=3' && has_cmdline_token 'logo\.nologo' && ! has_cmdline_token 'console=tty1' && ! has_cmdline_token 'splash'; then
    echo "[ok] Safe black/quiet boot and system console suppression are active."
  else
    echo "[warning] Black/quiet appliance boot parameters are incomplete."
    failed=1
  fi
  if ! grep -Eq '(^| )fullscreen_logo(_name)?=[^ ]+' "$CMDLINE_FILE"; then
    echo "[ok] Crash-prone fullscreen/initramfs branding is inactive."
  else
    echo "[warning] Legacy fullscreen_logo parameters are still active."
    failed=1
  fi
  if has_cmdline_token 'systemd\.show_status=false' && has_cmdline_token 'rd\.systemd\.show_status=false'; then
    echo "[ok] systemd boot status output is suppressed."
  else
    echo "[warning] systemd status suppression is incomplete."
    failed=1
  fi
  return "$failed"
}

case "$ACTION" in
  enable) require_pi; enable_appliance_boot ;;
  disable) require_pi; disable_appliance_boot ;;
  status|verify) require_pi; show_status ;;
  *) usage >&2; exit 2 ;;
esac
