#!/usr/bin/env bash
set -euo pipefail

# Recovery-only helper for releases that previously changed Raspberry Pi boot
# files. Normal installs and updates must never call this script.
CONFIG_BEGIN="# BEGIN LeftoverAchievements appliance boot"
CONFIG_END="# END LeftoverAchievements appliance boot"
LEGACY_CONFIG_BEGIN="# BEGIN LeftoverAchievements boot branding"
LEGACY_CONFIG_END="# END LeftoverAchievements boot branding"
ACTION="${1:-status}"
TEST_BOOT_DIRECTORY="${LEFTOVER_TEST_BOOT_DIRECTORY:-}"

detect_boot_files() {
  if [[ -n "$TEST_BOOT_DIRECTORY" ]]; then
    # Allows the recovery transform to be exercised without touching /boot.
    # Root is deliberately prohibited from using this test-only override.
    [[ "$(id -u)" -ne 0 && "$TEST_BOOT_DIRECTORY" == /* ]] || {
      echo "Error: the test boot directory is only available to a non-root test process." >&2
      exit 2
    }
    BOOT_CONFIG="$TEST_BOOT_DIRECTORY/config.txt"
    CMDLINE_FILE="$TEST_BOOT_DIRECTORY/cmdline.txt"
  elif [[ -f /boot/firmware/config.txt && -f /boot/firmware/cmdline.txt ]]; then
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

usage() {
  echo "Usage: sudo $0 restore-default"
  echo "       sudo $0 status"
}

require_boot_files() {
  if [[ -z "$TEST_BOOT_DIRECTORY" ]]; then
    [[ "$(id -u)" -eq 0 ]] || {
      echo "Error: boot recovery must be run with sudo." >&2
      exit 1
    }
    if [[ ! -r /proc/device-tree/model ]] || ! grep -aq "Raspberry Pi" /proc/device-tree/model; then
      echo "Error: boot recovery is only supported on Raspberry Pi hardware." >&2
      exit 1
    fi
  fi
  if [[ -z "$BOOT_CONFIG" || -z "$CMDLINE_FILE" || ! -f "$BOOT_CONFIG" || ! -f "$CMDLINE_FILE" ]]; then
    echo "Error: a matching Raspberry Pi config.txt/cmdline.txt pair was not found." >&2
    echo "Checked /boot/firmware (current OS) and /boot (legacy OS)." >&2
    exit 1
  fi
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

has_exact_token() {
  local file="$1" wanted="$2" token
  for token in $(tr '\r\n' ' ' < "$file"); do
    [[ "$token" == "$wanted" ]] && return 0
  done
  return 1
}

is_known_la_token() {
  case "$1" in
    fullscreen_logo=*|fullscreen_logo_name=*|loglevel=3|logo.nologo|vt.global_cursor_default=0|systemd.show_status=false|rd.systemd.show_status=false) return 0 ;;
    *) return 1 ;;
  esac
}

restore_cmdline() {
  local source="$1" backup="$1.leftover-achievements.bak" output="" token temporary

  for token in $(tr '\r\n' ' ' < "$source"); do
    if is_known_la_token "$token"; then
      # Preserve a matching token if the one-time pre-install backup proves it
      # existed before LeftoverAchievements managed this file.
      if [[ -f "$backup" ]] && has_exact_token "$backup" "$token"; then
        output+=" $token"
      fi
    elif [[ "$token" == quiet && -f "$backup" ]] && ! has_exact_token "$backup" quiet; then
      # The reliability-first black-boot release added quiet on some systems.
      :
    else
      output+=" $token"
    fi
  done

  # Re-add standard tokens that an older LeftoverAchievements installer removed,
  # but only when its own pre-install backup proves they were originally present.
  if [[ -f "$backup" ]]; then
    for token in console=tty1 quiet splash; do
      if has_exact_token "$backup" "$token" && [[ " $output " != *" $token "* ]]; then
        output+=" $token"
      fi
    done
  fi

  temporary="$(mktemp)"
  printf '%s\n' "${output# }" > "$temporary"
  install -m 0644 "$temporary" "$source"
  rm -f "$temporary"
}

restore_default() {
  local filtered_config
  filtered_config="$(mktemp)"
  trap 'rm -f "${filtered_config:-}"' EXIT
  remove_managed_config_blocks "$BOOT_CONFIG" "$filtered_config"
  install -m 0644 "$filtered_config" "$BOOT_CONFIG"
  restore_cmdline "$CMDLINE_FILE"
  [[ -n "$TEST_BOOT_DIRECTORY" ]] || sync

  echo "Removed LeftoverAchievements-managed boot settings from:"
  echo "  $BOOT_CONFIG"
  echo "  $CMDLINE_FILE"
  echo "Unrelated configuration and standard initramfs files were left untouched."
  echo "Reboot to use the restored Raspberry Pi OS boot behavior."
}

show_status() {
  local found=0 token
  if grep -Fqx "$CONFIG_BEGIN" "$BOOT_CONFIG" || grep -Fqx "$LEGACY_CONFIG_BEGIN" "$BOOT_CONFIG"; then
    echo "[recovery needed] LeftoverAchievements boot block found in $BOOT_CONFIG"
    found=1
  fi
  for token in $(tr '\r\n' ' ' < "$CMDLINE_FILE"); do
    if is_known_la_token "$token"; then
      echo "[recovery candidate] $token"
      found=1
    fi
  done
  if (( found == 0 )); then
    echo "No known LeftoverAchievements early-boot changes were found."
  fi
  return "$found"
}

require_boot_files
case "$ACTION" in
  restore-default|disable) restore_default ;;
  status|verify) show_status ;;
  enable)
    echo "Early-boot customization is no longer supported; Raspberry Pi OS boot configuration is intentionally left unchanged." >&2
    exit 2
    ;;
  *) usage >&2; exit 2 ;;
esac
