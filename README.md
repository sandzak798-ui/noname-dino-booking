# NoName by Dino V2
Build: `pip install -r requirements.txt`
Start: `gunicorn app:app`
Admin: `/admin/login`
Render Environment: SECRET_KEY, ADMIN_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

Napomena: SQLite na Render free servisu nije trajna baza. Za stvarnu produkciju prebaci bazu na persistent disk ili PostgreSQL prije nego što se osloniš na termine.
