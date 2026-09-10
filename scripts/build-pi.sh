#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VERSION="${LEFTOVER_BUILD_VERSION:-${1:-}}"
ARCH="$(uname -m)"

if [[ "$ARCH" != aarch64 && "${ALLOW_ARCHITECTURE_NEUTRAL_PI_BUILD:-0}" != 1 ]]; then
  echo "Error: Pi release builds must run on aarch64 (found $ARCH)." >&2
  exit 1
fi
if [[ ! "$VERSION" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: Pi release builds require a stable vX.Y.Z version." >&2
  exit 1
fi

ARTIFACT="LeftoverAchievements-Pi-arm64-$VERSION"
RELEASE_DIR="$PROJECT_ROOT/dist/releases"
STAGING_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/leftover-pi-build.XXXXXX")"
PACKAGE_ROOT="$STAGING_ROOT/$ARTIFACT"
ARCHIVE="$RELEASE_DIR/$ARTIFACT.tar.gz"
trap 'rm -rf "$STAGING_ROOT"' EXIT

mkdir -p "$PACKAGE_ROOT" "$RELEASE_DIR"
for file in app.py launcher.py runtime.py requirements.txt README.md .env.example; do
  install -m 0644 "$PROJECT_ROOT/$file" "$PACKAGE_ROOT/$file"
done
copy_runtime_tree() {
  local directory="$1" relative target mode
  while IFS= read -r -d '' relative; do
    [[ "${relative##*/}" == .gitkeep ]] && continue
    target="$PACKAGE_ROOT/$relative"
    mkdir -p "$(dirname "$target")"
    mode=0644
    [[ -x "$PROJECT_ROOT/$relative" ]] && mode=0755
    install -m "$mode" "$PROJECT_ROOT/$relative" "$target"
  done < <(git -C "$PROJECT_ROOT" ls-files -z --cached -- "$directory")
}
for directory in database services templates static; do
  copy_runtime_tree "$directory"
done
mkdir -p "$PACKAGE_ROOT/deploy"
for file in kiosk-loading.html leftover-achievements.service leftover-achievements-update.sudoers; do
  install -m 0644 "$PROJECT_ROOT/deploy/$file" "$PACKAGE_ROOT/deploy/$file"
done
mkdir -p "$PACKAGE_ROOT/scripts"
for script in \
  configure-pi-appliance-session.sh configure-pi-boot-branding.sh \
  pi-privileged-helper.sh pi_package.py run-kiosk-session.sh start-backend.sh \
  start-kiosk.sh update-app.sh; do
  install -m 0755 "$PROJECT_ROOT/scripts/$script" "$PACKAGE_ROOT/scripts/$script"
done
printf '%s\n' "$VERSION" > "$PACKAGE_ROOT/build-version.txt"
printf 'arm64\n' > "$PACKAGE_ROOT/build-architecture.txt"

find "$PACKAGE_ROOT" -name '.DS_Store' -delete
find "$PACKAGE_ROOT" -type d -name '__pycache__' -prune -exec rm -rf {} +
rm -f "$ARCHIVE"
if tar --version 2>/dev/null | grep -q 'GNU tar'; then
  tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
    -C "$STAGING_ROOT" -czf "$ARCHIVE" "$ARTIFACT"
else
  # Developer convenience on BSD/macOS; the release runner uses GNU tar above.
  COPYFILE_DISABLE=1 tar -C "$STAGING_ROOT" -czf "$ARCHIVE" "$ARTIFACT"
fi
VALIDATOR_PYTHON=python3
[[ -x "$PROJECT_ROOT/.venv/bin/python" ]] && VALIDATOR_PYTHON="$PROJECT_ROOT/.venv/bin/python"
"$VALIDATOR_PYTHON" "$PROJECT_ROOT/scripts/validate_release_package.py" \
  --platform pi --architecture arm64 --version "$VERSION" "$ARCHIVE"
echo "Built $ARCHIVE"
