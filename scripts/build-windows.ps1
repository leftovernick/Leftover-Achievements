param(
    [switch]$DebugConsole
)

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") {
    throw "The Windows package must be built on Windows."
}
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne "X64") {
    throw "This initial Windows build targets x64."
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PyInstaller = Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Version = $env:LEFTOVER_BUILD_VERSION
if (-not $Version) {
    $Version = (& git -C $ProjectRoot describe --tags --exact-match HEAD 2>$null)
}
if ($Version -notmatch '^v?[0-9]+\.[0-9]+\.[0-9]+([.+-][0-9A-Za-z.-]+)?$') {
    throw "Build from an exact stable version tag such as v1.2.0, or set LEFTOVER_BUILD_VERSION."
}
if (-not (Test-Path $Python)) {
    throw "Project virtual environment is missing. Create .venv and install requirements-build.txt."
}
& $Python -c "import sys; from packaging.version import Version; value=sys.argv[1][1:] if sys.argv[1].lower().startswith('v') else sys.argv[1]; version=Version(value); raise SystemExit(1 if version.is_prerelease or version.is_devrelease else 0)" $Version
if ($LASTEXITCODE -ne 0) {
    throw "Packaged release builds require a stable semantic version."
}
if (-not (Test-Path $PyInstaller)) {
    throw "PyInstaller is not installed. Run: .venv\Scripts\pip.exe install -r requirements-build.txt"
}

$ArtifactName = "LeftoverAchievements-Windows-x64-$Version"
$WorkRoot = Join-Path $ProjectRoot "build\pyinstaller-windows"
$DistRoot = Join-Path $ProjectRoot "dist"
$ReleaseRoot = Join-Path $DistRoot "releases"
$VersionDir = Join-Path $ProjectRoot "build\packaging"
$VersionFile = Join-Path $VersionDir "build-version.txt"
$ArtifactDir = Join-Path $DistRoot $ArtifactName
$ZipPath = Join-Path $ReleaseRoot "$ArtifactName.zip"

Remove-Item -Recurse -Force $WorkRoot, $ArtifactDir -ErrorAction SilentlyContinue
Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $VersionDir, $ReleaseRoot | Out-Null
Set-Content -Path $VersionFile -Value $Version -Encoding ASCII

$env:LEFTOVER_ARTIFACT_NAME = $ArtifactName
$env:LEFTOVER_BUILD_VERSION_FILE = $VersionFile
$env:LEFTOVER_BUILD_CONSOLE = if ($DebugConsole) { "1" } else { "0" }
& $PyInstaller --clean --noconfirm --workpath $WorkRoot --distpath $DistRoot (Join-Path $ProjectRoot "packaging_specs\windows.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

Compress-Archive -Path $ArtifactDir -DestinationPath $ZipPath -CompressionLevel Optimal
& $Python (Join-Path $ProjectRoot "scripts\validate_release_package.py") --platform windows --version $Version $ZipPath
if ($LASTEXITCODE -ne 0) {
    throw "Release package validation failed with exit code $LASTEXITCODE."
}
Write-Host "Created $ZipPath"
