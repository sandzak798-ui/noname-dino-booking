import os, sqlite3, calendar, uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
import requests

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-me')
DB = os.environ.get('DATABASE_PATH', 'bookings.db')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'dino123')
TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TG_CHAT = os.environ.get('TELEGRAM_CHAT_ID', '')
SLOTS = [f'{h:02d}:{m:02d}' for h in range(9, 20) for m in (0, 30)]
STATUS = {'dolazi':'Dolazi','zavrseno':'Završeno','nije_dosao':'Nije došao','otkazano':'Otkazano'}
SERVICES = {'sisanje_pranje_brada': 'Šišanje i brada', 'sisanje_pranje_farbanje_brada': 'Šišanje, farbanje i brada'}

def duration(service):
    return 60 if service == 'sisanje_pranje_farbanje_brada' else 30

def conn():
    url = os.environ.get('DATABASE_URL', '').strip()
    if url:
        raw = psycopg2.connect(url, cursor_factory=RealDictCursor)
        cur = raw.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS bookings (id SERIAL PRIMARY KEY, booking_date TEXT NOT NULL, booking_time TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'dolazi', recurring INTEGER NOT NULL DEFAULT 0, series_id TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(booking_date,booking_time))''')
        cur.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS service TEXT NOT NULL DEFAULT 'sisanje'")
        cur.execute('ALTER TABLE bookings ADD COLUMN IF NOT EXISTS duration_minutes INTEGER NOT NULL DEFAULT 60')
        raw.commit()
        return DBConn(raw, True)
    raw = sqlite3.connect(DB, timeout=20)
    raw.row_factory = sqlite3.Row
    raw.execute('''CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, booking_date TEXT NOT NULL, booking_time TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'dolazi', recurring INTEGER NOT NULL DEFAULT 0, series_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(booking_date,booking_time))''')
    cols = {r[1] for r in raw.execute('PRAGMA table_info(bookings)').fetchall()}
    for col, definition in [('status',"TEXT NOT NULL DEFAULT 'dolazi'"),('recurring','INTEGER NOT NULL DEFAULT 0'),('series_id','TEXT'),('service',"TEXT NOT NULL DEFAULT 'sisanje'"),('duration_minutes','INTEGER NOT NULL DEFAULT 60')]:
        if col not in cols:
            raw.execute(f'ALTER TABLE bookings ADD COLUMN {col} {definition}')
    raw.commit()
    return DBConn(raw, False)

class DBConn:
    def __init__(self, raw, pg): self.raw, self.pg = raw, pg
    def execute(self, q, params=()):
        if self.pg:
            cur = self.raw.cursor()
            cur.execute(q.replace('?', '%s'), params)
            return CursorWrap(cur)
        return CursorWrap(self.raw.execute(q, params))
    def commit(self): return self.raw.commit()
    def rollback(self): return self.raw.rollback()
    def close(self): return self.raw.close()
class CursorWrap:
    def __init__(self, cur): self.cur = cur
    def fetchall(self): return self.cur.fetchall()
    def fetchone(self): return self.cur.fetchone()
    def __iter__(self): return iter(self.cur)

def start_dt(day, tm): return datetime.strptime(day + ' ' + tm, '%Y-%m-%d %H:%M')
def is_valid(day, tm, mins):
    try:
        d = date.fromisoformat(day)
        s = start_dt(day, tm)
        return d >= date.today() and d.weekday() < 5 and tm in SLOTS and s + timedelta(minutes=mins) <= s.replace(hour=20, minute=0)
    except (ValueError, TypeError): return False

def conflicts(c, day, tm, mins):
    start = start_dt(day, tm)
    end = start + timedelta(minutes=mins)
    rows = c.execute("SELECT booking_time,duration_minutes FROM bookings WHERE booking_date=? AND status!='otkazano'", (day,)).fetchall()
    return any(start < start_dt(day, r['booking_time']) + timedelta(minutes=r['duration_minutes'] or 30) and start_dt(day, r['booking_time']) < end for r in rows)

def available(day, service='sisanje_pranje_brada'):
    if service not in SERVICES: service = 'sisanje_pranje_brada'
    mins = duration(service)
    c = conn()
    try: return [tm for tm in SLOTS if is_valid(day, tm, mins) and not conflicts(c, day, tm, mins)]
    finally: c.close()

def tg(msg):
    if TG_TOKEN and TG_CHAT:
        try:
            r = requests.post(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage', json={'chat_id':TG_CHAT,'text':msg}, timeout=10)
            print('TELEGRAM:', r.status_code)
        except Exception as e: print('TELEGRAM ERROR:', e)

@app.route('/', methods=['GET','POST'])
def index():
    selected = request.values.get('date') or date.today().isoformat()
    service = request.values.get('service', 'sisanje_pranje_brada')
    if service not in SERVICES:
        if request.method == 'POST':
            flash('Izaberite važeću uslugu.')
            return redirect(url_for('index'))
        service = 'sisanje_pranje_brada'
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip()
        tm = request.form.get('time','')
        mins = duration(service)
        if not name or not phone or not is_valid(selected, tm, mins):
            flash('Molimo unesite podatke i izaberite važeći termin.'); return redirect(url_for('index',date=selected,service=service))
        c = conn()
        try:
            # PostgreSQL advisory lock serializes competing bookings for the same date.
            if c.pg: c.execute('SELECT pg_advisory_xact_lock(hashtext(?))', (selected,))
            else: c.execute('BEGIN IMMEDIATE')
            if conflicts(c, selected, tm, mins):
                c.rollback(); flash('Termin je zauzet. Izaberite drugi.'); return redirect(url_for('index',date=selected,service=service))
            c.execute('INSERT INTO bookings(booking_date,booking_time,name,phone,service,duration_minutes) VALUES(?,?,?,?,?,?)', (selected,tm,name,phone,service,mins))
            c.commit()
        except Exception:
            c.rollback(); flash('Rezervacija nije uspjela. Pokušajte ponovo.'); return redirect(url_for('index',date=selected,service=service))
        finally: c.close()
        tg(f'✂️ NOVA REZERVACIJA – NoName by Dino\n👤 {name}\n📞 {phone}\n📅 {selected}\n🕐 {tm}\n💈 {SERVICES[service]} ({mins} min)')
        return render_template('success.html',name=name,date=selected,time=tm)
    return render_template('index.html',date=selected,today=date.today().isoformat(),slots=[tm for tm in SLOTS if is_valid(selected, tm, duration(service))],free_slots=available(selected,service),services=SERVICES,service=service)

@app.route('/calendar/<day>/<tm>/<name>.ics')
def ics(day,tm,name):
    start = start_dt(day,tm)
    c = conn()
    try:
        r = c.execute("SELECT duration_minutes FROM bookings WHERE booking_date=? AND booking_time=? AND name=? AND status!='otkazano'",(day,tm,name)).fetchone()
        mins = r['duration_minutes'] if r else 30
    finally: c.close()
    end = start + timedelta(minutes=mins)
    body = '\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//NoName by Dino//Booking//BS','BEGIN:VEVENT',f'UID:{day}-{tm}-{name}@noname-dino',f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",f'SUMMARY:NoName by Dino – {name}','END:VEVENT','END:VCALENDAR'])
    return Response(body,mimetype='text/calendar',headers={'Content-Disposition':'attachment; filename=noname-termin.ics'})

def guard(): return bool(session.get('admin'))
@app.route('/admin/login',methods=['GET','POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True; return redirect(url_for('admin'))
        flash('Pogrešna lozinka.')
    return render_template('login.html')
@app.route('/admin')
def admin():
    if not guard(): return redirect(url_for('login'))
    today = date.today(); y = int(request.args.get('year',today.year)); m = int(request.args.get('month',today.month))
    first = date(y,m,1); last = date(y,m,calendar.monthrange(y,m)[1])
    c = conn()
    rows = c.execute("SELECT booking_date,COUNT(*) n FROM bookings WHERE booking_date BETWEEN ? AND ? AND status!='otkazano' GROUP BY booking_date",(first.isoformat(),last.isoformat())).fetchall()
    counts = {r['booking_date']:r['n'] for r in rows}
    month_rows = c.execute('SELECT * FROM bookings WHERE booking_date BETWEEN ? AND ?',(first.isoformat(),last.isoformat())).fetchall()
    stats = {'month':len(month_rows),'noshow':sum(1 for r in month_rows if r['status']=='nije_dosao'),'done':sum(1 for r in month_rows if r['status']=='zavrseno'),'today':c.execute("SELECT COUNT(*) AS n FROM bookings WHERE booking_date=? AND status!='otkazano'",(today.isoformat(),)).fetchone()['n']}
    c.close()
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(y,m)
    prev = first-timedelta(days=1); nxt = last+timedelta(days=1)
    return render_template('admin_month.html',weeks=weeks,month=m,year=y,month_name=['','Januar','Februar','Mart','April','Maj','Juni','Juli','August','Septembar','Oktobar','Novembar','Decembar'][m],counts=counts,stats=stats,prev=prev,nxt=nxt,today=today)
@app.route('/admin/day/<day>')
def admin_day(day):
    if not guard(): return redirect(url_for('login'))
    c=conn(); rows=c.execute('SELECT * FROM bookings WHERE booking_date=? ORDER BY booking_time',(day,)).fetchall(); c.close()
    bytime={r['booking_time']:r for r in rows}
    return render_template('admin_day.html',day=day,slots=SLOTS,bytime=bytime,statuses=STATUS)
@app.post('/admin/status/<int:bid>')
def set_status(bid):
    if not guard(): return redirect(url_for('login'))
    st=request.form.get('status')
    if st in STATUS:
        c=conn(); c.execute('UPDATE bookings SET status=? WHERE id=?',(st,bid)); c.commit(); c.close()
    return redirect(request.referrer or url_for('admin'))
@app.post('/admin/delete/<int:bid>')
def delete(bid):
    if not guard(): return redirect(url_for('login'))
    c=conn(); c.execute('DELETE FROM bookings WHERE id=?',(bid,)); c.commit(); c.close()
    return redirect(request.referrer or url_for('admin'))
@app.route('/admin/recurring',methods=['GET','POST'])
def recurring():
    if not guard(): return redirect(url_for('login'))
    if request.method == 'POST':
        name=request.form['name'].strip(); phone=request.form['phone'].strip(); start=request.form['start']; tm=request.form['time']
        service=request.form.get('service','sisanje_pranje_brada')
        if service not in SERVICES: service='sisanje_pranje_brada'
        mins=duration(service)
        weeks=max(1,min(104,int(request.form.get('weeks','52')))); series=str(uuid.uuid4())
        try: d=date.fromisoformat(start)
        except ValueError: flash('Neispravan datum.'); return redirect(url_for('recurring'))
        added=0; skipped=[]
        c=conn()
        try:
            for i in range(weeks):
                day=(d+timedelta(weeks=i)).isoformat()
                if not is_valid(day,tm,mins): skipped.append(day); continue
                try:
                    if c.pg: c.execute('SELECT pg_advisory_xact_lock(hashtext(?))',(day,))
                    else: c.execute('BEGIN IMMEDIATE')
                    if conflicts(c,day,tm,mins):
                        c.rollback(); skipped.append(day); continue
                    c.execute('INSERT INTO bookings(booking_date,booking_time,name,phone,recurring,series_id,service,duration_minutes) VALUES(?,?,?,?,1,?,?,?)',(day,tm,name,phone,series,service,mins))
                    c.commit(); added+=1
                except Exception:
                    c.rollback(); skipped.append(day)
        finally: c.close()
        tg(f'🔁 TRAJNI TERMIN – NoName by Dino\n👤 {name}\n📞 {phone}\n📅 Svake sedmice od {start}\n🕐 {tm}\n💈 {SERVICES[service]} ({mins} min)\n✅ Dodano: {added}')
        flash(f'Trajni termin kreiran: {added} termina.' + (f' Preskočeno: {len(skipped)} termina.' if skipped else ''))
        return redirect(url_for('admin'))
    return render_template('recurring.html',today=date.today().isoformat(),slots=SLOTS,services=SERVICES)
@app.route('/admin/logout')
def logout():
    session.clear(); return redirect(url_for('index'))
if __name__ == '__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
