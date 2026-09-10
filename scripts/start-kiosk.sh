#!/usr/bin/env bash
set -euo pipefail

DISPLAY_URL="${LEFTOVER_ACHIEVEMENTS_DISPLAY_URL:-http://127.0.0.1:8000/display}"
RETRY_SECONDS="${LEFTOVER_ACHIEVEMENTS_RETRY_SECONDS:-2}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SPLASH_PAGE="$PROJECT_ROOT/deploy/kiosk-loading.html"
DISABLE_MARKER="${XDG_CONFIG_HOME:-$HOME/.config}/leftover-achievements/disable-kiosk"
KIOSK_PROFILE="${XDG_CONFIG_HOME:-$HOME/.config}/leftover-achievements/chromium-kiosk"

if [[ -e "$DISABLE_MARKER" ]]; then
  echo "LeftoverAchievements kiosk is temporarily disabled by $DISABLE_MARKER."
  exit 0
fi

if command -v chromium >/dev/null 2>&1; then
  CHROMIUM="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
  CHROMIUM="$(command -v chromium-browser)"
else
  echo "Error: Chromium was not found. Install it with: sudo apt install chromium" >&2
  exit 1
fi

if [[ ! -f "$SPLASH_PAGE" ]]; then
  echo "Error: kiosk loading page was not found: $SPLASH_PAGE" >&2
  exit 1
fi

PYTHON="${PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON" ]]; then
  echo "Error: Python is required to prepare the kiosk loading URL." >&2
  exit 1
fi

SPLASH_URL="$("$PYTHON" -c '
import pathlib, sys, urllib.parse
page, display, retry = sys.argv[1:]
query = urllib.parse.urlencode({"display": display, "retry": str(float(retry) * 1000)})
print(pathlib.Path(page).resolve().as_uri() + "?" + query)
' "$SPLASH_PAGE" "$DISPLAY_URL" "$RETRY_SECONDS")"

echo "Opening the LeftoverAchievements kiosk loading screen."
mkdir -p "$KIOSK_PROFILE"
exec "$CHROMIUM" \
  --kiosk \
  --ozone-platform=wayland \
  --noerrdialogs \
  --disable-infobars \
  --no-first-run \
  --no-default-browser-check \
  --user-data-dir="$KIOSK_PROFILE" \
  --password-store=basic \
  --disable-session-crashed-bubble \
  --autoplay-policy=no-user-gesture-required \
  --start-maximized \
  "$SPLASH_URL"
