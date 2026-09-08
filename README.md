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

3. Copy the example env and set your RetroAchievements API key:

```bash
cp .env.example .env
```

Then edit `.env` and set `RA_API_KEY` to your RetroAchievements web API key.

4. Run the FastAPI app:

```bash
uvicorn app:app --reload --timeout-graceful-shutdown 1
```

5. Open the dashboard and admin pages in your browser:

- Dashboard: http://127.0.0.1:8000/
- Admin: http://127.0.0.1:8000/admin

## Notes

- Do not commit your `.env` file (it's in `.gitignore`).
- The app will create a local SQLite database at `database/leftover.db` automatically.
- The admin page validates users through `API_GetUserProfile.php`, the official RetroAchievements profile endpoint.
- The one-second graceful-shutdown limit lets the development server reload even while the display page has an open live-events connection.
