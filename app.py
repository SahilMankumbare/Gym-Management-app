import csv
import io
import os
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from urllib.parse import quote

from flask import (
    Flask,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "gym.db")

app = Flask(__name__)
app.secret_key = "gym-management-secret-key-change-me"

COUNTRY_CODE = "91"

PLANS = {
    "Monthly": {"days": 30, "price": 1500},
    "Quarterly": {"days": 90, "price": 4000},
    "Half-Yearly": {"days": 180, "price": 7500},
    "Yearly": {"days": 365, "price": 13000},
}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            plan TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            list_amount REAL NOT NULL DEFAULT 0,
            discount REAL NOT NULL DEFAULT 0,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Active',
            notes TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER,
            member_name TEXT NOT NULL,
            amount REAL NOT NULL,
            list_amount REAL NOT NULL DEFAULT 0,
            discount REAL NOT NULL DEFAULT 0,
            plan TEXT NOT NULL,
            paid_on TEXT NOT NULL,
            FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trainers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            role TEXT NOT NULL DEFAULT 'Trainer',
            salary REAL NOT NULL DEFAULT 0,
            joined_on TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trainer_id INTEGER NOT NULL,
            att_date TEXT NOT NULL,
            present INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            UNIQUE (trainer_id, att_date),
            FOREIGN KEY (trainer_id) REFERENCES trainers (id) ON DELETE CASCADE
        );
        """
    )
    if not conn.execute("SELECT 1 FROM users WHERE username = 'Admin'").fetchone():
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("Admin", generate_password_hash("gymbroch@9353")),
        )
    migrate(conn)
    conn.commit()
    conn.close()


def migrate(conn):
    """Add new columns to existing databases without losing data."""
    wanted = {
        "members": {"list_amount": "REAL NOT NULL DEFAULT 0", "discount": "REAL NOT NULL DEFAULT 0"},
        "payments": {"list_amount": "REAL NOT NULL DEFAULT 0", "discount": "REAL NOT NULL DEFAULT 0"},
    }
    for table, cols in wanted.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, decl in cols.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def days_left(end_date):
    return (parse_date(end_date) - date.today()).days


def clean_phone(phone):
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith(COUNTRY_CODE) and len(digits) > 10:
        return digits
    if len(digits) == 10:
        return COUNTRY_CODE + digits
    return digits


def whatsapp_link(phone, message):
    return f"https://wa.me/{clean_phone(phone)}?text={quote(message)}"


def compute_pricing(plan, mode, value):
    list_price = PLANS[plan]["price"]
    try:
        val = float(value)
    except (TypeError, ValueError):
        val = 0.0
    val = max(val, 0.0)
    if mode == "percent":
        discount = list_price * min(val, 100) / 100
    else:
        discount = val
    discount = min(discount, list_price)
    final = max(list_price - discount, 0.0)
    return list_price, round(discount, 2), round(final, 2)


def member_status(end_date):
    left = days_left(end_date)
    if left < 0:
        return "Expired"
    if left <= 7:
        return "Expiring Soon"
    return "Active"


@app.context_processor
def inject_globals():
    return {
        "today": date.today(),
        "whatsapp_link": whatsapp_link,
        "days_left": days_left,
        "member_status": member_status,
    }


@app.after_request
def no_cache(resp):
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


@app.before_request
def require_login():
    allowed = {"login", "static"}
    if request.endpoint not in allowed and "user" not in session:
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user"] = user["username"]
            flash(f"Welcome back, {username}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


@app.route("/")
def dashboard():
    db = get_db()
    members = db.execute("SELECT * FROM members ORDER BY end_date ASC").fetchall()

    total_members = len(members)
    active = sum(1 for m in members if member_status(m["end_date"]) == "Active")
    expiring = [m for m in members if member_status(m["end_date"]) == "Expiring Soon"]
    expired = sum(1 for m in members if member_status(m["end_date"]) == "Expired")

    this_month = date.today().strftime("%Y-%m")
    month_payments = db.execute(
        "SELECT * FROM payments WHERE substr(paid_on, 1, 7) = ? ORDER BY paid_on DESC",
        (this_month,),
    ).fetchall()
    month_revenue = sum(p["amount"] for p in month_payments)
    total_revenue = db.execute("SELECT COALESCE(SUM(amount), 0) AS t FROM payments").fetchone()["t"]

    plan_rows = db.execute(
        "SELECT plan, COUNT(*) AS c, COALESCE(SUM(amount), 0) AS rev FROM members GROUP BY plan"
    ).fetchall()

    return render_template(
        "dashboard.html",
        total_members=total_members,
        active=active,
        expiring_count=len(expiring),
        expired=expired,
        month_revenue=month_revenue,
        total_revenue=total_revenue,
        month_payments=month_payments,
        expiring=expiring[:8],
        recent=members[:6],
        plan_rows=plan_rows,
        month_label=date.today().strftime("%B %Y"),
    )


def last_n_months(n):
    today = date.today()
    y, m = today.year, today.month
    out = []
    for i in range(n - 1, -1, -1):
        mm = m - i
        yy = y
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append((yy, mm))
    return out


def prev_month_key():
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1:04d}-12"
    return f"{today.year:04d}-{today.month - 1:02d}"


@app.route("/analytics")
def analytics():
    db = get_db()
    member_rows = db.execute("SELECT * FROM members").fetchall()
    pay_rows = db.execute("SELECT * FROM payments").fetchall()

    today = date.today()
    this_key = today.strftime("%Y-%m")
    last_key = prev_month_key()

    rev_series = []
    growth_series = []
    for (yy, mm) in last_n_months(6):
        key = f"{yy:04d}-{mm:02d}"
        label = datetime(yy, mm, 1).strftime("%b")
        rev_series.append({
            "label": label,
            "value": sum(p["amount"] for p in pay_rows if p["paid_on"][:7] == key),
        })
        growth_series.append({
            "label": label,
            "value": sum(1 for m in member_rows if m["start_date"][:7] == key),
        })

    max_rev = max([r["value"] for r in rev_series] + [1])
    max_growth = max([g["value"] for g in growth_series] + [1])

    plan_rows = db.execute(
        "SELECT plan, COUNT(*) AS c, COALESCE(SUM(amount), 0) AS rev FROM members GROUP BY plan"
    ).fetchall()
    plan_total = sum(r["c"] for r in plan_rows) or 1
    plan_colors = {
        "Monthly": "#FFD400",
        "Quarterly": "#FBBF24",
        "Half-Yearly": "#F59E0B",
        "Yearly": "#B45309",
    }
    plans = []
    for r in plan_rows:
        plans.append({
            "plan": r["plan"],
            "count": r["c"],
            "rev": r["rev"],
            "pct": round(r["c"] / plan_total * 100),
            "color": plan_colors.get(r["plan"], "#71717a"),
        })
    plans.sort(key=lambda x: -x["count"])

    status_counts = {"Active": 0, "Expiring Soon": 0, "Expired": 0}
    for m in member_rows:
        status_counts[member_status(m["end_date"])] += 1

    this_month_rev = sum(p["amount"] for p in pay_rows if p["paid_on"][:7] == this_key)
    last_month_rev = sum(p["amount"] for p in pay_rows if p["paid_on"][:7] == last_key)
    growth = ((this_month_rev - last_month_rev) / last_month_rev * 100) if last_month_rev else 0

    total_revenue = sum(p["amount"] for p in pay_rows)
    total_members = len(member_rows)
    arpu = total_revenue / total_members if total_members else 0
    new_this_month = sum(1 for m in member_rows if m["start_date"][:7] == this_key)
    renewals = db.execute("SELECT COUNT(*) AS c FROM payments").fetchone()["c"] - total_members

    top = db.execute(
        """SELECT member_name, SUM(amount) AS spend, COUNT(*) AS txn
           FROM payments GROUP BY member_name ORDER BY spend DESC LIMIT 5"""
    ).fetchall()
    max_spend = max([t["spend"] for t in top] + [1])

    return render_template(
        "analytics.html",
        rev_series=rev_series,
        growth_series=growth_series,
        max_rev=max_rev,
        max_growth=max_growth,
        plans=plans,
        status_counts=status_counts,
        this_month_rev=this_month_rev,
        last_month_rev=last_month_rev,
        growth=growth,
        total_revenue=total_revenue,
        arpu=arpu,
        new_this_month=new_this_month,
        renewals=max(renewals, 0),
        total_members=total_members,
        top=top,
        max_spend=max_spend,
        month_label=today.strftime("%B %Y"),
    )


@app.route("/members")
def members():
    db = get_db()
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "")

    rows = db.execute("SELECT * FROM members ORDER BY end_date ASC").fetchall()
    data = []
    for m in rows:
        item = dict(m)
        item["st"] = member_status(m["end_date"])
        item["left"] = days_left(m["end_date"])
        if q and q.lower() not in (m["name"] + " " + m["phone"]).lower():
            continue
        if status_filter and item["st"] != status_filter:
            continue
        data.append(item)

    return render_template(
        "members.html",
        members=data,
        q=q,
        status_filter=status_filter,
    )


@app.route("/add", methods=["GET", "POST"])
def add_member():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        plan = request.form.get("plan", "Monthly")
        start_raw = request.form.get("start_date") or date.today().isoformat()
        mode = request.form.get("discount_mode", "amount")
        dvalue = request.form.get("discount_value", "0")
        notes = request.form.get("notes", "").strip()

        errors = []
        if not name:
            errors.append("Member name is required.")
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) < 10:
            errors.append("A valid 10-digit phone number is required.")
        if plan not in PLANS:
            errors.append("Please choose a valid plan.")
        if mode not in ("amount", "percent"):
            mode = "amount"
        try:
            start = parse_date(start_raw)
        except ValueError:
            errors.append("Please choose a valid start date.")
            start = date.today()

        if errors:
            for e in errors:
                flash(e, "error")
            return redirect(url_for("add_member"))

        list_price, discount, amount = compute_pricing(plan, mode, dvalue)
        end = start + timedelta(days=PLANS[plan]["days"])

        db = get_db()
        cur = db.execute(
            """INSERT INTO members
               (name, phone, email, plan, amount, list_amount, discount, start_date, end_date, status, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active', ?, ?)""",
            (
                name,
                phone,
                email,
                plan,
                amount,
                list_price,
                discount,
                start.isoformat(),
                end.isoformat(),
                notes,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        db.execute(
            """INSERT INTO payments (member_id, member_name, amount, list_amount, discount, plan, paid_on)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cur.lastrowid, name, amount, list_price, discount, plan, start.isoformat()),
        )
        db.commit()
        flash(f"Member {name} added successfully.", "success")
        return redirect(url_for("members"))

    return render_template("add_member.html", plans=PLANS, default_plan="Monthly")


@app.route("/renew/<int:member_id>", methods=["POST"])
def renew(member_id):
    db = get_db()
    m = db.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
    if not m:
        flash("Member not found.", "error")
        return redirect(url_for("members"))

    plan = request.form.get("plan") or m["plan"]
    if plan not in PLANS:
        plan = "Monthly"
    amount = PLANS[plan]["price"]
    today = date.today()
    base = today if days_left(m["end_date"]) < 0 else parse_date(m["end_date"])
    new_end = base + timedelta(days=PLANS[plan]["days"])

    db.execute(
        "UPDATE members SET plan = ?, amount = ?, end_date = ?, status = 'Active' WHERE id = ?",
        (plan, amount, new_end.isoformat(), member_id),
    )
    db.execute(
        """INSERT INTO payments (member_id, member_name, amount, list_amount, discount, plan, paid_on)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (member_id, m["name"], amount, PLANS[plan]["price"], 0, plan, today.isoformat()),
    )
    db.commit()
    flash(f"{m['name']} renewed on {plan} plan.", "success")
    return redirect(request.referrer or url_for("members"))


@app.route("/delete/<int:member_id>", methods=["POST"])
def delete_member(member_id):
    db = get_db()
    m = db.execute("SELECT name FROM members WHERE id = ?", (member_id,)).fetchone()
    db.execute("DELETE FROM payments WHERE member_id = ?", (member_id,))
    db.execute("DELETE FROM members WHERE id = ?", (member_id,))
    db.execute(
        "DELETE FROM payments WHERE member_id IS NULL OR member_id NOT IN (SELECT id FROM members)"
    )
    db.commit()
    if m:
        flash(f"{m['name']} and their transactions were removed.", "success")
    else:
        flash("Member not found.", "error")
    return redirect(url_for("members"))


@app.route("/payments")
def payments():
    db = get_db()
    rows = db.execute("SELECT * FROM payments ORDER BY paid_on DESC, id DESC").fetchall()
    total = sum(r["amount"] for r in rows)
    return render_template("payments.html", payments=rows, total=total)


# ---------------------------------------------------------------------------
# Trainers
# ---------------------------------------------------------------------------
@app.route("/trainers", methods=["GET", "POST"])
def trainers():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        role = request.form.get("role", "").strip() or "Trainer"
        salary_raw = request.form.get("salary", "0").strip()
        joined = request.form.get("joined_on") or date.today().isoformat()

        errors = []
        if not name:
            errors.append("Trainer name is required.")
        if len("".join(ch for ch in phone if ch.isdigit())) < 10:
            errors.append("A valid 10-digit phone number is required.")
        try:
            parse_date(joined)
        except ValueError:
            errors.append("Please choose a valid joining date.")
            joined = date.today().isoformat()
        try:
            salary = float(salary_raw) if salary_raw else 0.0
        except (TypeError, ValueError):
            errors.append("Salary must be a number.")
            salary = 0.0

        if errors:
            for e in errors:
                flash(e, "error")
            return redirect(url_for("trainers"))

        db.execute(
            """INSERT INTO trainers (name, phone, email, role, salary, joined_on, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            (name, phone, email, role, salary, joined, datetime.now().isoformat(timespec="seconds")),
        )
        db.commit()
        flash(f"Trainer {name} added successfully.", "success")
        return redirect(url_for("trainers"))

    cutoff = (date.today() - timedelta(days=30)).isoformat()
    stats = {
        r["trainer_id"]: r
        for r in db.execute(
            """SELECT trainer_id, COUNT(*) AS marked, SUM(present) AS present
               FROM attendance WHERE att_date >= ? GROUP BY trainer_id""",
            (cutoff,),
        ).fetchall()
    }
    data = []
    for r in db.execute("SELECT * FROM trainers ORDER BY active DESC, name").fetchall():
        d = dict(r)
        s = stats.get(r["id"])
        d["marked"] = s["marked"] if s else 0
        d["present"] = s["present"] if s else 0
        d["pct"] = round(d["present"] / d["marked"] * 100) if d["marked"] else None
        data.append(d)
    return render_template("trainers.html", trainers=data)


@app.route("/trainers/<int:tid>/delete", methods=["POST"])
def delete_trainer(tid):
    db = get_db()
    db.execute("DELETE FROM attendance WHERE trainer_id = ?", (tid,))
    db.execute("DELETE FROM trainers WHERE id = ?", (tid,))
    db.commit()
    flash("Trainer and attendance records removed.", "success")
    return redirect(url_for("trainers"))


@app.route("/trainers/<int:tid>/toggle", methods=["POST"])
def toggle_trainer(tid):
    db = get_db()
    db.execute("UPDATE trainers SET active = 1 - active WHERE id = ?", (tid,))
    db.commit()
    return redirect(url_for("trainers"))


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------
@app.route("/attendance", methods=["GET", "POST"])
def attendance():
    db = get_db()
    today = date.today().isoformat()

    if request.method == "POST":
        att_date = request.form.get("att_date") or today
        for t in db.execute("SELECT id FROM trainers WHERE active = 1").fetchall():
            present = 1 if request.form.get(f"present_{t['id']}") else 0
            db.execute(
                """INSERT INTO attendance (trainer_id, att_date, present, notes)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(trainer_id, att_date)
                   DO UPDATE SET present = excluded.present, notes = excluded.notes""",
                (t["id"], att_date, present, request.form.get(f"note_{t['id']}", "").strip()),
            )
        db.commit()
        flash(f"Attendance saved for {att_date}.", "success")
        return redirect(url_for("attendance", date=att_date))

    att_date = request.args.get("date") or today
    try:
        parse_date(att_date)
    except ValueError:
        att_date = today

    trainers = [
        dict(t)
        for t in db.execute("SELECT * FROM trainers WHERE active = 1 ORDER BY name").fetchall()
    ]
    saved = {
        r["trainer_id"]: r
        for r in db.execute("SELECT * FROM attendance WHERE att_date = ?", (att_date,)).fetchall()
    }
    for t in trainers:
        t["present"] = bool(saved[t["id"]]["present"]) if t["id"] in saved else False

    cutoff = (date.today() - timedelta(days=30)).isoformat()
    history = db.execute(
        """SELECT t.id, t.name, COUNT(a.id) AS marked, COALESCE(SUM(a.present),0) AS present
           FROM trainers t
           LEFT JOIN attendance a ON a.trainer_id = t.id AND a.att_date >= ?
           GROUP BY t.id ORDER BY t.name""",
        (cutoff,),
    ).fetchall()
    return render_template(
        "attendance.html",
        trainers=trainers,
        att_date=att_date,
        today=today,
        history=history,
        cutoff=cutoff,
    )


# ---------------------------------------------------------------------------
# Reports / Export
# ---------------------------------------------------------------------------
REPORT_TYPES = ("members", "payments", "trainers", "attendance")
REPORT_COLUMNS = {
    "members": ["Name", "Phone", "Email", "Plan", "List Price", "Discount", "Paid",
                "Start Date", "End Date", "Status"],
    "payments": ["Paid On", "Member", "Plan", "List Amount", "Discount", "Paid"],
    "trainers": ["Name", "Phone", "Email", "Role", "Salary", "Joined On", "Status", "Attendance % (30d)"],
    "attendance": ["Date", "Trainer", "Status"],
}


def esc(v):
    return (
        str(v)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_xls_html(title, cols, data):
    head = "".join(f"<th style='background:#ffd400;color:#000;font-weight:bold'>{esc(c)}</th>" for c in cols)
    body = ""
    for row in data:
        body += "<tr>" + "".join(f"<td>{esc(row[c])}</td>" for c in cols) + "</tr>"
    return (
        "<html xmlns:x='urn:schemas-microsoft-com:office:excel'><head><meta charset='UTF-8'>"
        f"<title>{esc(title)}</title></head><body>"
        f"<table border='1'>{head}<tbody>{body}</tbody></table></body></html>"
    )


def build_report(rtype, start="", end=""):
    db = get_db()

    if rtype == "members":
        rows = db.execute("SELECT * FROM members ORDER BY start_date DESC, id DESC").fetchall()
        data = []
        for m in rows:
            data.append({
                "Name": m["name"],
                "Phone": "+" + m["phone"],
                "Email": m["email"] or "",
                "Plan": m["plan"],
                "List Price": m["list_amount"],
                "Discount": m["discount"],
                "Paid": m["amount"],
                "Start Date": m["start_date"],
                "End Date": m["end_date"],
                "Status": member_status(m["end_date"]),
            })
        return REPORT_COLUMNS["members"], data, "Members"

    if rtype == "payments":
        sql = "SELECT * FROM payments WHERE 1=1"
        args = []
        if start:
            sql += " AND paid_on >= ?"
            args.append(start)
        if end:
            sql += " AND paid_on <= ?"
            args.append(end)
        sql += " ORDER BY paid_on DESC, id DESC"
        data = []
        for p in db.execute(sql, args).fetchall():
            data.append({
                "Paid On": p["paid_on"],
                "Member": p["member_name"],
                "Plan": p["plan"],
                "List Amount": p["list_amount"],
                "Discount": p["discount"],
                "Paid": p["amount"],
            })
        return REPORT_COLUMNS["payments"], data, "Payments"

    if rtype == "trainers":
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        stats = {
            r["trainer_id"]: r
            for r in db.execute(
                """SELECT trainer_id, COUNT(*) AS marked, SUM(present) AS present
                   FROM attendance WHERE att_date >= ? GROUP BY trainer_id""",
                (cutoff,),
            ).fetchall()
        }
        data = []
        for t in db.execute("SELECT * FROM trainers ORDER BY active DESC, name").fetchall():
            s = stats.get(t["id"])
            marked = s["marked"] if s else 0
            present = s["present"] if s else 0
            pct = round(present / marked * 100) if marked else ""
            data.append({
                "Name": t["name"],
                "Phone": "+" + t["phone"],
                "Email": t["email"] or "",
                "Role": t["role"],
                "Salary": t["salary"],
                "Joined On": t["joined_on"],
                "Status": "Active" if t["active"] else "Inactive",
                "Attendance % (30d)": pct,
            })
        return REPORT_COLUMNS["trainers"], data, "Trainers"

    sql = """SELECT a.att_date, t.name, a.present, a.notes
             FROM attendance a JOIN trainers t ON t.id = a.trainer_id WHERE 1=1"""
    args = []
    if start:
        sql += " AND a.att_date >= ?"
        args.append(start)
    if end:
        sql += " AND a.att_date <= ?"
        args.append(end)
    sql += " ORDER BY a.att_date DESC, t.name"
    data = []
    for r in db.execute(sql, args).fetchall():
        data.append({"Date": r["att_date"], "Trainer": r["name"], "Status": "Present" if r["present"] else "Absent"})
    return REPORT_COLUMNS["attendance"], data, "Trainer Attendance"


@app.route("/reports")
def reports():
    rtype = request.args.get("type", "members")
    if rtype not in REPORT_TYPES:
        rtype = "members"
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    cols, data, title = build_report(rtype, start, end)
    return render_template(
        "reports.html",
        rtype=rtype,
        start=start,
        end=end,
        cols=cols,
        data=data[:20],
        total=len(data),
        title=title,
        today=date.today().isoformat(),
        report_types=list(REPORT_TYPES),
    )


@app.route("/reports/export")
def report_export():
    rtype = request.args.get("type", "members")
    if rtype not in REPORT_TYPES:
        rtype = "members"
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    fmt = request.args.get("format", "csv")
    cols, data, title = build_report(rtype, start, end)
    fname = f"gymbroch_{rtype}_{date.today().isoformat()}"

    if fmt == "xls":
        return Response(
            build_xls_html(title, cols, data),
            mimetype="application/vnd.ms-excel",
            headers={"Content-Disposition": f"attachment; filename={fname}.xls"},
        )

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(cols)
    for row in data:
        writer.writerow([row[c] for c in cols])
    return Response(
        buf.getvalue().encode("utf-8"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={fname}.csv"},
    )


init_db()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
