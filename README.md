# LeftoverAchievements Display

A small FastAPI dashboard for RetroAchievements, designed for local development on macOS and later deployment to a Raspberry Pi display.

## Features (initial)

- FastAPI app with Jinja2 templates
- SQLite database for tracked users
- Admin UI to add/remove RetroAchievements users
- Dashboard showing a simple leaderboard ranked by Hardcore points
- Plain HTML, CSS, and JavaScript with no frontend framework

## macOS development setup

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install requirements:

```bash
pip install -r requirements.txt
```

3. Run the FastAPI app:

```bash
uvicorn app:app --reload --timeout-graceful-shutdown 1
```

4. Open http://127.0.0.1:8000/ in your browser. A new installation opens the guided
setup automatically. The guide verifies a RetroAchievements Web API key, adds the
first tracked players, and confirms that the display is ready without requiring file
edits.

After setup, the main pages are:

- Dashboard: http://127.0.0.1:8000/
- Admin: http://127.0.0.1:8000/admin
- Display: http://127.0.0.1:8000/display

## Notes

- `RA_API_KEY` in `.env` remains supported as an optional legacy fallback, but is not
  required for normal setup. Do not commit your `.env` file (it's in `.gitignore`).
- The app will create a local SQLite database at `database/leftover.db` automatically.
- The admin page validates users through `API_GetUserProfile.php`, the official RetroAchievements profile endpoint.
- The one-second graceful-shutdown limit lets the development server reload even while the display page has an open live-events connection.

## Packaged desktop server

The macOS and Windows packages include Python and all runtime dependencies. They run
LeftoverAchievements as a local server without kiosk mode, a dashboard window, or an
automatically opened browser. On macOS, launching the app creates a native monochrome
trophy in the menu bar and no Dock icon. Its menu reports server and update status,
opens the Dashboard or Display in the default browser, copies the preferred LAN
address, checks for updates, and quits the backend cleanly. Windows continues to run
as a headless server. Open http://127.0.0.1:8000/ yourself on Windows, or use the
macOS menu command. Other devices on the same trusted LAN can use the LAN address
recorded in the application log. `/display` remains available when a desktop user
intentionally opens it.

First launch uses the same browser-based onboarding as the Pi. The API key, users,
settings, history, custom audio, and database are persisted outside the package:

- macOS: `~/Library/Application Support/LeftoverAchievements/`
- Windows: `%LOCALAPPDATA%\LeftoverAchievements\`

Rotating logs are stored in the `logs` subdirectory as
`leftover-achievements.log`. The log records the localhost URL, detected LAN URL,
startup errors, and shutdown without recording API keys. Launching a second copy
exits cleanly when the instance lock is already owned. On macOS, a backend startup
failure leaves the menu bar app available with `Server: Failed` instead of appearing
as an unresponsive foreground app.

Packaged builds can check GitHub Releases and show newer versions. Self-replacement
is deliberately not implemented yet: **Update Now** is hidden and Settings explains
that the matching release ZIP must be downloaded manually. Packaged builds never run
the Pi git checkout, pip installation, sudo, or systemd update path.

### Build requirements

Install the build-only dependencies in the project virtual environment:

```bash
pip install -r requirements-build.txt
```

On macOS, the runtime requirements install PyObjC/AppKit. To exercise the menu bar
wrapper without building an `.app`, use packaged-style data isolation on a free port:

```bash
LEFTOVER_RUNTIME_MODE=macos_packaged \
LEFTOVER_PORT=8000 \
python macos_menu.py
```

This does not replace the normal `uvicorn` development command. The wrapper does not
open a browser automatically; choose **Open Dashboard** or **Open Display** from its
menu. Its status icon uses the system `trophy.fill` symbol as a template image, so no
separate colored menu-bar asset is required and macOS adapts it for light/dark menus.

Packaged macOS builds can also deliver native Notification Center alerts for
achievement unlocks, beaten games, mastered games, and available app updates. Open
**Settings → Notifications**, choose the event categories, and save with **Enable
macOS Notifications** selected to request the normal macOS permission. The app does
not ask at launch, a denial does not affect the server or display, and display popup
audio remains a separate preference. Each RetroAchievements event is notified at
most once, and each available release version is announced once. Clicking a
notification opens the local dashboard.

Build on the target operating system; PyInstaller does not cross-compile. Both build
scripts derive the version from the exact Git tag at HEAD. CI or a test build may
instead provide `LEFTOVER_BUILD_VERSION=v1.2.0`; end users never edit a version file.
The PyInstaller definitions live in `packaging_specs/macos.spec` and
`packaging_specs/windows.spec`; the directory deliberately avoids the name of the
third-party Python `packaging` dependency used for release-version validation.

On an Apple Silicon Mac, build the native arm64 package:

```bash
MACOS_ARCH=arm64 ./scripts/build-macos.sh
```

This produces
`dist/releases/LeftoverAchievements-macOS-arm64-v1.2.0.zip`. The contained `.app`
runs without a main window or Dock icon. It is not Developer ID signed or notarized,
so downloaded builds may require **Control-click → Open** in Finder or approval in
**System Settings → Privacy & Security**. Signing and notarization are intentionally
deferred.

On an Intel Mac, build the native x64 package instead:

```bash
MACOS_ARCH=x64 ./scripts/build-macos.sh
```

This produces
`dist/releases/LeftoverAchievements-macOS-x64-v1.2.0.zip`. The build script refuses
to cross-compile: `arm64` must run on Apple Silicon and `x64` must run on Intel.

Choose the macOS download that matches the computer:

- Macs with M1, M2, M3, M4, or newer Apple Silicon use the **macOS arm64** ZIP.
- Macs with an Intel processor use the **macOS x64** ZIP.

These are separate native builds, not a combined universal2 application.

On Windows x64, run PowerShell from the repository:

```powershell
.\scripts\build-windows.ps1
```

This creates the reliable one-directory build and archives it as
`dist\releases\LeftoverAchievements-Windows-x64-v1.2.0.zip`. The normal executable
has no console window. For startup diagnosis, build a console-enabled variant with:

```powershell
.\scripts\build-windows.ps1 -DebugConsole
```

Publishing a stable GitHub Release automatically invokes these same scripts in the
`Build packaged release assets` workflow. Independent native jobs build Apple
Silicon macOS on `macos-15`, Intel macOS on `macos-15-intel`, and Windows x64 on
`windows-latest`. A fourth job builds the Pi source bundle on GitHub's native
`ubuntu-24.04-arm` runner. Each job checks out the Release tag explicitly, embeds that
exact tag, validates its archive, and attaches one predictably named
asset to the same Release:

- `LeftoverAchievements-macOS-arm64-v1.2.0.zip`
- `LeftoverAchievements-macOS-x64-v1.2.0.zip`
- `LeftoverAchievements-Windows-x64-v1.2.0.zip`
- `LeftoverAchievements-Pi-arm64-v1.2.0.tar.gz`

Rerunning a job replaces its existing same-named asset. A failed job uploads
nothing, and does not prevent the other platform job from producing its asset.
Drafts and prereleases do not produce stable packages. Normal pushes to `main` do
not run this workflow or produce distributable packages. The workflow uses its
built-in `GITHUB_TOKEN`; no personal access token or release-note generation is
involved.

## Raspberry Pi 4/5 deployment

Use Raspberry Pi OS 64-bit with Desktop. Current Raspberry Pi OS desktop images use
Wayland with the labwc window manager and include Chromium. The backend runs as a
systemd service. Production appliance mode selects a separate minimal labwc session;
the normal Raspberry Pi desktop, panel, file manager, and wallpaper are not started.

### 1. Fresh install from a GitHub Release

In Raspberry Pi Imager, select **Raspberry Pi OS (64-bit) with Desktop** and configure
the normal user, networking, and SSH. Boot once, confirm networking works, then run
this single command as the normal user (do not prefix it with `sudo`):

```bash
curl -fsSL https://raw.githubusercontent.com/leftovernick/Leftover-Achievements/main/scripts/bootstrap-pi.sh | bash
```

After successful validation, the bootstrap announces a ten-second countdown and
reboots the Pi automatically. No second command is required. Press Ctrl+C during that
delay to leave the completed installation running without rebooting. After the Pi
returns, open `http://<raspberry-pi-hostname>.local:8000/` from another device to
finish onboarding.

The bootstrap requires Raspberry Pi OS `aarch64`. It installs prerequisites, queries
the latest stable GitHub Release, selects only its matching Pi ARM64 asset, validates
the archive and embedded version, builds a release-specific virtual environment, and
atomically selects the release. It then configures systemd, the narrow privileged
migration helper, and the dedicated kiosk session. Raspberry Pi boot configuration
is deliberately left unchanged. Git and manual configuration-file editing are not
required.

For development or troubleshooting, suppress the automatic reboot with either form:

```bash
curl -fsSL https://raw.githubusercontent.com/leftovernick/Leftover-Achievements/main/scripts/bootstrap-pi.sh | LEFTOVER_ACHIEVEMENTS_NO_REBOOT=1 bash
curl -fsSL https://raw.githubusercontent.com/leftovernick/Leftover-Achievements/main/scripts/bootstrap-pi.sh | bash -s -- --no-reboot
```

The installer then prints the manual reboot command but still treats the installation
as successful. Automatic reboot is exclusive to bootstrap and is not used for normal
updates started from the dashboard.

After installation, open the dashboard from another device on the same network and
follow the setup guide. Before setup is complete, the Pi display shows the setup URL,
device address, and a QR code instead of an empty carousel. An existing `RA_API_KEY`
in `.env` can still be verified by the guide until a key is saved through the web UI.

### 2. Installed layout

Application releases are stored under
`~/.local/share/LeftoverAchievements/app/releases/vX.Y.Z/`. The atomic
`~/.local/share/LeftoverAchievements/app/current` symlink selects the active release.
Persistent state is separate under `~/.local/share/LeftoverAchievements/data/`,
including `leftover.db`, `.env`, custom audio, updater state, and logs. Updates never
replace this data directory.

The production launcher binds Uvicorn to `0.0.0.0:8000` without reload mode. The Pi
uses `http://127.0.0.1:8000/display`; another device on the same LAN can open the
dashboard at `http://<raspberry-pi-ip>:8000/`. This deployment does not add
authentication, so only expose port 8000 on a trusted network.

### 3. Dedicated labwc appliance session

The bootstrap installs a `leftover-achievements` Wayland session and selects it in a
small LightDM override. Current Raspberry Pi OS can give active session assignments
in `/etc/lightdm/lightdm.conf` precedence over that drop-in, so the installer also
changes only active `user-session` and `autologin-session` values in the main file.
It preserves `autologin-user`, comments, and every unrelated LightDM setting. The
original session values are recorded once under `/etc/leftover-achievements/`, making
repeated installs idempotent and allowing appliance-mode recovery to restore the prior
desktop session.

The appliance session runs labwc with a private configuration directory under
`/etc/leftover-achievements/labwc`; its autostart contains the kiosk and optional
`kanshi`/`swaybg` support only. It does not source the Raspberry Pi desktop labwc
configuration, so `wf-panel-pi`, PCManFM, desktop icons, and the normal wallpaper are
not rendered underneath Chromium. A legacy `start-kiosk.sh` line is removed from the
user desktop autostart after a one-time backup, preventing duplicate browsers.

The kiosk launcher opens Chromium immediately onto a local, dark
LeftoverAchievements loading screen. That page checks the local backend every two
seconds and replaces itself with `http://127.0.0.1:8000/display` as soon as it is
ready. Chromium uses kiosk, basic password-store, no-first-run, no-error-dialog,
autoplay, native Wayland, a dedicated kiosk profile, and maximized-window flags, so a
new keyring or first-run prompt does not interrupt startup. The session supplies a
transparent Xcursor theme, scoped only to the appliance session; `/display` also uses
`cursor: none` as defense in depth. Touch and pointer gestures continue to work.

### 4. Reliability-first boot

The default installer does not modify `/boot/config.txt`,
`/boot/firmware/config.txt`, either `cmdline.txt`, Plymouth, firmware splash settings,
or initramfs images. It does not install `rpi-splash-screen-support`, add quiet-boot or
`fullscreen_logo` parameters, or use kernel command-line cursor suppression.

This is intentional. Real Raspberry Pi 4 testing with a DSI touchscreen showed that
early splash customization could fail before networking and SSH became available,
and an earlier initramfs/fullscreen-logo approach could expose crash or backtrace
output on the framebuffer. A normal Raspberry Pi OS boot screen is accepted to keep
boot, networking, SSH, and recovery reliable. Early branded splash is not a supported
or recommended option, especially on DSI displays.

The intended handoff is:

`Raspberry Pi OS boot visuals` → `LeftoverAchievements loading page` → `/display`

1. Raspberry Pi OS shows its normal boot visuals.
2. LightDM enters the dedicated LeftoverAchievements labwc session instead of the
   normal desktop shell.
3. Chromium opens the dark branded local loading screen.
4. The loading screen transitions to `/display` when the backend is ready.

Re-running the installer remains idempotent. The appliance session does not mask boot,
getty, display-manager, or emergency services, so SSH and alternate virtual consoles
remain available. Check the post-boot appliance configuration with:

```bash
cd ~/.local/share/LeftoverAchievements/app/current
sudo ./scripts/configure-pi-appliance-session.sh status "$(id -un)" "$PWD"
```

### 5. Automatic reboot and verification

Only after the package, dependencies, migration, systemd service, kiosk session, and
local `/display` health check succeed does bootstrap flush pending writes and begin
the ten-second reboot countdown. Any failure exits without rebooting. Ctrl+C cancels
only the pending reboot and prints the command to use later.

Expected boot sequence:

1. systemd waits for the network-online target, starts FastAPI, and restarts it after
   a crash.
2. Raspberry Pi OS may show its normal boot screen while hardware and services start.
3. LightDM logs the configured user directly into the dedicated minimal labwc
   appliance session; the normal Raspberry Pi desktop is not launched.
4. labwc displays the dark branded background and starts the matching local loading
   screen without a panel, wallpaper, terminal, or browser chrome.
5. The loading screen opens `/display` when FastAPI is ready.
6. The dashboard remains available to other devices on the LAN.

A temporary loss of internet connectivity does not prevent Chromium from reaching the
local FastAPI page. Live RetroAchievements data and remote artwork naturally require
internet connectivity and will recover through the application's existing polling.

Useful service commands:

```bash
sudo systemctl status leftover-achievements
sudo systemctl restart leftover-achievements
journalctl -u leftover-achievements
```

The production launcher signals active `/display/events` streams before Uvicorn
begins its graceful connection wait. SSE queue waits are cancellable, and Chromium's
native `EventSource` reconnects automatically after the replacement backend is
listening. Uvicorn has an eight-second graceful-shutdown ceiling; the service
template's `TimeoutStopSec=12s` remains a last-resort systemd safety net rather than
the normal shutdown mechanism. An existing local `TimeoutStopSec=10s` override is
also safe to retain.

### Troubleshooting and recovery

To temporarily return to the normal OS desktop, run these commands over SSH or from
an alternate console:

```bash
cd ~/.local/share/LeftoverAchievements/app/current
sudo ./scripts/configure-pi-appliance-session.sh disable
sudo reboot
```

Disabling removes the LeftoverAchievements drop-in and session entry, and restores
the saved active session values in `/etc/lightdm/lightdm.conf` (normally
`rpd-labwc`). It does not replace the whole LightDM file or change the configured
autologin user.

Re-enable and verify appliance mode when troubleshooting is complete:

```bash
cd ~/.local/share/LeftoverAchievements/app/current
sudo ./scripts/configure-pi-appliance-session.sh enable "$(id -un)" "$PWD"
sudo ./scripts/configure-pi-appliance-session.sh status "$(id -un)" "$PWD"
sudo reboot
```

To boot to a text console, use `sudo raspi-config` and select **System Options →
Boot / Auto Login → Console**, or run `sudo raspi-config nonint do_boot_behaviour
B1`. Restore desktop auto-login with the same menu or
`sudo raspi-config nonint do_boot_behaviour B4`. SSH is unaffected by either mode.
On an attached keyboard, Ctrl+Alt+F2 also reaches an alternate console.

If an older LeftoverAchievements installation modified early-boot settings, recover
only the known project-managed changes with:

```bash
cd ~/.local/share/LeftoverAchievements/app/current
sudo ./scripts/configure-pi-boot-branding.sh restore-default
sudo reboot
```

The helper removes the project's marked `config.txt` blocks and known old kernel
arguments. When the old installer backup exists, it uses that evidence to preserve
pre-existing arguments and restore `console=tty1`, `quiet`, or `splash` only when they
were originally present. It preserves unrelated configuration and does not delete or
rebuild initramfs files. Files from an older splash-support package may therefore
remain installed but become inactive once their kernel arguments are removed. Because
an interrupted or manually altered historical install cannot always be reconstructed
exactly, reflashing the SD card remains the safest recovery if the Pi still fails
before networking starts.

### Application updates

The backend checks the public GitHub Releases API every five minutes and caches the
latest published stable release. Drafts, prereleases, and ordinary commits pushed to
`main` do not create update notifications. Release tags use semantic versions such
as `v1.2.0`, so `v1.10.0` correctly compares newer than `v1.9.0`. No GitHub token is
required for the public repository.

When an update is available, use **Settings → Application Update** from the web
dashboard or swipe down from the top edge of the touchscreen and choose **Update**.
The updater downloads the matching Pi ARM64 TAR.GZ into temporary staging, validates
its paths, platform, embedded version, and exclusions, then builds dependencies inside
the new version directory. Only after all of that succeeds does it atomically replace
the `current` symlink, apply vetted system configuration, and restart the service.
Progress reports Downloading, Validating, Preparing, Installing, Applying system
changes, Restarting, and Reconnecting. No Git command or working tree is involved.

The bootstrap installs a root-owned helper at
`/usr/local/sbin/leftover-achievements-migrate`. Its sudo rule allows the appliance
user to invoke only its argument-free `apply` action and restart the one managed
service. The helper derives paths from a root-owned user record, rejects releases
outside the fixed version directory, validates version/architecture metadata, and
writes only the LeftoverAchievements service, kiosk-session selection, and sudoers
files. For future explicit migrations it can refresh only the helper shipped at the
active stable tag from the fixed LeftoverAchievements GitHub repository; it validates
the helper identity and shell syntax before installing it. It cannot run an arbitrary
command, URL, or path supplied by the application.

If archive validation, dependency installation, system application, or service
restart fails, the prior version remains selected or is restored. Persistent data is
never part of the staged release.

### Existing Git-checkout migration

For the currently deployed `~/Leftover-Achievements` Pi, run the same bootstrap once:

```bash
curl -fsSL https://raw.githubusercontent.com/leftovernick/Leftover-Achievements/main/scripts/bootstrap-pi.sh | bash
```

It detects `~/Leftover-Achievements` and `~/LeftoverAchievements`, copies `.env`, the
configured/default SQLite database, and `custom-*` audio only when the destination is
empty, and migrates an environment-only RA API key into the database. Onboarding,
tracked users, histories, cached event deduplication, and settings therefore survive.
After validating the migrated packaged installation, bootstrap uses the same automatic
reboot countdown as a fresh install.
The old checkout is not deleted; keep it until the packaged installation has been
verified, then archive or remove it manually if desired. All later updates use release
assets and require no Git checkout.

#### Publishing a release with GitHub Desktop

Normal development does not require release commands: make changes locally, commit
them in GitHub Desktop, and push to `main`. The Pi will do nothing merely because
`main` contains newer commits.

When a build is ready for users:

1. Commit and push the desired release commit with GitHub Desktop.
2. Verify that commit appears on GitHub and is the exact revision to ship.
3. Open the repository on GitHub.com and choose **Releases → Draft a new release**.
4. Create or select a semantic version tag such as `v1.2.0`.
5. Target the desired commit (normally the verified commit on `main`).
6. Write the human-authored release title and notes.
7. Leave **Set as a pre-release** off, then publish the Release.
8. Open the **Actions** tab and follow all four package jobs.
9. Confirm that the macOS arm64, macOS x64, Windows x64, and Pi arm64 assets appear
   under the same Release.
10. Installed LeftoverAchievements devices detect that stable published version.

Publishing the Release is the explicit **ship this version** action. Ordinary commits
and pushes never create device updates or desktop packages. After publication, a Pi
detects the tag during its next check and waits for the user to install it from Quick
Settings or web Settings. Packaged desktop installations detect the matching attached
ZIP and direct the user to download it manually. No command-line Git is needed to
publish releases. Packaged Pi paths are stable and do not need editing when releases
change.
