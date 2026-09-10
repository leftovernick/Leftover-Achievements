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
`windows-latest`. Each job checks out the Release tag explicitly, embeds that exact
tag, validates the ZIP contents and frozen server, and attaches one predictably named
asset to the same Release:

- `LeftoverAchievements-macOS-arm64-v1.2.0.zip`
- `LeftoverAchievements-macOS-x64-v1.2.0.zip`
- `LeftoverAchievements-Windows-x64-v1.2.0.zip`

Rerunning a job replaces its existing same-named asset. A failed job uploads
nothing, and does not prevent the other platform job from producing its asset.
Drafts and prereleases do not produce stable packages. Normal pushes to `main` do
not run this workflow or produce distributable packages. The workflow uses its
built-in `GITHUB_TOKEN`; no personal access token or release-note generation is
involved.

## Raspberry Pi 4/5 deployment

Use Raspberry Pi OS 64-bit with Desktop. Current Raspberry Pi OS desktop images use
Wayland with the labwc window manager and include Chromium. The backend runs as a
systemd service; Chromium starts after desktop login and waits for the local backend
before opening the display.

### 1. Clone and install

On the Raspberry Pi, clone the repository into a permanent location owned by the
normal desktop user. The examples below use `~/LeftoverAchievements`:

```bash
git clone YOUR_REPOSITORY_URL ~/LeftoverAchievements
cd ~/LeftoverAchievements
./scripts/install-pi.sh
```

The installer creates `.venv`, installs `requirements.txt`, ensures the local database
directory exists, marks the launch scripts executable, and creates `.env` from
`.env.example` only when `.env` does not already exist. It reports an `apt` command if
`curl`, Chromium, or Python venv support is missing.

After installation, open the dashboard from another device on the same network and
follow the setup guide. Before setup is complete, the Pi display shows the setup URL,
device address, and a QR code instead of an empty carousel. An existing `RA_API_KEY`
in `.env` can still be verified by the guide until a key is saved through the web UI.

Keep `LEFTOVER_ACHIEVEMENTS_DB_PATH=database/leftover.db` to store persistent SQLite
data inside the project. Relative database paths are resolved from the project root;
an absolute path may be used instead. If the variable is omitted, the existing macOS
default remains `database/leftover.db`. Back up this file when preserving user and
achievement history matters.

### 2. Install the backend service

Copy the service template and edit its placeholders:

```bash
sudo cp deploy/leftover-achievements.service /etc/systemd/system/leftover-achievements.service
sudo nano /etc/systemd/system/leftover-achievements.service
```

Replace every `YOUR_USER` with the normal, non-root desktop username. If the repository
is not at `/home/YOUR_USER/LeftoverAchievements`, replace all three project paths with
the absolute output of `pwd` from the repository directory. Then enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now leftover-achievements
sudo systemctl status leftover-achievements
```

The production launcher binds Uvicorn to `0.0.0.0:8000` without reload mode. The Pi
uses `http://127.0.0.1:8000/display`; another device on the same LAN can open the
dashboard at `http://<raspberry-pi-ip>:8000/`. This deployment does not add
authentication, so only expose port 8000 on a trusted network.

### 3. Configure the labwc kiosk autostart

Enable desktop auto-login using Raspberry Pi Imager during OS setup, the desktop
Control Centre, or `sudo raspi-config` (`System Options` → `Boot / Auto Login` →
desktop autologin).

The current Raspberry Pi OS labwc user autostart file is documented in the
[official Raspberry Pi kiosk guide](https://www.raspberrypi.com/tutorials/how-to-use-a-raspberry-pi-in-kiosk-mode/):

```text
~/.config/labwc/autostart
```

Create the directory/file if needed, then copy the command from
`deploy/labwc-autostart` into the existing autostart file. Replace `YOUR_USER` and the
example project path just as you did for the systemd unit. Do not replace an existing
autostart file; append the kiosk command to it. For example:

```bash
mkdir -p ~/.config/labwc
nano ~/.config/labwc/autostart
```

The resulting entry should resemble:

```sh
/home/your-user/LeftoverAchievements/scripts/start-kiosk.sh &
```

The kiosk launcher opens Chromium immediately onto a local, dark
LeftoverAchievements loading screen. That page checks the local backend every two
seconds and replaces itself with `http://127.0.0.1:8000/display` as soon as it is
ready. Chromium uses kiosk, basic password-store, no-first-run, no-error-dialog,
autoplay, and maximized-window flags, so a new keyring or first-run prompt does not
interrupt startup. Internet access is not required to open the local page.

### 4. Branded boot splash

On Raspberry Pi hardware, `install-pi.sh` also enables the branded early boot splash.
It installs Raspberry Pi OS's supported `rpi-splash-screen-support` package when
needed, suppresses the firmware rainbow screen with `disable_splash=1`, validates
and installs `deploy/boot/leftover-achievements-splash.tga`, and rebuilds the
initramfs. The supplied TGA is a dark 1280×720 derivative of the existing project
logo, not a separate logo design.

The intended handoff is:

1. Firmware starts with its display suppressed where supported.
2. The kernel draws the centered LeftoverAchievements early splash.
3. Chromium starts on the matching local loading screen.
4. The loading screen transitions to `/display` when the backend is ready.

The official helper preserves the original kernel command line as
`/boot/firmware/cmdline.txt.bak` (or `/boot/cmdline.txt.bak` on older images).
The installer does not mask boot, getty, display-manager, or emergency services.
SSH and alternate virtual consoles therefore remain available.

Check or reapply the branding with:

```bash
sudo ./scripts/configure-pi-boot-branding.sh status
sudo ./scripts/configure-pi-boot-branding.sh enable
```

Very early firmware, monitor-link training, and display-driver initialization happen
before Linux can draw the custom image. A short black frame can therefore remain.
Some DSI displays whose driver is unavailable in the initramfs may not show the early
image; they remain dark until the graphical session starts. The project deliberately
does not patch firmware or add an unsupported framebuffer hack for those frames.

### 5. Reboot and verify

```bash
sudo reboot
```

Expected boot sequence:

1. systemd waits for the network-online target, starts FastAPI, and restarts it after
   a crash.
2. The branded early splash covers normal kernel startup where the display driver
   supports it.
3. Raspberry Pi OS starts the labwc graphical session and logs in the configured
   desktop user.
4. labwc runs `scripts/start-kiosk.sh`, which immediately covers the session with
   the matching local loading screen.
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

To temporarily boot to the normal desktop without launching Chromium, create the
kiosk-disable marker over SSH or from a virtual console, then reboot:

```bash
mkdir -p ~/.config/leftover-achievements
touch ~/.config/leftover-achievements/disable-kiosk
sudo reboot
```

Remove the marker to restore appliance kiosk startup:

```bash
rm ~/.config/leftover-achievements/disable-kiosk
sudo reboot
```

To boot to a text console, use `sudo raspi-config` and select **System Options →
Boot / Auto Login → Console**, or run `sudo raspi-config nonint do_boot_behaviour
B1`. Restore desktop auto-login with the same menu or
`sudo raspi-config nonint do_boot_behaviour B4`. SSH is unaffected by either mode.
On an attached keyboard, Ctrl+Alt+F2 also reaches an alternate console.

To disable the custom early splash and restore a conventional quiet console boot:

```bash
sudo ./scripts/configure-pi-boot-branding.sh disable
sudo reboot
```

This recovery command removes only the project's marked `config.txt` block and its
fullscreen-logo kernel parameters, restores `console=tty1 quiet`, and rebuilds the
initramfs. It does not disable SSH or change the normal graphical boot target.

### Application updates

The backend checks the public GitHub Releases API every five minutes and caches the
latest published stable release. Drafts, prereleases, and ordinary commits pushed to
`main` do not create update notifications. Release tags use semantic versions such
as `v1.2.0`, so `v1.10.0` correctly compares newer than `v1.9.0`. No GitHub token is
required for the public repository.

When an update is available, use **Settings → Application Update** from the web
dashboard or swipe down from the top edge of the touchscreen and choose **Update**.
The installer requires a clean tracked worktree, fetches the selected release tag,
refuses same-version or older releases, checks out that exact tag in detached HEAD
mode, updates `.venv` from `requirements.txt`, and restarts only the backend service.
Detached HEAD is the expected production state after the first release update and
does not prevent future updates. Ignored files such as `.env`, the SQLite database,
and updater logs are not modified.

A new Pi initially cloned from `main` is shown as a **Development build** until HEAD
exactly matches a stable version tag. If a stable release exists, that unversioned
installation can install it through the normal Update button; subsequent checks use
the installed tag for semantic version comparisons.

The normal service user needs permission to restart this one service. Edit the
included sudoers template, validate it, and install it with restrictive permissions:

```bash
sed "s/YOUR_USER/$USER/g" deploy/leftover-achievements-update.sudoers | sudo tee /etc/sudoers.d/leftover-achievements-update >/dev/null
sudo chmod 0440 /etc/sudoers.d/leftover-achievements-update
sudo visudo -cf /etc/sudoers.d/leftover-achievements-update
```

The rule permits only `/usr/bin/systemctl restart leftover-achievements.service`;
it does not grant general passwordless sudo. Confirm that `command -v systemctl`
prints `/usr/bin/systemctl` on the Pi before installing the template. Update progress
is logged to `.update.log`. A failed update leaves persisted application data alone
and reports the last log message in both interfaces.

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
8. Open the **Actions** tab and follow all three native package jobs.
9. Confirm that the macOS arm64, macOS x64, and Windows x64 ZIPs appear under the
   same Release.
10. Installed LeftoverAchievements devices detect that stable published version.

Publishing the Release is the explicit **ship this version** action. Ordinary commits
and pushes never create device updates or desktop packages. After publication, a Pi
detects the tag during its next check and waits for the user to install it from Quick
Settings or web Settings. Packaged desktop installations detect the matching attached
ZIP and direct the user to download it manually. No command-line Git is needed to
publish releases.

After moving the repository, update the paths in the installed systemd unit and labwc
autostart entry, then run `sudo systemctl daemon-reload` and restart the service.
