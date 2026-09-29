#!/usr/bin/env bash
set -euo pipefail

CURRENT_APP="${1:-}"
VERSION="${2:-}"
ASSET_URL="${3:-}"
EXPECTED_ARCH="${4:-}"
APP_PID="${5:-}"
PHASE_PATH="${6:-}"
APP_NAME="LeftoverAchievements.app"

set_phase() {
  printf '%s\n' "$1" > "$PHASE_PATH"
}

fail_update() {
  [[ -n "$PHASE_PATH" ]] && set_phase failed
  echo "macOS update failed: $1" >&2
  exit 1
}

[[ -n "$PHASE_PATH" ]] || { echo "macOS update failed: the status path is missing." >&2; exit 1; }
[[ "$CURRENT_APP" = /* && "$CURRENT_APP" == *.app ]] || fail_update "the current application path is invalid."
[[ -d "$CURRENT_APP/Contents" ]] || fail_update "the current application bundle is missing."
[[ "$VERSION" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+([.+-][0-9A-Za-z.-]+)?$ ]] || fail_update "the release version is invalid."
[[ "$ASSET_URL" == https://github.com/* ]] || fail_update "the release download URL is invalid."
[[ "$EXPECTED_ARCH" == arm64 || "$EXPECTED_ARCH" == x64 ]] || fail_update "the expected architecture is invalid."
[[ "$APP_PID" =~ ^[0-9]+$ ]] || fail_update "the application process ID is invalid."
INSTALL_DIR="$(dirname "$CURRENT_APP")"
TARGET_APP="$INSTALL_DIR/$APP_NAME"
BACKUP_APP="$INSTALL_DIR/.LeftoverAchievements.update-backup.app"
[[ -w "$INSTALL_DIR" ]] || fail_update "$(dirname "$CURRENT_APP") is not writable. Move LeftoverAchievements to Applications and try again."

UPDATE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/leftover-macos-update.XXXXXX")"
DISK_IMAGE="$UPDATE_ROOT/update.dmg"
MOUNT_POINT="$UPDATE_ROOT/mount"
NEW_APP="$UPDATE_ROOT/$APP_NAME"
MOUNTED=0
cleanup() {
  if [[ "$MOUNTED" == 1 ]]; then
    /usr/bin/hdiutil detach "$MOUNT_POINT" -quiet 2>/dev/null || true
  fi
  rm -rf "$UPDATE_ROOT"
}
trap cleanup EXIT
mkdir -p "$MOUNT_POINT"

set_phase downloading
/usr/bin/curl --fail --location --silent --show-error "$ASSET_URL" --output "$DISK_IMAGE" \
  || fail_update "the release could not be downloaded."

set_phase validating
/usr/bin/hdiutil attach -readonly -nobrowse -mountpoint "$MOUNT_POINT" "$DISK_IMAGE" >/dev/null \
  || fail_update "the release disk image could not be opened."
MOUNTED=1
MOUNTED_APP="$MOUNT_POINT/$APP_NAME"
[[ -d "$MOUNTED_APP" ]] || fail_update "the release does not contain LeftoverAchievements.app."
/usr/bin/ditto "$MOUNTED_APP" "$NEW_APP" || fail_update "the application could not be copied from the release."
/usr/bin/hdiutil detach "$MOUNT_POINT" -quiet || fail_update "the release disk image could not be closed."
MOUNTED=0

NEW_EXECUTABLE="$NEW_APP/Contents/MacOS/LeftoverAchievements"
[[ -x "$NEW_EXECUTABLE" ]] || fail_update "the release does not contain LeftoverAchievements.app."

EMBEDDED_VERSION="$(head -n 1 "$NEW_APP/Contents/Resources/build-version.txt" 2>/dev/null || true)"
[[ "$EMBEDDED_VERSION" == "$VERSION" ]] || fail_update "the downloaded version does not match the release."
ACTUAL_ARCH="$(/usr/bin/lipo -archs "$NEW_EXECUTABLE" 2>/dev/null || true)"
[[ "$ACTUAL_ARCH" == x86_64 ]] && ACTUAL_ARCH=x64
[[ "$ACTUAL_ARCH" == "$EXPECTED_ARCH" ]] || fail_update "the downloaded app is for $ACTUAL_ARCH, not $EXPECTED_ARCH."
BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$NEW_APP/Contents/Info.plist" 2>/dev/null || true)"
[[ "$BUNDLE_ID" == com.leftoverachievements.server ]] || fail_update "the downloaded application identity is invalid."

set_phase preparing
/bin/kill -TERM "$APP_PID" 2>/dev/null || true
for _attempt in {1..40}; do
  /bin/kill -0 "$APP_PID" 2>/dev/null || break
  /bin/sleep 0.5
done
if /bin/kill -0 "$APP_PID" 2>/dev/null; then
  /bin/kill -KILL "$APP_PID" 2>/dev/null || true
  /bin/sleep 1
fi

set_phase applying
rm -rf "$BACKUP_APP"
if [[ -e "$TARGET_APP" ]]; then
  mv "$TARGET_APP" "$BACKUP_APP" || fail_update "the existing application could not be backed up."
fi
if ! mv "$NEW_APP" "$TARGET_APP"; then
  [[ -e "$BACKUP_APP" ]] && mv "$BACKUP_APP" "$TARGET_APP"
  fail_update "the new application could not be installed."
fi

set_phase restarting
if ! /usr/bin/open "$TARGET_APP"; then
  rm -rf "$TARGET_APP"
  [[ -e "$BACKUP_APP" ]] && mv "$BACKUP_APP" "$TARGET_APP"
  [[ -e "$TARGET_APP" ]] && /usr/bin/open "$TARGET_APP" || true
  fail_update "the updated application could not be opened; the previous version was restored."
fi

rm -rf "$BACKUP_APP"
if [[ "$CURRENT_APP" != "$TARGET_APP" ]]; then
  rm -rf "$CURRENT_APP"
fi
echo "Installed $APP_NAME $VERSION successfully."
