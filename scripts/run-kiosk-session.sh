#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STOP=0
trap 'STOP=1' TERM INT HUP

# Keep Chromium available if it exits unexpectedly. The local loading page is
# always its first document, so restarts never expose a white browser surface.
while (( ! STOP )); do
  "$SCRIPT_DIR/start-kiosk.sh"
  status=$?
  (( STOP )) && break
  if (( status == 0 )) && [[ -e "${XDG_CONFIG_HOME:-$HOME/.config}/leftover-achievements/disable-kiosk" ]]; then
    break
  fi
  sleep 2 &
  wait $! || true
done
