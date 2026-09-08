#!/usr/bin/env bash
set -euo pipefail

DISPLAY_URL="${LEFTOVER_ACHIEVEMENTS_DISPLAY_URL:-http://127.0.0.1:8000/display}"
HEALTH_URL="${LEFTOVER_ACHIEVEMENTS_HEALTH_URL:-http://127.0.0.1:8000/display}"
RETRY_SECONDS="${LEFTOVER_ACHIEVEMENTS_RETRY_SECONDS:-2}"

if ! command -v curl >/dev/null 2>&1; then
  echo "Error: curl is required. Install it with: sudo apt install curl" >&2
  exit 1
fi

if command -v chromium >/dev/null 2>&1; then
  CHROMIUM="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
  CHROMIUM="$(command -v chromium-browser)"
else
  echo "Error: Chromium was not found. Install it with: sudo apt install chromium" >&2
  exit 1
fi

echo "Waiting for the LeftoverAchievements backend at $HEALTH_URL ..."
until curl --fail --silent --output /dev/null "$HEALTH_URL"; do
  sleep "$RETRY_SECONDS"
done

echo "Backend is ready; opening $DISPLAY_URL in Chromium kiosk mode."
exec "$CHROMIUM" \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --no-first-run \
  --disable-session-crashed-bubble \
  --autoplay-policy=no-user-gesture-required \
  --start-maximized \
  "$DISPLAY_URL"
