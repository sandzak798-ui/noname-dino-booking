# NoName by Dino – Python booking app

## Lokalno pokretanje
1. Instaliraj Python 3.10+
2. `pip install -r requirements.txt`
3. Postavi environment varijable iz `.env.example`
4. `python app.py`
5. Otvori `http://127.0.0.1:5000`

Admin: `/admin/login`

## Telegram
1. U Telegramu otvori `@BotFather`, napravi bot i kopiraj token.
2. Pošalji jednu poruku novom botu.
3. Otvori Telegram Bot API `getUpdates` za svoj bot i pronađi svoj `chat.id`.
4. Na serveru postavi `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID`.

Token nikad ne stavljaj direktno u javni source code.

## Produkcija
Za javni sajt koristi hosting koji podržava Python/WSGI (ili VPS). EuroDNS može ostati registrar/DNS: usmjeri domen/subdomen na hosting server. Za produkciju promijeni SECRET_KEY i ADMIN_PASSWORD, isključi debug i koristi HTTPS.
