#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-enable}"
APPLIANCE_USER="${2:-${SUDO_USER:-}}"
PROJECT_ROOT="${3:-}"
SESSION_NAME=leftover-achievements
STATE_DIR=/etc/leftover-achievements
CONFIG_DIR=$STATE_DIR/labwc
LIGHTDM_MAIN=/etc/lightdm/lightdm.conf
LIGHTDM_CONFIG=/etc/lightdm/lightdm.conf.d/90-leftover-achievements.conf
LIGHTDM_SESSION_STATE=$STATE_DIR/lightdm-main-session.state
SESSION_FILE=/usr/share/wayland-sessions/$SESSION_NAME.desktop
SESSION_LAUNCHER=/usr/local/libexec/leftover-achievements-session
CURSOR_THEME=/usr/share/icons/LeftoverAchievementsInvisible

usage() {
  echo "Usage: sudo $0 enable USER PROJECT_ROOT"
  echo "       sudo $0 disable"
  echo "       sudo $0 status USER PROJECT_ROOT"
}

require_root() {
  [[ "$(id -u)" -eq 0 ]] || { echo "Error: appliance-session configuration must run with sudo." >&2; exit 1; }
}

active_lightdm_setting() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  awk -v key="$key" '
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      value = $0
      sub(/^[^=]*=[[:space:]]*/, "", value)
      sub(/[[:space:]]*#.*/, "", value)
      sub(/[[:space:]]+$/, "", value)
      found = value
    }
    END { if (found != "") print found }
  ' "$file"
}

replace_active_lightdm_setting() {
  local file="$1" key="$2" value="$3" only_value="${4:-}" temporary
  [[ -f "$file" ]] || return 0
  temporary="$(mktemp)"
  awk -v key="$key" -v replacement="$value" -v only="$only_value" '
    {
      line = $0
      if (line ~ "^[[:space:]]*" key "[[:space:]]*=") {
        current = line
        sub(/^[^=]*=[[:space:]]*/, "", current)
        sub(/[[:space:]]*#.*/, "", current)
        sub(/[[:space:]]+$/, "", current)
        if (only == "" || current == only) {
          equals = index(line, "=")
          rest = substr(line, equals + 1)
          match(rest, /^[[:space:]]*/)
          prefix = substr(line, 1, equals) substr(rest, 1, RLENGTH)
          rest = substr(rest, RLENGTH + 1)
          hash = index(rest, "#")
          suffix = hash ? " " substr(rest, hash) : ""
          print prefix replacement suffix
          next
        }
      }
      print line
    }
  ' "$file" > "$temporary"
  install -m 0644 "$temporary" "$file"
  rm -f "$temporary"
}

patch_lightdm_main_sessions() {
  [[ -f "$LIGHTDM_MAIN" ]] || return 0
  install -d -m 0755 "$STATE_DIR"
  if [[ ! -f "$LIGHTDM_SESSION_STATE" ]]; then
    local previous_user_session previous_autologin_session state_tmp
    previous_user_session="$(active_lightdm_setting "$LIGHTDM_MAIN" user-session)"
    previous_autologin_session="$(active_lightdm_setting "$LIGHTDM_MAIN" autologin-session)"
    state_tmp="$(mktemp)"
    {
      printf 'user-session=%s\n' "$previous_user_session"
      printf 'autologin-session=%s\n' "$previous_autologin_session"
    } > "$state_tmp"
    install -m 0600 "$state_tmp" "$LIGHTDM_SESSION_STATE"
    rm -f "$state_tmp"
  fi
  replace_active_lightdm_setting "$LIGHTDM_MAIN" user-session "$SESSION_NAME"
  replace_active_lightdm_setting "$LIGHTDM_MAIN" autologin-session "$SESSION_NAME"
}

restore_lightdm_main_sessions() {
  [[ -f "$LIGHTDM_MAIN" && -f "$LIGHTDM_SESSION_STATE" ]] || return 0
  local previous_user_session previous_autologin_session
  previous_user_session="$(active_lightdm_setting "$LIGHTDM_SESSION_STATE" user-session)"
  previous_autologin_session="$(active_lightdm_setting "$LIGHTDM_SESSION_STATE" autologin-session)"
  if [[ -n "$previous_user_session" ]]; then
    replace_active_lightdm_setting "$LIGHTDM_MAIN" user-session "$previous_user_session" "$SESSION_NAME"
  fi
  if [[ -n "$previous_autologin_session" ]]; then
    replace_active_lightdm_setting "$LIGHTDM_MAIN" autologin-session "$previous_autologin_session" "$SESSION_NAME"
  fi
  rm -f "$LIGHTDM_SESSION_STATE"
}

effective_lightdm_setting() {
  local key="$1" value
  value="$(active_lightdm_setting "$LIGHTDM_MAIN" "$key")"
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
  else
    active_lightdm_setting "$LIGHTDM_CONFIG" "$key"
  fi
}

verify_lightdm_session_selection() {
  local failed=0 effective_user_session effective_autologin_session
  effective_user_session="$(effective_lightdm_setting user-session)"
  effective_autologin_session="$(effective_lightdm_setting autologin-session)"
  if [[ -f "$SESSION_FILE" ]]; then
    echo "[ok] $SESSION_FILE is installed."
  else
    echo "[error] Dedicated Wayland session is missing: $SESSION_FILE"
    failed=1
  fi
  if [[ "$effective_user_session" == "$SESSION_NAME" ]]; then
    echo "[ok] Effective LightDM user-session is $SESSION_NAME."
  else
    echo "[error] Effective LightDM user-session is '${effective_user_session:-unset}', not $SESSION_NAME."
    [[ "$effective_user_session" != rpd-labwc ]] || echo "[error] Raspberry Pi OS is still selecting the normal rpd-labwc desktop."
    failed=1
  fi
  if [[ "$effective_autologin_session" == "$SESSION_NAME" ]]; then
    echo "[ok] Effective LightDM autologin-session is $SESSION_NAME."
  else
    echo "[error] Effective LightDM autologin-session is '${effective_autologin_session:-unset}', not $SESSION_NAME."
    [[ "$effective_autologin_session" != rpd-labwc ]] || echo "[error] Raspberry Pi OS autologin still selects the normal rpd-labwc desktop."
    failed=1
  fi
  return "$failed"
}

resolve_inputs() {
  [[ -n "$APPLIANCE_USER" ]] || { echo "Error: the non-root kiosk user is required." >&2; exit 1; }
  USER_HOME="$(getent passwd "$APPLIANCE_USER" | cut -d: -f6)"
  [[ -n "$USER_HOME" && "$APPLIANCE_USER" != root ]] || { echo "Error: kiosk user '$APPLIANCE_USER' is invalid." >&2; exit 1; }
  [[ -n "$PROJECT_ROOT" ]] || PROJECT_ROOT="$USER_HOME/LeftoverAchievements"
  [[ "$PROJECT_ROOT" == /* && "$PROJECT_ROOT" != *$'\n'* ]] || { echo "Error: project path must be an absolute path." >&2; exit 1; }
  PROJECT_ROOT="${PROJECT_ROOT%/}"
  [[ -x "$PROJECT_ROOT/scripts/start-kiosk.sh" ]] || { echo "Error: start-kiosk.sh is missing or not executable in $PROJECT_ROOT." >&2; exit 1; }
  [[ -f "$PROJECT_ROOT/static/images/leftover-achievements-logo.png" ]] || { echo "Error: project logo is missing." >&2; exit 1; }
}

find_wayland_session_dir() {
  SESSION_DIR=""
  if [[ -d /usr/share/wayland-sessions ]] && command -v labwc >/dev/null 2>&1; then
    SESSION_DIR=/usr/share/wayland-sessions
  fi
  [[ -n "$SESSION_DIR" ]] || {
    echo "Warning: a labwc Wayland session was not found; this Raspberry Pi OS image is unsupported." >&2
    exit 1
  }
}

install_invisible_cursor() {
  install -d -m 0755 "$CURSOR_THEME/cursors"
  python3 - "$CURSOR_THEME/cursors/left_ptr" <<'PY'
import struct
import sys

# A standards-compliant 1x1 ARGB Xcursor whose only pixel is transparent.
image_type = 0xFFFD0002
payload = struct.pack("<4I", 0x72756358, 16, 0x00010000, 1)
payload += struct.pack("<3I", image_type, 1, 28)
payload += struct.pack("<9I", 36, image_type, 1, 1, 1, 1, 0, 0, 0)
payload += struct.pack("<I", 0)
with open(sys.argv[1], "wb") as cursor:
    cursor.write(payload)
PY
  chmod 0644 "$CURSOR_THEME/cursors/left_ptr"
  local cursor_name
  for cursor_name in \
    default arrow pointer hand1 hand2 xterm text vertical-text watch wait progress \
    crosshair move fleur all-scroll grab grabbing help question_arrow context-menu \
    not-allowed no-drop copy alias cell zoom-in zoom-out col-resize row-resize \
    e-resize w-resize n-resize s-resize ne-resize nw-resize se-resize sw-resize \
    ew-resize ns-resize nesw-resize nwse-resize sb_h_double_arrow sb_v_double_arrow \
    top_left_corner top_right_corner bottom_left_corner bottom_right_corner dnd-none \
    dnd-copy dnd-move dnd-link; do
    ln -sfn left_ptr "$CURSOR_THEME/cursors/$cursor_name"
  done
  cat > "$CURSOR_THEME/index.theme" <<'EOF'
[Icon Theme]
Name=LeftoverAchievements Invisible Cursor
Comment=Session-scoped transparent cursor for the appliance kiosk
EOF
}

remove_legacy_autostart() {
  local autostart="$USER_HOME/.config/labwc/autostart"
  [[ -f "$autostart" ]] || return 0
  local filtered
  filtered="$(mktemp)"
  awk '!/LeftoverAchievements\/scripts\/start-kiosk\.sh/ && !/leftover-achievements\/scripts\/start-kiosk\.sh/' "$autostart" > "$filtered"
  if ! cmp -s "$autostart" "$filtered"; then
    [[ -e "$autostart.leftover-achievements.bak" ]] || cp -a "$autostart" "$autostart.leftover-achievements.bak"
    install -o "$APPLIANCE_USER" -g "$(id -gn "$APPLIANCE_USER")" -m 0644 "$filtered" "$autostart"
    echo "Removed the legacy desktop-overlay kiosk autostart entry."
  fi
  rm -f "$filtered"
}

enable_session() {
  resolve_inputs
  find_wayland_session_dir
  command -v lightdm >/dev/null 2>&1 || { echo "Warning: LightDM is required to select the appliance session." >&2; exit 1; }

  install -d -m 0755 "$CONFIG_DIR" /usr/local/libexec /etc/lightdm/lightdm.conf.d
  local detected_autologin_user
  detected_autologin_user="$(active_lightdm_setting "$LIGHTDM_MAIN" autologin-user)"
  if [[ -n "$detected_autologin_user" && "$detected_autologin_user" != "$APPLIANCE_USER" ]]; then
    echo "Error: LightDM autologin-user is '$detected_autologin_user'; run the installer as that user instead of '$APPLIANCE_USER'." >&2
    exit 1
  fi
  patch_lightdm_main_sessions
  install_invisible_cursor

  cat > "$CONFIG_DIR/environment" <<EOF
XCURSOR_THEME=LeftoverAchievementsInvisible
XCURSOR_SIZE=1
XCURSOR_PATH=/usr/share/icons
XDG_CURRENT_DESKTOP=LeftoverAchievements
LEFTOVER_DATA_DIR=$USER_HOME/.local/share/LeftoverAchievements/data
EOF
  cat > "$CONFIG_DIR/rc.xml" <<'EOF'
<?xml version="1.0"?>
<labwc_config>
  <!-- Touch remains native; only the rendered pointer image is transparent. -->
  <touch mouseEmulation="no" />
</labwc_config>
EOF

  local kiosk logo
  printf -v kiosk '%q' "$PROJECT_ROOT/scripts/run-kiosk-session.sh"
  printf -v logo '%q' "$PROJECT_ROOT/static/images/leftover-achievements-logo.png"
  cat > "$CONFIG_DIR/autostart" <<EOF
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP 2>/dev/null || true
dbus-update-activation-environment --systemd DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP 2>/dev/null || true
if command -v kanshi >/dev/null 2>&1; then
  kanshi >/dev/null 2>&1 &
fi
if command -v swaybg >/dev/null 2>&1; then
  swaybg -c '#05080d' -m center -i $logo >/dev/null 2>&1 &
fi
$kiosk >/dev/null 2>&1 &
EOF
  chmod 0644 "$CONFIG_DIR/environment" "$CONFIG_DIR/rc.xml" "$CONFIG_DIR/autostart"

  cat > "$SESSION_LAUNCHER" <<EOF
#!/bin/sh
export HOME=$(printf '%q' "$USER_HOME")
exec $(command -v labwc) -C $CONFIG_DIR
EOF
  chmod 0755 "$SESSION_LAUNCHER"

  cat > "$SESSION_FILE" <<EOF
[Desktop Entry]
Name=LeftoverAchievements Appliance
Comment=Dedicated minimal labwc Chromium kiosk
Exec=$SESSION_LAUNCHER
Type=Application
DesktopNames=LeftoverAchievements
EOF
  chmod 0644 "$SESSION_FILE"

  cat > "$LIGHTDM_CONFIG" <<EOF
[Seat:*]
autologin-user=${detected_autologin_user:-$APPLIANCE_USER}
autologin-user-timeout=0
autologin-session=$SESSION_NAME
user-session=$SESSION_NAME
EOF
  chmod 0644 "$LIGHTDM_CONFIG"
  if getent group autologin >/dev/null 2>&1; then
    usermod -a -G autologin "$APPLIANCE_USER"
  fi
  remove_legacy_autostart
  echo "Dedicated LeftoverAchievements appliance session enabled for $APPLIANCE_USER."
  echo "A reboot is required to enter the new session."
}

disable_session() {
  restore_lightdm_main_sessions
  rm -f "$LIGHTDM_CONFIG"
  rm -f "$SESSION_FILE"
  echo "Dedicated appliance-session selection disabled. The normal OS desktop/session will be used after reboot."
}

show_status() {
  resolve_inputs
  local failed=0
  verify_lightdm_session_selection || failed=1
  if [[ -f "$SESSION_FILE" ]] && grep -Fq "$SESSION_LAUNCHER" "$SESSION_FILE"; then
    echo "[ok] Minimal labwc session is installed."
  else
    echo "[warning] The dedicated labwc session is missing."
    failed=1
  fi
  if [[ -f "$CONFIG_DIR/autostart" ]] && grep -Fq "run-kiosk-session.sh" "$CONFIG_DIR/autostart" && ! grep -Eq 'lxpanel|pcmanfm|wf-panel|lxsession' "$CONFIG_DIR/autostart"; then
    echo "[ok] LA loading/kiosk starts without a desktop panel or file-manager wallpaper."
  else
    echo "[warning] Kiosk autostart is missing or includes desktop-shell processes."
    failed=1
  fi
  if [[ -f "$CONFIG_DIR/environment" ]] && grep -Fqx 'XCURSOR_THEME=LeftoverAchievementsInvisible' "$CONFIG_DIR/environment" && grep -Fqx "LEFTOVER_DATA_DIR=$USER_HOME/.local/share/LeftoverAchievements/data" "$CONFIG_DIR/environment" && [[ -f "$CURSOR_THEME/cursors/left_ptr" ]]; then
    echo "[ok] Session-scoped invisible Wayland cursor is installed."
  else
    echo "[warning] Appliance cursor hiding is incomplete."
    failed=1
  fi
  if command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1; then
    echo "[ok] Chromium is available to the appliance session."
  else
    echo "[warning] Chromium is not installed; install it before rebooting into appliance mode."
    failed=1
  fi
  return "$failed"
}

if [[ "${LEFTOVER_APPLIANCE_SESSION_LIBRARY_ONLY:-0}" != 1 ]]; then
  require_root
  case "$ACTION" in
    enable) enable_session ;;
    disable) disable_session ;;
    status|verify) show_status ;;
    *) usage >&2; exit 2 ;;
  esac
fi
