#!/usr/bin/env bash
# Narrow root helper for LeftoverAchievements-owned system configuration.
# LeftoverAchievements privileged helper API 1
set -euo pipefail

ACTION="${1:-}"
STATE_DIR=/etc/leftover-achievements
USER_FILE="$STATE_DIR/appliance-user"
SERVICE_FILE=/etc/systemd/system/leftover-achievements.service
SUDOERS_FILE=/etc/sudoers.d/leftover-achievements-update
HELPER_PATH=/usr/local/sbin/leftover-achievements-migrate
LABWC_CONFIG=/etc/leftover-achievements/labwc
LIGHTDM_CONFIG=/etc/lightdm/lightdm.conf.d/90-leftover-achievements.conf
SESSION_FILE=/usr/share/wayland-sessions/leftover-achievements.desktop
SESSION_LAUNCHER=/usr/local/libexec/leftover-achievements-session

[[ "$(id -u)" -eq 0 ]] || { echo "This helper must run as root." >&2; exit 1; }

validate_user() {
  local candidate="$1"
  [[ "$candidate" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "Invalid appliance user." >&2; exit 2; }
  [[ "$(id -u "$candidate")" -ge 1000 ]] || { echo "The appliance user must be non-root." >&2; exit 2; }
  APP_HOME="$(getent passwd "$candidate" | cut -d: -f6)"
  [[ "$APP_HOME" == /home/* && -d "$APP_HOME" ]] || { echo "Unexpected appliance home directory." >&2; exit 2; }
  APP_USER="$candidate"
}

load_installed_user() {
  [[ -f "$USER_FILE" ]] || { echo "LeftoverAchievements has not been bootstrapped." >&2; exit 2; }
  local candidate
  candidate="$(head -n 1 "$USER_FILE")"
  validate_user "$candidate"
}

validate_current_release() {
  INSTALL_ROOT="$APP_HOME/.local/share/LeftoverAchievements"
  CURRENT="$INSTALL_ROOT/app/current"
  DATA_DIR="$INSTALL_ROOT/data"
  [[ -L "$CURRENT" ]] || { echo "The packaged application current link is missing." >&2; exit 2; }
  RELEASE="$(readlink -f "$CURRENT")"
  case "$RELEASE" in
    "$INSTALL_ROOT/app/releases/"*) ;;
    *) echo "The current release resolves outside the managed releases directory." >&2; exit 2 ;;
  esac
  [[ -f "$RELEASE/.install-complete" && -x "$RELEASE/scripts/start-backend.sh" ]] || {
    echo "The current release is incomplete." >&2; exit 2;
  }
  VERSION="$(head -n 1 "$RELEASE/build-version.txt")"
  ARCHITECTURE="$(head -n 1 "$RELEASE/build-architecture.txt")"
  [[ "$VERSION" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ && "$ARCHITECTURE" == arm64 ]] || {
    echo "The current release metadata is invalid." >&2; exit 2;
  }
}

refresh_vetted_helper() {
  [[ "${LEFTOVER_HELPER_REFRESHED:-0}" != 1 ]] || return 0
  local candidate
  candidate="$(mktemp)"
  if ! curl --fail --location --silent --show-error \
    "https://raw.githubusercontent.com/leftovernick/Leftover-Achievements/$VERSION/scripts/pi-privileged-helper.sh" \
    -o "$candidate"; then
    rm -f "$candidate"
    echo "Could not retrieve the vetted privileged helper for $VERSION." >&2
    exit 2
  fi
  grep -Fqx '# LeftoverAchievements privileged helper API 1' "$candidate" || {
    rm -f "$candidate"; echo "Downloaded helper identity is invalid." >&2; exit 2;
  }
  bash -n "$candidate"
  if ! cmp -s "$candidate" "$HELPER_PATH"; then
    install -m 0755 "$candidate" "$HELPER_PATH"
    rm -f "$candidate"
    LEFTOVER_HELPER_REFRESHED=1 exec "$HELPER_PATH" apply
  fi
  rm -f "$candidate"
}

apply_configuration() {
  load_installed_user
  validate_current_release
  refresh_vetted_helper
  install -d -o "$APP_USER" -g "$(id -gn "$APP_USER")" -m 0750 "$DATA_DIR" "$DATA_DIR/logs" "$DATA_DIR/audio"
  [[ -f "$DATA_DIR/.env" ]] || install -o "$APP_USER" -g "$(id -gn "$APP_USER")" -m 0600 /dev/null "$DATA_DIR/.env"

  local service_tmp sudoers_tmp
  service_tmp="$(mktemp)"
  sudoers_tmp="$(mktemp)"
  trap 'rm -f "${service_tmp:-}" "${sudoers_tmp:-}"' EXIT
  cat > "$service_tmp" <<EOF
[Unit]
Description=LeftoverAchievements FastAPI backend
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$CURRENT
Environment=LEFTOVER_RUNTIME_MODE=raspberry_pi
Environment=LEFTOVER_DATA_DIR=$DATA_DIR
EnvironmentFile=-$DATA_DIR/.env
ExecStart=$CURRENT/scripts/start-backend.sh
Restart=on-failure
RestartSec=3
TimeoutStopSec=12s

[Install]
WantedBy=multi-user.target
EOF
  install -m 0644 "$service_tmp" "$SERVICE_FILE"

  cat > "$sudoers_tmp" <<EOF
$APP_USER ALL=(root) NOPASSWD: $HELPER_PATH apply
$APP_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart leftover-achievements.service
EOF
  chmod 0440 "$sudoers_tmp"
  visudo -cf "$sudoers_tmp" >/dev/null
  install -m 0440 "$sudoers_tmp" "$SUDOERS_FILE"

  # Re-assert only the fixed, managed kiosk paths. Applications still run as
  # the unprivileged appliance user and resolve through the atomic current link.
  [[ -x /usr/bin/labwc && -d /usr/share/wayland-sessions ]] || {
    echo "The supported labwc Wayland session is unavailable." >&2; exit 2;
  }
  install -d -m 0755 "$LABWC_CONFIG" /etc/lightdm/lightdm.conf.d /usr/local/libexec
  cat > "$LABWC_CONFIG/environment" <<EOF
XCURSOR_THEME=LeftoverAchievementsInvisible
XCURSOR_SIZE=1
XCURSOR_PATH=/usr/share/icons
XDG_CURRENT_DESKTOP=LeftoverAchievements
LEFTOVER_DATA_DIR=$DATA_DIR
EOF
  cat > "$LABWC_CONFIG/autostart" <<EOF
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP 2>/dev/null || true
dbus-update-activation-environment --systemd DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP 2>/dev/null || true
if command -v kanshi >/dev/null 2>&1; then
  kanshi >/dev/null 2>&1 &
fi
if command -v swaybg >/dev/null 2>&1; then
  swaybg -c '#05080d' -m center -i $CURRENT/static/images/leftover-achievements-logo.png >/dev/null 2>&1 &
fi
$CURRENT/scripts/run-kiosk-session.sh >/dev/null 2>&1 &
EOF
  cat > "$SESSION_LAUNCHER" <<EOF
#!/bin/sh
export HOME=$APP_HOME
exec /usr/bin/labwc -C $LABWC_CONFIG
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
  cat > "$LIGHTDM_CONFIG" <<EOF
[Seat:*]
autologin-user=$APP_USER
autologin-user-timeout=0
autologin-session=leftover-achievements
user-session=leftover-achievements
EOF
  chmod 0644 "$LABWC_CONFIG/environment" "$LABWC_CONFIG/autostart" "$SESSION_FILE" "$LIGHTDM_CONFIG"
  systemctl daemon-reload
  systemctl enable leftover-achievements.service >/dev/null
  echo "Applied vetted LeftoverAchievements system configuration for $VERSION."
}

case "$ACTION" in
  install)
    [[ "$#" -eq 2 ]] || { echo "Usage: $0 install USER" >&2; exit 2; }
    validate_user "$2"
    install -d -m 0755 "$STATE_DIR"
    printf '%s\n' "$APP_USER" | install -m 0644 /dev/stdin "$USER_FILE"
    apply_configuration
    ;;
  apply)
    [[ "$#" -eq 1 ]] || { echo "The apply action accepts no arguments." >&2; exit 2; }
    apply_configuration
    ;;
  *)
    echo "Allowed actions: install USER, apply" >&2
    exit 2
    ;;
esac
