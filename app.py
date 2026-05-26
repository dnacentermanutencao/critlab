from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime
from functools import wraps
import uuid, os, hashlib, sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "critlab.db")

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))
app.secret_key = os.environ.get("SECRET_KEY", "critlab-secret-2026")

# ────────────────────────────────────────────────────────────────────
# BANCO DE DADOS
# ────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS hospitals (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                username   TEXT NOT NULL UNIQUE,
                password   TEXT NOT NULL,
                role       TEXT DEFAULT 'hospital',
                active     INTEGER DEFAULT 1,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS results (
                id          TEXT PRIMARY KEY,
                hospital_id TEXT NOT NULL,
                protocol    TEXT,
                technician  TEXT,
                exam        TEXT,
                patient     TEXT,
                value       TEXT,
                created_at  TEXT,
                status      TEXT DEFAULT 'PENDENTE'
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id          TEXT PRIMARY KEY,
                result_id   TEXT NOT NULL,
                notified_to TEXT,
                role        TEXT,
                notified_at TEXT,
                notes       TEXT
            );
        """)
        if not db.execute("SELECT id FROM hospitals WHERE role='admin'").fetchone():
            db.execute(
                "INSERT INTO hospitals VALUES (?,?,?,?,?,?,?)",
                ("admin","ADMINISTRADOR","admin",_hash("admin123"),"admin",1,_now())
            )

def _hash(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def _now():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")

def _row(row):
    return dict(row) if row else None

def _result(db, rid):
    r = _row(db.execute("SELECT * FROM results WHERE id=?", (rid,)).fetchone())
    if not r:
        return None
    r["notifications"] = [_row(n) for n in
        db.execute("SELECT * FROM notifications WHERE result_id=? ORDER BY notified_at", (rid,)).fetchall()]
    return r

def _all_results(db, hid):
    rows = db.execute("SELECT * FROM results WHERE hospital_id=? ORDER BY created_at", (hid,)).fetchall()
    out = []
    for row in rows:
        r = _row(row)
        r["notifications"] = [_row(n) for n in
            db.execute("SELECT * FROM notifications WHERE result_id=? ORDER BY notified_at", (r["id"],)).fetchall()]
        out.append(r)
    return out

# ────────────────────────────────────────────────────────────────────
# RELATÓRIO
# ────────────────────────────────────────────────────────────────────

def build_report(results, year_filter=""):
    MES = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
    FMT = "%d/%m/%Y %H:%M:%S"
    summary, exams, analysts, rtimes, mresp = {}, {}, {}, [], {}

    for r in results:
        try:
            d, m, y = r["created_at"].split(" ")[0].split("/")
        except:
            continue
        if year_filter and y != year_filter:
            continue
        k = f"{y}-{m}"
        if k not in summary:
            summary[k] = {"key":k, "label":f"{MES[int(m)-1]}/{y}", "year":y,
                          "month":int(m), "total":0, "informado":0, "pendente":0,
                          "avg_response_min":None}
            mresp[k] = []
        summary[k]["total"] += 1
        if r["status"] == "INFORMADO":
            summary[k]["informado"] += 1
        else:
            summary[k]["pendente"] += 1
        exams[r.get("exam","—")] = exams.get(r.get("exam","—"), 0) + 1
        analysts[r.get("technician","—")] = analysts.get(r.get("technician","—"), 0) + 1
        ns = r.get("notifications", [])
        if ns:
            try:
                s = (datetime.strptime(ns[0]["notified_at"], FMT) -
                     datetime.strptime(r["created_at"], FMT)).total_seconds()
                if s >= 0:
                    rtimes.append(s); mresp[k].append(s)
            except:
                pass

    for k, times in mresp.items():
        if times:
            summary[k]["avg_response_min"] = round(sum(times)/len(times)/60, 1)

    months = sorted(summary.values(), key=lambda x: (x["year"], x["month"]))
    return {
        "months":   months,
        "years":    sorted({v["year"] for v in summary.values()}, reverse=True),
        "top_exams":    [{"exam":e,"count":c} for e,c in sorted(exams.items(),   key=lambda x:x[1],reverse=True)[:10]],
        "top_analysts": [{"analyst":a,"count":c} for a,c in sorted(analysts.items(),key=lambda x:x[1],reverse=True)[:10]],
        "total":    sum(v["total"]    for v in summary.values()),
        "informado": sum(v["informado"] for v in summary.values()),
        "pendente":  sum(v["pendente"]  for v in summary.values()),
        "avg_response_min": round(sum(rtimes)/len(rtimes)/60,1) if rtimes else None,
        "min_response_min": round(min(rtimes)/60,1) if rtimes else None,
        "max_response_min": round(max(rtimes)/60,1) if rtimes else None,
    }

# ────────────────────────────────────────────────────────────────────
# DECORATORS
# ────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if "hid" not in session:
            return redirect(url_for("login_page"))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if session.get("role") != "admin":
            return jsonify({"error":"Acesso negado"}), 403
        return f(*a, **kw)
    return dec

# ────────────────────────────────────────────────────────────────────
# ROTAS — AUTENTICAÇÃO
# ────────────────────────────────────────────────────────────────────

@app.route("/")
def root():
    if "hid" not in session:
        return redirect(url_for("login_page"))
    return redirect(url_for("admin_page") if session["role"]=="admin" else url_for("app_page"))

@app.route("/login")
def login_page():
    if "hid" in session:
        return redirect(url_for("root"))
    return render_template("login.html")

@app.route("/api/login", methods=["POST"])
def do_login():
    b = request.json or {}
    u = b.get("username","").strip().lower()
    p = b.get("password","")
    with get_db() as db:
        h = _row(db.execute("SELECT * FROM hospitals WHERE LOWER(username)=?", (u,)).fetchone())
    if not h or h["password"] != _hash(p):
        return jsonify({"error":"Usuário ou senha incorretos."}), 401
    if not h["active"]:
        return jsonify({"error":"Acesso desativado. Contate o administrador."}), 403
    session.update(hid=h["id"], hname=h["name"], role=h["role"], uname=h["username"])
    return jsonify({"role":h["role"],"name":h["name"]})

@app.route("/api/logout", methods=["POST"])
def do_logout():
    session.clear()
    return jsonify({"ok":True})

# ────────────────────────────────────────────────────────────────────
# ROTAS — ADMIN
# ────────────────────────────────────────────────────────────────────

@app.route("/admin")
@login_required
def admin_page():
    if session["role"] != "admin":
        return redirect(url_for("app_page"))
    return render_template("admin.html", hname=session["hname"], uname=session["uname"])

@app.route("/api/admin/hospitals", methods=["GET"])
@login_required
@admin_required
def admin_list():
    with get_db() as db:
        rows = db.execute("SELECT * FROM hospitals WHERE role!='admin' ORDER BY name").fetchall()
        result = []
        for row in rows:
            h = _row(row)
            h["results_count"] = db.execute(
                "SELECT COUNT(*) c FROM results WHERE hospital_id=?", (h["id"],)).fetchone()["c"]
            del h["password"]
            result.append(h)
    return jsonify(result)

@app.route("/api/admin/hospitals", methods=["POST"])
@login_required
@admin_required
def admin_create():
    b = request.json or {}
    name = b.get("name","").strip().upper()
    uname = b.get("username","").strip().lower()
    pw   = b.get("password","").strip()
    if not all([name, uname, pw]):
        return jsonify({"error":"Preencha todos os campos."}), 400
    hid = str(uuid.uuid4())[:8]
    try:
        with get_db() as db:
            db.execute("INSERT INTO hospitals VALUES (?,?,?,?,?,?,?)",
                       (hid, name, uname, _hash(pw), "hospital", 1, _now()))
    except sqlite3.IntegrityError:
        return jsonify({"error":"Usuário já existe."}), 409
    return jsonify({"id":hid,"name":name,"username":uname}), 201

@app.route("/api/admin/hospitals/<hid>/toggle", methods=["POST"])
@login_required
@admin_required
def admin_toggle(hid):
    with get_db() as db:
        row = db.execute("SELECT active FROM hospitals WHERE id=?", (hid,)).fetchone()
        if not row:
            return jsonify({"error":"Não encontrado"}), 404
        new = 0 if row["active"] else 1
        db.execute("UPDATE hospitals SET active=? WHERE id=?", (new, hid))
    return jsonify({"active": bool(new)})

@app.route("/api/admin/hospitals/<hid>/password", methods=["POST"])
@login_required
@admin_required
def admin_reset_pw(hid):
    pw = (request.json or {}).get("password","").strip()
    if not pw:
        return jsonify({"error":"Informe a nova senha."}), 400
    with get_db() as db:
        db.execute("UPDATE hospitals SET password=? WHERE id=?", (_hash(pw), hid))
    return jsonify({"ok":True})

@app.route("/api/admin/hospitals/<hid>", methods=["DELETE"])
@login_required
@admin_required
def admin_delete(hid):
    with get_db() as db:
        rids = [r["id"] for r in db.execute("SELECT id FROM results WHERE hospital_id=?", (hid,)).fetchall()]
        for rid in rids:
            db.execute("DELETE FROM notifications WHERE result_id=?", (rid,))
        db.execute("DELETE FROM results WHERE hospital_id=?", (hid,))
        db.execute("DELETE FROM hospitals WHERE id=?", (hid,))
    return jsonify({"ok":True})

@app.route("/api/admin/report")
@login_required
@admin_required
def admin_report():
    with get_db() as db:
        hospitals = db.execute("SELECT * FROM hospitals WHERE role!='admin' ORDER BY name").fetchall()
        out = []
        for h in hospitals:
            rpt = build_report(_all_results(db, h["id"]))
            out.append({"id":h["id"],"name":h["name"],"active":h["active"],
                        "total":rpt["total"],"informado":rpt["informado"],
                        "pendente":rpt["pendente"],"avg_response_min":rpt["avg_response_min"]})
    return jsonify(out)

# ────────────────────────────────────────────────────────────────────
# ROTAS — APP HOSPITAL
# ────────────────────────────────────────────────────────────────────

@app.route("/app")
@login_required
def app_page():
    if session["role"] == "admin":
        return redirect(url_for("admin_page"))
    return render_template("index.html", hname=session["hname"], uname=session["uname"])

@app.route("/api/results")
@login_required
def results_list():
    with get_db() as db:
        return jsonify(_all_results(db, session["hid"]))

@app.route("/api/results", methods=["POST"])
@login_required
def results_create():
    b   = request.json or {}
    hid = session["hid"]
    rid = str(uuid.uuid4())
    prot = "RC-" + datetime.now().strftime("%Y%m%d") + "-" + str(uuid.uuid4())[:6].upper()
    ts  = _now()
    with get_db() as db:
        db.execute("INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?)",
                   (rid, hid, prot, b.get("technician",""), b.get("exam",""),
                    b.get("patient",""), b.get("value",""), ts, "PENDENTE"))
    return jsonify({"id":rid,"hospital_id":hid,"protocol":prot,
                    "technician":b.get("technician",""),"exam":b.get("exam",""),
                    "patient":b.get("patient",""),"value":b.get("value",""),
                    "created_at":ts,"status":"PENDENTE","notifications":[]}), 201

@app.route("/api/results/<rid>")
@login_required
def results_get(rid):
    with get_db() as db:
        r = _result(db, rid)
    return jsonify(r) if r else (jsonify({"error":"Não encontrado"}), 404)

@app.route("/api/results/<rid>/notify", methods=["POST"])
@login_required
def results_notify(rid):
    b   = request.json or {}
    nid = str(uuid.uuid4())
    ts  = _now()
    with get_db() as db:
        db.execute("INSERT INTO notifications VALUES (?,?,?,?,?,?)",
                   (nid, rid, b.get("notified_to",""), b.get("role",""), ts, b.get("notes","")))
        db.execute("UPDATE results SET status='INFORMADO' WHERE id=?", (rid,))
        r = _result(db, rid)
    return jsonify(r)

@app.route("/api/report/monthly")
@login_required
def report_monthly():
    with get_db() as db:
        results = _all_results(db, session["hid"])
    return jsonify(build_report(results, request.args.get("year","")))

# ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
