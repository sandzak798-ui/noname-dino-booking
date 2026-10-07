import os, sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session
import urllib.request, urllib.parse

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret')
DB = os.path.join(os.path.dirname(__file__), 'bookings.db')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'dino123')
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
OPEN_HOUR, CLOSE_HOUR = 9, 19


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(date,time)
        )''')


def slots_for(date):
    with db() as con:
        booked = {r['time'] for r in con.execute('SELECT time FROM bookings WHERE date=?', (date,))}
    return [f'{h:02d}:00' for h in range(OPEN_HOUR, CLOSE_HOUR) if f'{h:02d}:00' not in booked]


def telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        return False
    data = urllib.parse.urlencode({'chat_id': CHAT_ID, 'text': text}).encode()
    try:
        urllib.request.urlopen(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage', data=data, timeout=8).read()
        return True
    except Exception as e:
        print('Telegram error:', e)
        return False


@app.route('/', methods=['GET', 'POST'])
def index():
    today = datetime.now().date().isoformat()
    selected = request.values.get('date', today)
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip()
        time = request.form.get('time','').strip()
        if not name or not phone or not time:
            flash('Molimo popunite sva polja.', 'error')
        elif selected < today:
            flash('Nije moguće rezervisati termin u prošlosti.', 'error')
        else:
            try:
                with db() as con:
                    con.execute('INSERT INTO bookings(date,time,name,phone,created_at) VALUES(?,?,?,?,?)',
                                (selected,time,name,phone,datetime.now().isoformat(timespec='seconds')))
                telegram(f'✂️ NOVA REZERVACIJA – NoName by Dino\n\n👤 {name}\n📞 {phone}\n📅 {selected}\n🕐 {time}')
                return render_template('success.html', name=name, date=selected, time=time)
            except sqlite3.IntegrityError:
                flash('Ovaj termin je upravo rezervisan. Izaberite drugi.', 'error')
    return render_template('index.html', date=selected, today=today, slots=slots_for(selected))


@app.route('/admin/login', methods=['GET','POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == ADMIN_PASSWORD:
        session['admin'] = True
        return redirect(url_for('admin'))
    if request.method == 'POST': flash('Pogrešna lozinka.', 'error')
    return render_template('login.html')

@app.route('/admin')
def admin():
    if not session.get('admin'): return redirect(url_for('login'))
    selected = request.args.get('date', datetime.now().date().isoformat())
    with db() as con:
        rows = con.execute('SELECT * FROM bookings WHERE date=? ORDER BY time', (selected,)).fetchall()
    return render_template('admin.html', bookings=rows, date=selected)

@app.post('/admin/delete/<int:bid>')
def delete(bid):
    if not session.get('admin'): return redirect(url_for('login'))
    with db() as con:
        con.execute('DELETE FROM bookings WHERE id=?', (bid,))
    return redirect(request.referrer or url_for('admin'))

@app.get('/admin/logout')
def logout():
    session.clear(); return redirect(url_for('index'))

init_db()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
