# LeftoverAchievements

LeftoverAchievements turns RetroAchievements activity into a shared dashboard,
leaderboard, history view, live achievement display, and annual Wrapped recap.

It can run from a Mac, Windows PC, or Raspberry Pi. One installation can also act as
a hub for other displays on the same trusted network.

**Website:** [LeftoverAchievements.NickGray.Dev](https://leftoverachievements.nickgray.dev/)

## What is LeftoverAchievements?

LeftoverAchievements is a self-hosted companion display for families, friends, and
gaming groups that use [RetroAchievements](https://retroachievements.org/). Add the
players you want to follow and it keeps a shared view of their activity up to date.

Use it to:

- see who is leading the current week;
- watch achievements appear live on a full-screen display;
- follow current games, recent unlocks, beaten games, and masteries;
- compare weekly history and long-term progress charts;
- create annual Wrapped recaps for eligible players; and
- share one hub with additional displays around your home.

Everything runs on your own device. LeftoverAchievements uses your
RetroAchievements Web API key to retrieve achievement data, then stores its settings
and history locally.

## Download

**[Download the latest release](https://github.com/leftovernick/Leftover-Achievements/releases/latest)**

Choose the file for your device:

| Device | Download |
| --- | --- |
| Apple Silicon Mac | `LeftoverAchievements-macOS-arm64.dmg` |
| Intel Mac | `LeftoverAchievements-macOS-x64.dmg` |
| Windows 10/11 x64 | `LeftoverAchievements-Windows-x64-<version>.zip` |
| Raspberry Pi 4/5 | Installed with the command in the Raspberry Pi section below |

You will need a RetroAchievements account and a Web API key. You can create or copy
your key from the [RetroAchievements control panel](https://retroachievements.org/controlpanel.php).

## Install on macOS

1. Download the DMG that matches your Mac:
   - Choose **arm64** for Apple Silicon Macs with an M-series processor.
   - Choose **x64** for Intel Macs.
2. Open the downloaded DMG.
3. Drag **LeftoverAchievements** into the **Applications** folder.
4. Open LeftoverAchievements from Applications.
5. Select the trophy icon in the menu bar, then choose **Open Dashboard**.

The app is not currently notarized. If macOS blocks the first launch:

1. Control-click **LeftoverAchievements** in Applications.
2. Choose **Open**.
3. Confirm that you want to open it.

You can also approve it from **System Settings → Privacy & Security**.

LeftoverAchievements runs in the menu bar without a Dock icon. Quitting the browser
or closing the Display window does not stop the server; use **Quit
LeftoverAchievements** from the trophy menu when you want to stop it.

## Install on Windows

1. Download `LeftoverAchievements-Windows-x64-<version>.zip` from the latest release.
2. Extract the entire ZIP to a permanent folder.
3. Open the extracted folder and run the LeftoverAchievements executable.
4. Select the trophy icon in the system tray, then choose **Open Dashboard**.

Do not run the executable from inside the ZIP. The other files in the extracted
folder are required by the application.

The native Display window requires the
[Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).
Most current Windows 10 and Windows 11 installations already include it. The web
dashboard remains available even if WebView2 is unavailable.

To stop the application, open the system-tray menu and choose **Quit
LeftoverAchievements**.

## Install on Raspberry Pi 4 or 5

Use a 64-bit Raspberry Pi OS image with Desktop. In Raspberry Pi Imager, configure a
normal user, Wi-Fi or Ethernet, and SSH before the first boot.

After the Pi has booted and can reach the internet, open a terminal as the normal user
and download the installer:

```bash
curl -fsSLO https://raw.githubusercontent.com/leftovernick/Leftover-Achievements/main/scripts/bootstrap-pi.sh
```

You may inspect `bootstrap-pi.sh` before running it. Start the installation without
`sudo`:

```bash
bash bootstrap-pi.sh
```

The installer:

- downloads the latest stable Raspberry Pi release;
- verifies the download before installing it;
- installs the required software;
- configures the background service and dedicated kiosk session;
- checks the local display before finishing; and
- reboots the Pi after a ten-second countdown.

Press Ctrl+C during the countdown if you do not want to reboot immediately. To install
without scheduling a reboot, run:

```bash
bash bootstrap-pi.sh --no-reboot
```

After the Pi restarts, open the following address from another device on the same
network:

```text
http://<raspberry-pi-hostname>.local:8000/
```

For example, a Pi named `leftover-pi` is available at
`http://leftover-pi.local:8000/`.

The Pi starts directly in the LeftoverAchievements display. Its normal desktop is not
shown while kiosk mode is enabled, but SSH remains available.

## First-time setup

The dashboard opens the setup guide automatically on a new installation.

1. Choose **Set Up This Device** to make this installation a hub, or choose
   **Connect to an existing hub** if another device already owns your data.
2. Paste your RetroAchievements Web API key. The app verifies it before saving it.
3. Add the RetroAchievements usernames you want to track.
4. Preview the shared display.
5. Finish setup and open the dashboard or display.

The API key is stored locally and is never shown again in the browser. Initial account
history can take several minutes to load for long-running accounts. Progress appears
under **Charts → All Time** and **Settings → History Data**.

## Using LeftoverAchievements

The main pages are:

- **Dashboard** — current activity, weekly rankings, and recent unlocks.
- **Display** — a full-screen rotating view with live achievement alerts.
- **Users** — tracked players and per-player notification settings.
- **History** — completed weekly results and available Wrapped recaps.
- **Charts** — weekly and all-time progress charts.
- **Settings** — API connection, display timing, sounds, notifications, updates,
  history refresh, and recent errors.

From the device running LeftoverAchievements, the dashboard is available at:

```text
http://127.0.0.1:8000/
```

Other devices on the same network can use the LAN address shown in the macOS menu,
Windows tray, application log, or Raspberry Pi setup screen.

## Connect additional displays

One LeftoverAchievements installation can be the hub for multiple displays.

On each additional Mac, Windows PC, or Raspberry Pi:

1. Open its first-time setup guide.
2. Choose **Connect to an existing hub**.
3. Enter the hub address, such as `192.168.1.50:8000` or
   `leftover-pi.local:8000`.

The hub keeps the API key, players, settings, and history, and refreshes the shared
RetroAchievements data. Connected displays do not need their own API keys.
Disconnect or change a hub from **Connection Settings** in the desktop menu, or by
opening `http://127.0.0.1:8000/connection` on that device.

## Updates

LeftoverAchievements checks GitHub Releases for stable updates.

- **macOS:** Open **Settings → Application Update** and choose **Update Now**.
- **Windows:** Follow the release link shown in Settings, download the new ZIP, quit
  LeftoverAchievements, and replace the extracted application folder.
- **Raspberry Pi:** Open **Settings → Application Update** and choose **Update Now**.

Updates preserve the API key, tracked users, history, settings, and custom sounds.
Only stable published releases are offered as updates.

## Data and network safety

LeftoverAchievements is intended for a device you control on a trusted home network.
It does not provide internet-facing user accounts or authentication. Do not forward
port 8000 from your router or expose the dashboard directly to the public internet.

Application data is stored locally:

- **macOS:** `~/Library/Application Support/LeftoverAchievements/`
- **Windows:** `%LOCALAPPDATA%\LeftoverAchievements\`
- **Raspberry Pi:** `~/.local/share/LeftoverAchievements/data/`

See [SECURITY.md](SECURITY.md) for more about API-key handling and network safety.

## Troubleshooting

### The dashboard does not open

- Confirm that the trophy icon is present in the macOS menu bar or Windows system
  tray.
- Choose **Open Dashboard** from that menu again.
- Check whether another application is already using port 8000.
- Restart LeftoverAchievements.

### The Windows Display window does not open

Install or repair the Microsoft Edge WebView2 Runtime, then restart
LeftoverAchievements. You can continue using `/display` in a normal browser.

### The Raspberry Pi display does not start

Connect over SSH and check the service:

```bash
sudo systemctl status leftover-achievements
journalctl -u leftover-achievements
```

Restart it with:

```bash
sudo systemctl restart leftover-achievements
```

To temporarily return to the normal Raspberry Pi desktop:

```bash
cd ~/.local/share/LeftoverAchievements/app/current
sudo ./scripts/configure-pi-appliance-session.sh disable
sudo reboot
```

To restore kiosk mode:

```bash
cd ~/.local/share/LeftoverAchievements/app/current
sudo ./scripts/configure-pi-appliance-session.sh enable "$(id -un)" "$PWD"
sudo reboot
```

### RetroAchievements data is unavailable

- Confirm that the device can reach the internet.
- Open **Settings** and check the RetroAchievements connection status.
- Re-enter the Web API key if the connection is marked invalid.
- Use **Settings → History Data → Refresh / Retry** if an account-history request was
  interrupted.

### Where are the logs?

Recent warnings and errors are shown under **Settings → Recent Errors** with
credentials redacted. Packaged installations also keep rotating logs in the `logs`
folder inside the platform data directory listed above.

## License and contributions

LeftoverAchievements is source-available software, not open-source software. Official
releases may be used for personal, non-commercial purposes. Redistribution,
independent publication, commercial use, and derivative products are not permitted
without written authorization. See [LICENSE.md](LICENSE.md) for the complete terms.

Issues and proposed improvements are welcome. A GitHub fork may be used to prepare a
pull request for review, but all changes are accepted at the project owner's
discretion. Read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a change.
