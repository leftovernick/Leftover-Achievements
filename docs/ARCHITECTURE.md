# Architecture

LeftoverAchievements is one FastAPI process with a server-rendered browser interface,
background polling jobs, and a local SQLite database. The same backend is used by the
development server, desktop wrappers, and Raspberry Pi appliance.

## Request and data flow

1. `runtime.py` selects resource, data, log, and network settings for the active mode.
2. `launcher.py` starts Uvicorn for packaged builds; development can run Uvicorn directly.
3. `app.py` owns HTTP routes, page composition, and background-job coordination.
4. `security.py` enforces the browser request boundary and response headers.
5. `services/retroachievements.py` is the only RetroAchievements HTTP client. It
   applies HTTPS certificate verification, timeouts, request spacing, and bounded
   retry behavior.
6. `database/database.py` owns schema creation, idempotent migrations, and all
   persistence queries.
7. Jinja templates render initial HTML. Files in `static/js` add focused client-side
   behavior without a frontend framework.

The browser never receives the RetroAchievements API key. Routes ask the API service
for normalized data, persist the fields needed by the application, and render or
serialize those results.

## Runtime modes

- Development keeps mutable files in the checkout and runs on port 8001.
- Packaged macOS and Windows builds keep data in the platform application-data
  directory and use a menu-bar or tray wrapper.
- Raspberry Pi mode runs the same server under systemd and opens `/display` in a
  dedicated Chromium kiosk session.

An installation is a hub unless `instance-config.json` names another hub. A client
redirects browser pages to that hub and stops its local polling work; its local
database remains untouched.

## Background work

Background tasks refresh live activity, weekly rankings, profiles, game metadata,
history, charts, and update status. `services/background_tasks.py` provides the task
creation boundary so exceptions are logged consistently. Polling services retain
their last usable cache when an upstream request fails.

The display receives short-lived events over server-sent events. Shutdown wakes those
streams before Uvicorn waits for persistent connections, allowing packaged processes
to stop cleanly.

## Wrapped

`services/wrapped.py` builds annual statistics from mode-aware unlock facts and award
records. `services/wrapped_story.py` deterministically selects the story cards. The
template, stylesheet, and browser controller are isolated in `templates/wrapped.html`,
`static/css/wrapped.css`, and `static/js/wrapped.js` because the recap has its own
responsive and export layout.

## Update boundary

`services/updater.py` discovers releases and coordinates installation. Platform update
scripts validate the package version, architecture, expected contents, and application
identity before activation. Raspberry Pi releases use versioned directories and an
atomic `current` symlink so a failed health check can leave the active release intact.
