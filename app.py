import os, sqlite3, calendar
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
import requests

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","change-me")
DB=os.environ.get("DATABASE_PATH","bookings.db")
ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD","dino123")
TG_TOKEN=os.environ.get("TELEGRAM_BOT_TOKEN","")
TG_CHAT=os.environ.get("TELEGRAM_CHAT_ID","")
SLOTS=[f"{h:02d}:00" for h in range(9,19)]
STATUS={"dolazi":"Dolazi","zavrseno":"Završeno","nije_dosao":"Nije došao","otkazano":"Otkazano"}

def conn():
    database_url=os.environ.get("DATABASE_URL","").strip()
    if database_url:
        c=psycopg2.connect(database_url, cursor_factory=RealDictCursor)
        cur=c.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS bookings(
          id SERIAL PRIMARY KEY,
          booking_date TEXT NOT NULL,
          booking_time TEXT NOT NULL,
          name TEXT NOT NULL,
          phone TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'dolazi',
          recurring INTEGER NOT NULL DEFAULT 0,
          series_id TEXT,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(booking_date,booking_time))""")
        c.commit()
        return DBConn(c, True)
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS bookings(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      booking_date TEXT NOT NULL, booking_time TEXT NOT NULL,
      name TEXT NOT NULL, phone TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'dolazi',
      recurring INTEGER NOT NULL DEFAULT 0,
      series_id TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(booking_date,booking_time))""")
    cols={r[1] for r in c.execute("PRAGMA table_info(bookings)").fetchall()}
    if "status" not in cols: c.execute("ALTER TABLE bookings ADD COLUMN status TEXT NOT NULL DEFAULT 'dolazi'")
    if "recurring" not in cols: c.execute("ALTER TABLE bookings ADD COLUMN recurring INTEGER NOT NULL DEFAULT 0")
    if "series_id" not in cols: c.execute("ALTER TABLE bookings ADD COLUMN series_id TEXT")
    c.commit()
    return DBConn(c, False)

class DBConn:
    def __init__(self, raw, pg):
        self.raw=raw; self.pg=pg
    def _sql(self, q):
        return q.replace("?", "%s") if self.pg else q
    def execute(self, q, params=()):
        if self.pg:
            cur=self.raw.cursor()
            cur.execute(self._sql(q), params)
            return CursorWrap(cur)
        return CursorWrap(self.raw.execute(q, params))
    def commit(self): return self.raw.commit()
    def close(self): return self.raw.close()

class CursorWrap:
    def __init__(self, cur): self.cur=cur
    def fetchall(self): return self.cur.fetchall()
    def fetchone(self): return self.cur.fetchone()
    def __iter__(self): return iter(self.cur)

def used(day):
    c=conn(); x={r["booking_time"] for r in c.execute("SELECT booking_time FROM bookings WHERE booking_date=? AND status!='otkazano'",(day,))}; c.close(); return x
def available(day): return [s for s in SLOTS if s not in used(day)]

def tg(msg):
    if TG_TOKEN and TG_CHAT:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text},
            timeout=10
        )
        print("TELEGRAM:", r.status_code, r.text)
    except Exception as e:
        print("TELEGRAM ERROR:", e)
else:
    print("TELEGRAM ERROR: TOKEN oder CHAT_ID fehlt", flush=True)

@app.route("/",methods=["GET","POST"])
def index():
    selected=request.values.get("date") or date.today().isoformat()
    if request.method=="POST":
        name=request.form.get("name","").strip(); phone=request.form.get("phone","").strip(); tm=request.form.get("time","")
        if not name or not phone or tm not in SLOTS:
            flash("Molimo popunite sva polja i izaberite termin."); return redirect(url_for("index",date=selected))
        try:
            c=conn(); c.execute("INSERT INTO bookings(booking_date,booking_time,name,phone) VALUES(?,?,?,?)",(selected,tm,name,phone)); c.commit(); c.close()
        except Exception as e:
            flash("Ovaj termin je upravo rezervisan. Izaberite drugi."); return redirect(url_for("index",date=selected))
        tg(f"✂️ NOVA REZERVACIJA – NoName by Dino\n👤 {name}\n📞 {phone}\n📅 {selected}\n🕐 {tm}")
        return render_template("success.html",name=name,date=selected,time=tm)
    return render_template("index.html",date=selected,today=date.today().isoformat(),slots=available(selected))

@app.route("/calendar/<day>/<tm>/<name>.ics")
def ics(day,tm,name):
    start=datetime.strptime(day+" "+tm,"%Y-%m-%d %H:%M"); end=start+timedelta(hours=1)
    body="\r\n".join(["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//NoName by Dino//Booking//BS","BEGIN:VEVENT",
      f"UID:{day}-{tm}-{name}@noname-dino",f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
      f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
      f"SUMMARY:NoName by Dino – {name}","END:VEVENT","END:VCALENDAR"])
    return Response(body,mimetype="text/calendar",headers={"Content-Disposition":"attachment; filename=noname-termin.ics"})

def guard():
    return bool(session.get("admin"))

@app.route("/admin/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        if request.form.get("password")==ADMIN_PASSWORD:
            session["admin"]=True; return redirect(url_for("admin"))
        flash("Pogrešna lozinka.")
    return render_template("login.html")

@app.route("/admin")
def admin():
    if not guard(): return redirect(url_for("login"))
    today=date.today()
    y=int(request.args.get("year",today.year)); m=int(request.args.get("month",today.month))
    first=date(y,m,1); last=date(y,m,calendar.monthrange(y,m)[1])
    c=conn()
    rows=c.execute("""SELECT booking_date, COUNT(*) n FROM bookings
      WHERE booking_date BETWEEN ? AND ? AND status!='otkazano' GROUP BY booking_date""",(first.isoformat(),last.isoformat())).fetchall()
    counts={r["booking_date"]:r["n"] for r in rows}
    month_rows=c.execute("SELECT * FROM bookings WHERE booking_date BETWEEN ? AND ?",(first.isoformat(),last.isoformat())).fetchall()
    stats={"month":len(month_rows),"noshow":sum(1 for r in month_rows if r["status"]=="nije_dosao"),
           "done":sum(1 for r in month_rows if r["status"]=="zavrseno"),
           "today":c.execute("SELECT COUNT(*) AS n FROM bookings WHERE booking_date=? AND status!='otkazano'",(today.isoformat(),)).fetchone()["n"]}
    c.close()
    weeks=calendar.Calendar(firstweekday=0).monthdatescalendar(y,m)
    prev=(first-timedelta(days=1)); nxt=(last+timedelta(days=1))
    return render_template("admin_month.html",weeks=weeks,month=m,year=y,month_name=["","Januar","Februar","Mart","April","Maj","Juni","Juli","August","Septembar","Oktobar","Novembar","Decembar"][m],counts=counts,stats=stats,prev=prev,nxt=nxt,today=today)

@app.route("/admin/day/<day>")
def admin_day(day):
    if not guard(): return redirect(url_for("login"))
    c=conn(); rows=c.execute("SELECT * FROM bookings WHERE booking_date=? ORDER BY booking_time",(day,)).fetchall(); c.close()
    bytime={r["booking_time"]:r for r in rows}
    return render_template("admin_day.html",day=day,slots=SLOTS,bytime=bytime,statuses=STATUS)

@app.post("/admin/status/<int:bid>")
def set_status(bid):
    if not guard(): return redirect(url_for("login"))
    st=request.form.get("status")
    if st in STATUS:
        c=conn(); c.execute("UPDATE bookings SET status=? WHERE id=?",(st,bid)); c.commit(); c.close()
    return redirect(request.referrer or url_for("admin"))

@app.post("/admin/delete/<int:bid>")
def delete(bid):
    if not guard(): return redirect(url_for("login"))
    c=conn(); c.execute("DELETE FROM bookings WHERE id=?",(bid,)); c.commit(); c.close()
    return redirect(request.referrer or url_for("admin"))

@app.route("/admin/recurring",methods=["GET","POST"])
def recurring():
    if not guard(): return redirect(url_for("login"))
    if request.method=="POST":
        name=request.form["name"].strip(); phone=request.form["phone"].strip(); start=request.form["start"]; tm=request.form["time"]
        weeks=int(request.form.get("weeks","52")); series=f"{datetime.utcnow().timestamp()}-{name}"
        d=datetime.strptime(start,"%Y-%m-%d").date(); added=0; skipped=[]
        c=conn()
        for i in range(weeks):
            day=(d+timedelta(weeks=i)).isoformat()
            try:
                c.execute("""INSERT INTO bookings(booking_date,booking_time,name,phone,recurring,series_id)
                VALUES(?,?,?,?,1,?)""",(day,tm,name,phone,series)); added+=1
            except Exception as e: skipped.append(day)
        c.commit(); c.close()
        tg(f"🔁 TRAJNI TERMIN – NoName by Dino\n👤 {name}\n📞 {phone}\n📅 Svake sedmice od {start}\n🕐 {tm}\n✅ Dodano: {added}")
        flash(f"Trajni termin kreiran: {added} termina." + (f" Preskočeno: {len(skipped)} zauzetih termina." if skipped else ""))
        return redirect(url_for("admin"))
    return render_template("recurring.html",today=date.today().isoformat(),slots=SLOTS)

@app.route("/admin/logout")
def logout():
    session.clear(); return redirect(url_for("index"))

if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
