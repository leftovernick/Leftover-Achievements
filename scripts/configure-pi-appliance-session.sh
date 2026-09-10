#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-enable}"
APPLIANCE_USER="${2:-${SUDO_USER:-}}"
PROJECT_ROOT="${3:-}"
SESSION_NAME=leftover-achievements
CONFIG_DIR=/etc/leftover-achievements/labwc
LIGHTDM_CONFIG=/etc/lightdm/lightdm.conf.d/90-leftover-achievements.conf
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

  cat > "$SESSION_DIR/$SESSION_NAME.desktop" <<EOF
[Desktop Entry]
Name=LeftoverAchievements Appliance
Comment=Dedicated minimal labwc Chromium kiosk
Exec=$SESSION_LAUNCHER
Type=Application
DesktopNames=LeftoverAchievements
EOF
  chmod 0644 "$SESSION_DIR/$SESSION_NAME.desktop"

  cat > "$LIGHTDM_CONFIG" <<EOF
[Seat:*]
autologin-user=$APPLIANCE_USER
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
  rm -f "$LIGHTDM_CONFIG"
  rm -f /usr/share/wayland-sessions/$SESSION_NAME.desktop
  echo "Dedicated appliance-session selection disabled. The normal OS desktop/session will be used after reboot."
}

show_status() {
  resolve_inputs
  local failed=0
  if [[ -f "$LIGHTDM_CONFIG" ]] && grep -Fqx "user-session=$SESSION_NAME" "$LIGHTDM_CONFIG"; then
    echo "[ok] LightDM selects the dedicated appliance session."
  else
    echo "[warning] LightDM does not select the appliance session."
    failed=1
  fi
  if [[ -f /usr/share/wayland-sessions/$SESSION_NAME.desktop ]] && grep -Fq "$SESSION_LAUNCHER" /usr/share/wayland-sessions/$SESSION_NAME.desktop; then
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

require_root
case "$ACTION" in
  enable) enable_session ;;
  disable) disable_session ;;
  status|verify) show_status ;;
  *) usage >&2; exit 2 ;;
esac
