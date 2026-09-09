#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${1:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
TARGET_TAG="${2:-}"
VENV_DIR="$PROJECT_ROOT/.venv"
STATUS_FILE="$PROJECT_ROOT/.update-status"
SERVICE_NAME="leftover-achievements.service"

set_phase() {
  printf '%s\n' "$1" > "$STATUS_FILE"
}

abort_update() {
  set_phase failed
  echo "Error: $1" >&2
  exit 1
}

fail_update() {
  status=$?
  set_phase failed
  echo "Update failed near line ${BASH_LINENO[0]} (exit ${status})." >&2
  exit "$status"
}
trap fail_update ERR

echo "[$(date -Iseconds)] Preparing application update."
set_phase preparing
cd "$PROJECT_ROOT"

if [[ -z "$TARGET_TAG" ]]; then
  abort_update "a release tag is required."
fi
if [[ ! "$TARGET_TAG" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+([.+-][0-9A-Za-z.-]+)?$ ]]; then
  abort_update "the requested release tag is not a valid version."
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  abort_update "tracked local changes are present; refusing to update."
fi
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  abort_update "expected virtual environment at $VENV_DIR."
fi
if ! sudo -n -l /usr/bin/systemctl restart "$SERVICE_NAME" >/dev/null 2>&1; then
  abort_update "the service user is not permitted to restart $SERVICE_NAME; install the provided sudoers rule."
fi

echo "Fetching stable release tag $TARGET_TAG."
git fetch --quiet origin "refs/tags/$TARGET_TAG:refs/tags/$TARGET_TAG"
git rev-parse --verify --quiet "refs/tags/$TARGET_TAG^{commit}" >/dev/null

INSTALLED_TAG="$(git tag --points-at HEAD | "$VENV_DIR/bin/python" -c '
import sys
from packaging.version import InvalidVersion, Version
versions = []
for raw in sys.stdin:
    tag = raw.strip()
    normalized = tag[1:] if tag.lower().startswith("v") else tag
    try:
        version = Version(normalized)
    except InvalidVersion:
        continue
    if not version.is_prerelease and not version.is_devrelease:
        versions.append((version, tag))
print(max(versions)[1] if versions else "")
')"

"$VENV_DIR/bin/python" -c '
import sys
from packaging.version import InvalidVersion, Version
target_tag, installed_tag = sys.argv[1:]
def parse(tag):
    value = tag[1:] if tag.lower().startswith("v") else tag
    try:
        version = Version(value)
    except InvalidVersion as exc:
        raise SystemExit(f"Invalid release version {tag}: {exc}")
    if version.is_prerelease or version.is_devrelease:
        raise SystemExit("Prerelease versions cannot be installed on the stable channel.")
    return version
target = parse(target_tag)
if installed_tag and target <= parse(installed_tag):
    raise SystemExit(f"Release {target_tag} is not newer than installed {installed_tag}.")
' "$TARGET_TAG" "$INSTALLED_TAG"

set_phase installing
echo "Checking out release $TARGET_TAG in detached HEAD mode."
git switch --detach "$TARGET_TAG"
echo "Installing Python requirements."
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_ROOT/requirements.txt"

set_phase restarting
echo "Update installed successfully; restarting $SERVICE_NAME."
sudo -n /usr/bin/systemctl restart "$SERVICE_NAME"
