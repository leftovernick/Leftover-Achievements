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

## Raspberry Pi 5 deployment

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

The kiosk launcher checks `http://127.0.0.1:8000/display` every two seconds until it
receives a successful response, then launches Chromium with kiosk, no-first-run,
no-error-dialog, autoplay, and maximized-window flags. It does not require internet
access to open the local page.

### 4. Reboot and verify

```bash
sudo reboot
```

Expected boot sequence:

1. systemd waits for the network-online target, starts FastAPI, and restarts it after
   a crash.
2. Raspberry Pi OS starts the labwc desktop and logs in the configured desktop user.
3. labwc runs `scripts/start-kiosk.sh`.
4. The launcher waits for FastAPI and opens Chromium directly to `/display`.
5. The dashboard remains available to other devices on the LAN.

A temporary loss of internet connectivity does not prevent Chromium from reaching the
local FastAPI page. Live RetroAchievements data and remote artwork naturally require
internet connectivity and will recover through the application's existing polling.

Useful service commands:

```bash
sudo systemctl status leftover-achievements
sudo systemctl restart leftover-achievements
journalctl -u leftover-achievements
```

### Application updates

The backend checks `origin/main` every five minutes and caches the result. These
checks only run `git fetch`; they never install an update. When an update is
available, use **Settings → Application Update** from the web dashboard or swipe
down from the top edge of the touchscreen and choose **Update**. The installer
requires a clean tracked worktree and the `main` branch, performs a fast-forward
only merge, updates `.venv` from `requirements.txt`, and restarts only the backend
service. Ignored files such as `.env`, the SQLite database, and updater logs are not
modified.

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

After moving the repository, update the paths in the installed systemd unit and labwc
autostart entry, then run `sudo systemctl daemon-reload` and restart the service.
