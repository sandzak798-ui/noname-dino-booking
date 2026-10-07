# NoName by Dino V3 – PostgreSQL

Render:
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Environment: `DATABASE_URL` = Internal Database URL from Render Postgres
- Also set `SECRET_KEY`, `ADMIN_PASSWORD`, and optionally Telegram variables.

When DATABASE_URL is present, bookings are stored in PostgreSQL.
