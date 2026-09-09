#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Error: the macOS package must be built on macOS." >&2
  exit 1
fi

case "$(uname -m)" in
  arm64) HOST_ARCH="arm64" ;;
  x86_64) HOST_ARCH="x64" ;;
  *)
    echo "Error: unsupported macOS host architecture: $(uname -m)." >&2
    exit 1
    ;;
esac
MACOS_ARCH="${MACOS_ARCH:-$HOST_ARCH}"
if [[ "$MACOS_ARCH" != "arm64" && "$MACOS_ARCH" != "x64" ]]; then
  echo "Error: MACOS_ARCH must be arm64 or x64." >&2
  exit 1
fi
if [[ "$MACOS_ARCH" != "$HOST_ARCH" ]]; then
  echo "Error: MACOS_ARCH=$MACOS_ARCH requires a native $MACOS_ARCH runner; this host is $HOST_ARCH." >&2
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

ARTIFACT_NAME="LeftoverAchievements-macOS-$MACOS_ARCH-$VERSION"
WORK_ROOT="$PROJECT_ROOT/build/pyinstaller-macos-$MACOS_ARCH"
DIST_ROOT="$PROJECT_ROOT/dist"
RELEASE_ROOT="$DIST_ROOT/releases"
VERSION_DIR="$PROJECT_ROOT/build/packaging"
VERSION_FILE="$VERSION_DIR/build-version.txt"
ARCHITECTURE_FILE="$VERSION_DIR/build-architecture.txt"

rm -rf "$WORK_ROOT" "$DIST_ROOT/$ARTIFACT_NAME" "$DIST_ROOT/$ARTIFACT_NAME.app"
mkdir -p "$VERSION_DIR" "$RELEASE_ROOT"
printf '%s\n' "$VERSION" > "$VERSION_FILE"
printf '%s\n' "$MACOS_ARCH" > "$ARCHITECTURE_FILE"

export LEFTOVER_ARTIFACT_NAME="$ARTIFACT_NAME"
export LEFTOVER_BUILD_VERSION_FILE="$VERSION_FILE"
export LEFTOVER_BUILD_ARCHITECTURE_FILE="$ARCHITECTURE_FILE"
"$PYINSTALLER" --clean --noconfirm --workpath "$WORK_ROOT" --distpath "$DIST_ROOT" "$PROJECT_ROOT/packaging_specs/macos.spec"

EXECUTABLE="$DIST_ROOT/$ARTIFACT_NAME.app/Contents/MacOS/$ARTIFACT_NAME"
if [[ ! -x "$EXECUTABLE" ]]; then
  echo "Error: expected packaged executable is missing: $EXECUTABLE" >&2
  exit 1
fi
ACTUAL_ARCH="$(/usr/bin/lipo -archs "$EXECUTABLE")"
if [[ "$ACTUAL_ARCH" == "x86_64" ]]; then
  ACTUAL_ARCH="x64"
fi
if [[ "$ACTUAL_ARCH" != "$MACOS_ARCH" ]]; then
  echo "Error: packaged executable architecture is $ACTUAL_ARCH; expected $MACOS_ARCH." >&2
  exit 1
fi

ZIP_PATH="$RELEASE_ROOT/$ARTIFACT_NAME.zip"
rm -f "$ZIP_PATH"
ditto -c -k --sequesterRsrc --keepParent "$DIST_ROOT/$ARTIFACT_NAME.app" "$ZIP_PATH"
"$PYTHON" "$PROJECT_ROOT/scripts/validate_release_package.py" \
  --platform macos --architecture "$MACOS_ARCH" --version "$VERSION" "$ZIP_PATH"
echo "Created $ZIP_PATH"
