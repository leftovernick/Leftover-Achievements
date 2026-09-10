# Build with scripts/build-macos.sh; environment variables are set by that script.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH).parent
artifact_name = os.environ["LEFTOVER_ARTIFACT_NAME"]
version_file = os.environ["LEFTOVER_BUILD_VERSION_FILE"]
architecture_file = os.environ["LEFTOVER_BUILD_ARCHITECTURE_FILE"]

a = Analysis(
    [str(project_root / "macos_menu.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "templates"), "templates"),
        (str(project_root / "static"), "static"),
        (version_file, "."),
        (architecture_file, "."),
    ],
    hiddenimports=collect_submodules("uvicorn") + ["AppKit", "Foundation", "UserNotifications", "objc"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=artifact_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=artifact_name,
)
app = BUNDLE(
    collection,
    name=f"{artifact_name}.app",
    bundle_identifier="com.leftoverachievements.server",
    info_plist={
        "CFBundleName": "LeftoverAchievements",
        "CFBundleDisplayName": "LeftoverAchievements",
        "CFBundleShortVersionString": Path(version_file).read_text().strip().lstrip("v"),
        "CFBundleVersion": Path(version_file).read_text().strip().lstrip("v"),
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
)
