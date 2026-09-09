#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Error: the macOS package must be built on macOS." >&2
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Error: this initial macOS build targets Apple Silicon arm64." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYINSTALLER="$PROJECT_ROOT/.venv/bin/pyinstaller"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
VERSION="${LEFTOVER_BUILD_VERSION:-$(git -C "$PROJECT_ROOT" describe --tags --exact-match HEAD 2>/dev/null || true)}"

if [[ ! "$VERSION" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+([.+-][0-9A-Za-z.-]+)?$ ]]; then
  echo "Error: build from an exact stable version tag such as v1.2.0, or set LEFTOVER_BUILD_VERSION." >&2
  exit 1
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Error: project virtual environment is missing. Create .venv and install requirements-build.txt." >&2
  exit 1
fi
if ! "$PYTHON" -c '
import sys
from packaging.version import Version
value = sys.argv[1][1:] if sys.argv[1].lower().startswith("v") else sys.argv[1]
version = Version(value)
raise SystemExit(1 if version.is_prerelease or version.is_devrelease else 0)
' "$VERSION"; then
  echo "Error: packaged release builds require a stable semantic version." >&2
  exit 1
fi
if [[ ! -x "$PYINSTALLER" ]]; then
  echo "Error: PyInstaller is not installed. Run: .venv/bin/pip install -r requirements-build.txt" >&2
  exit 1
fi

ARTIFACT_NAME="LeftoverAchievements-macOS-arm64-$VERSION"
WORK_ROOT="$PROJECT_ROOT/build/pyinstaller-macos"
DIST_ROOT="$PROJECT_ROOT/dist"
RELEASE_ROOT="$DIST_ROOT/releases"
VERSION_DIR="$PROJECT_ROOT/build/packaging"
VERSION_FILE="$VERSION_DIR/build-version.txt"

rm -rf "$WORK_ROOT" "$DIST_ROOT/$ARTIFACT_NAME" "$DIST_ROOT/$ARTIFACT_NAME.app"
mkdir -p "$VERSION_DIR" "$RELEASE_ROOT"
printf '%s\n' "$VERSION" > "$VERSION_FILE"

export LEFTOVER_ARTIFACT_NAME="$ARTIFACT_NAME"
export LEFTOVER_BUILD_VERSION_FILE="$VERSION_FILE"
"$PYINSTALLER" --clean --noconfirm --workpath "$WORK_ROOT" --distpath "$DIST_ROOT" "$PROJECT_ROOT/packaging/macos.spec"

ZIP_PATH="$RELEASE_ROOT/$ARTIFACT_NAME.zip"
rm -f "$ZIP_PATH"
ditto -c -k --sequesterRsrc --keepParent "$DIST_ROOT/$ARTIFACT_NAME.app" "$ZIP_PATH"
"$PYTHON" "$PROJECT_ROOT/scripts/validate_release_package.py" \
  --platform macos --version "$VERSION" "$ZIP_PATH"
echo "Created $ZIP_PATH"
