# Build with scripts/build-macos.sh; environment variables are set by that script.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH).parent
artifact_name = os.environ["LEFTOVER_ARTIFACT_NAME"]
version_file = os.environ["LEFTOVER_BUILD_VERSION_FILE"]

a = Analysis(
    [str(project_root / "launcher.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "templates"), "templates"),
        (str(project_root / "static"), "static"),
        (version_file, "."),
    ],
    hiddenimports=collect_submodules("uvicorn"),
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
    target_arch="arm64",
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
        "CFBundleDisplayName": "LeftoverAchievements",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
)
