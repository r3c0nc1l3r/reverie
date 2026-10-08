"""FieldOps data layer: SQLite schema, synthetic seed data, and the work order state machine."""

import hashlib
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(os.environ.get("FIELDOPS_DB") or Path(__file__).parent / "data" / "fieldops.db")

STATUSES = ["New", "Scheduled", "En route", "In progress", "Completed", "Invoiced", "Cancelled"]
OPEN_FOR_DISPATCH = ("New", "Scheduled")
CANCELLABLE = ("New", "Scheduled", "En route")
ON_BOARD = ("Scheduled", "En route", "In progress", "Completed")
ACTIVE = ("Scheduled", "En route", "In progress")
PRIORITIES = ["Low", "Normal", "High", "Urgent"]
SLA_DAYS = {"Urgent": 1, "High": 2, "Normal": 5, "Low": 10}
LABOR_RATE_CENTS = 9500
CHECKLIST = ["Isolate power and confirm the unit is safe", "Inspect the unit and record the fault",
             "Repair or replace the failed components", "Test operation with the customer present",
             "Clean the work area"]

SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
  email TEXT NOT NULL, salt TEXT NOT NULL, pw_hash TEXT NOT NULL);
CREATE TABLE sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL);
CREATE TABLE sites (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), name TEXT NOT NULL,
  address TEXT NOT NULL);
CREATE TABLE parts (id INTEGER PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, unit_price_cents INTEGER NOT NULL);
CREATE TABLE work_orders (id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES customers(id), site_id INTEGER NOT NULL REFERENCES sites(id),
  title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', priority TEXT NOT NULL, sla_due TEXT NOT NULL,
  status TEXT NOT NULL, technician_id INTEGER REFERENCES users(id), sched_date TEXT, start_min INTEGER,
  duration_min INTEGER, labor_hours REAL, notes TEXT NOT NULL DEFAULT '', signature_name TEXT,
  signature_ok INTEGER NOT NULL DEFAULT 0, created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL,
  completed_at TEXT, cancel_reason TEXT);
CREATE TABLE checklist (id INTEGER PRIMARY KEY, wo_id INTEGER NOT NULL REFERENCES work_orders(id),
  position INTEGER NOT NULL, label TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0);
CREATE TABLE wo_parts (id INTEGER PRIMARY KEY, wo_id INTEGER NOT NULL REFERENCES work_orders(id),
  part_id INTEGER NOT NULL REFERENCES parts(id), qty INTEGER NOT NULL);
CREATE TABLE invoices (id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL, wo_id INTEGER UNIQUE NOT NULL
  REFERENCES work_orders(id), labor_hours REAL NOT NULL, labor_rate_cents INTEGER NOT NULL, labor_cents INTEGER NOT NULL,
  parts_cents INTEGER NOT NULL, total_cents INTEGER NOT NULL, status TEXT NOT NULL, issued_at TEXT NOT NULL,
  paid_at TEXT, payment_ref TEXT);
CREATE TABLE activity (id INTEGER PRIMARY KEY, wo_id INTEGER NOT NULL REFERENCES work_orders(id), at TEXT NOT NULL,
  actor TEXT NOT NULL, message TEXT NOT NULL);
CREATE TABLE notifications (id INTEGER PRIMARY KEY, at TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL,
  body TEXT NOT NULL, wo_id INTEGER REFERENCES work_orders(id));
"""

# Synthetic demo accounts. These passwords are public demo values, not secrets.
DEMO_PASSWORD = "fieldops-demo"
USERS = [("dana.dispatch", "Dana Reyes", "dispatcher"), ("tom.tech", "Tomas Nguyen", "technician"),
         ("priya.tech", "Priya Shah", "technician"), ("mia.manager", "Mia Okafor", "manager")]
CUSTOMERS = [
    ("Harbor View Apartments", "facilities@harborview.example", "555-0140",
     [("Harbor View — Building A", "400 Harbor Road, Unit A"), ("Harbor View — Building B", "402 Harbor Road, Unit B")]),
    ("Lumen Bakery", "owner@lumenbakery.example", "555-0172", [("Lumen Bakery — 12 Mill Street", "12 Mill Street")]),
    ("Northgate Clinic", "ops@northgateclinic.example", "555-0115",
     [("Northgate Clinic — Main", "88 Northgate Avenue"), ("Northgate Clinic — Annex", "90 Northgate Avenue")]),
    ("Ridge Line Storage", "manager@ridgeline.example", "555-0198", [("Ridge Line — Depot", "7 Quarry Lane")]),
]
PARTS = [("AF-1625", "Air filter 16x25", 1250), ("CAP-45", "Run capacitor 45/5 uF", 2800),
         ("CP-120", "Condensate pump", 8900), ("TH-200", "Programmable thermostat", 14500),
         ("BLT-A42", "Blower belt A42", 1675), ("REF-410", "Refrigerant R-410A (1 lb)", 3600)]


def today():
    return date.today()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def reset():
    """Delete the database and write the schema and the synthetic seed data again."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(str(DB_PATH) + suffix)
        if path.exists():
            path.unlink()
    db = connect()
    db.executescript(SCHEMA)
    seed(db)
    db.commit()
    db.close()


def ensure():
    if not DB_PATH.exists():
        reset()


def seed(db):
    for username, name, role in USERS:
        salt = secrets.token_hex(8)
        db.execute("INSERT INTO users (username, name, role, email, salt, pw_hash) VALUES (?,?,?,?,?,?)",
                   (username, name, role, f"{username}@fieldops.example", salt, hash_pw(DEMO_PASSWORD, salt)))
    for name, email, phone, sites in CUSTOMERS:
        cid = db.execute("INSERT INTO customers (name, email, phone) VALUES (?,?,?)", (name, email, phone)).lastrowid
        for site, address in sites:
            db.execute("INSERT INTO sites (customer_id, name, address) VALUES (?,?,?)", (cid, site, address))
    db.executemany("INSERT INTO parts (sku, name, unit_price_cents) VALUES (?,?,?)", PARTS)

    uid = {r["username"]: r["id"] for r in db.execute("SELECT id, username FROM users")}
    site = {r["name"]: (r["id"], r["customer_id"]) for r in db.execute("SELECT id, name, customer_id FROM sites")}
    part = {r["sku"]: r["id"] for r in db.execute("SELECT id, sku FROM parts")}
    t = today()
    d = lambda n: (t + timedelta(days=n)).isoformat()  # noqa: E731

    def wo(number, site_name, title, priority, status, tech=None, day=None, start=None, hours=2, sla=None,
           desc="", created=-2):
        site_id, cust_id = site[site_name]
        created_at = (datetime.now() + timedelta(days=created)).replace(hour=8, minute=15, second=0)
        wid = db.execute(
            "INSERT INTO work_orders (number, customer_id, site_id, title, description, priority, sla_due, status,"
            " technician_id, sched_date, start_min, duration_min, created_by, created_at) VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, cust_id, site_id, title, desc, priority, sla or d(SLA_DAYS[priority]), status,
             uid.get(tech), None if day is None else d(day), None if start is None else start * 60,
             None if day is None else int(hours * 60), uid["dana.dispatch"], created_at.strftime("%Y-%m-%d %H:%M:%S"))
        ).lastrowid
        for i, label in enumerate(CHECKLIST):
            db.execute("INSERT INTO checklist (wo_id, position, label, done) VALUES (?,?,?,?)",
                       (wid, i, label, 1 if status in ("Completed", "Invoiced") else 0))
        at = created_at.strftime("%Y-%m-%d %H:%M:%S")
        db.execute("INSERT INTO activity (wo_id, at, actor, message) VALUES (?,?,?,?)",
                   (wid, at, "Dana Reyes", f"Created work order ({priority} priority)"))
        if tech:
            name = dict((u, n) for u, n, _ in USERS)[tech]
            db.execute("INSERT INTO activity (wo_id, at, actor, message) VALUES (?,?,?,?)",
                       (wid, at, "Dana Reyes", f"Assigned to {name} on {d(day)} at {start:02d}:00"))
        return wid

    wo("WO-1001", "Northgate Clinic — Main", "Exam room 3 too warm", "Normal", "New",
       desc="Staff report exam room 3 stays above 26 °C in the afternoon.", created=-1)
    wo("WO-1002", "Harbor View — Building A", "No heat in the lobby", "High", "Scheduled", "tom.tech", 0, 8,
       desc="Lobby air handler runs but blows cold air. Door code 4471.")
    wo("WO-1003", "Ridge Line — Depot", "Quarterly rooftop unit service", "Low", "Scheduled", "tom.tech", 0, 13,
       desc="Planned maintenance: filters, belts, coil clean.", created=-6)
    wo("WO-1004", "Northgate Clinic — Annex", "Thermostat not responding", "Normal", "Scheduled", "priya.tech", 0, 9,
       desc="Annex thermostat display is blank.")
    wo("WO-1005", "Harbor View — Building B", "Water leak under air handler", "Urgent", "Scheduled", "priya.tech", 0,
       10, desc="Water pooling under the air handler in the plant room.", created=-1)
    wo("WO-1006", "Lumen Bakery — 12 Mill Street", "Proofing room humidity alarm", "High", "New",
       desc="Humidity alarm trips every morning at about 05:00.", created=-1)
    wo("WO-1007", "Ridge Line — Depot", "Office split unit noisy", "Normal", "New", desc="Rattle from the outdoor unit.",
       created=0)
    w8 = wo("WO-1008", "Northgate Clinic — Main", "Replace failed capacitor and filters", "High", "Completed",
            "priya.tech", -1, 9, desc="Condenser fan not starting.", created=-3)
    db.execute("UPDATE work_orders SET labor_hours=2.0, signature_name='Grace Lin', signature_ok=1, completed_at=?,"
               " notes='Replaced run capacitor; changed three filters.' WHERE id=?",
               (f"{d(-1)} 11:20:00", w8))
    db.executemany("INSERT INTO wo_parts (wo_id, part_id, qty) VALUES (?,?,?)",
                   [(w8, part["AF-1625"], 3), (w8, part["CAP-45"], 1)])
    db.executemany("INSERT INTO activity (wo_id, at, actor, message) VALUES (?,?,?,?)",
                   [(w8, f"{d(-1)} 08:31:00", "Priya Shah", "Started travel"),
                    (w8, f"{d(-1)} 08:58:00", "Priya Shah", "Arrived on site"),
                    (w8, f"{d(-1)} 11:20:00", "Priya Shah", "Completed job; signed by Grace Lin")])
    db.execute("INSERT INTO notifications (at, recipient, subject, body, wo_id) VALUES (?,?,?,?,?)",
               (f"{d(-1)} 11:20:00", "ops@northgateclinic.example", "Job completed: WO-1008",
                "Priya Shah completed 'Replace failed capacitor and filters'. Signed by Grace Lin.", w8))
    w9 = wo("WO-1009", "Lumen Bakery — 12 Mill Street", "Oven hood fan belt", "Normal", "Invoiced", "tom.tech", -3, 10,
            hours=1, created=-5)
    db.execute("UPDATE work_orders SET labor_hours=1.0, signature_name='Sam Ortiz', signature_ok=1, completed_at=?"
               " WHERE id=?", (f"{d(-3)} 11:05:00", w9))
    db.execute("INSERT INTO wo_parts (wo_id, part_id, qty) VALUES (?,?,1)", (w9, part["BLT-A42"]))
    db.execute("INSERT INTO invoices (number, wo_id, labor_hours, labor_rate_cents, labor_cents, parts_cents,"
               " total_cents, status, issued_at, paid_at, payment_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               ("INV-5001", w9, 1.0, LABOR_RATE_CENTS, 9500, 1675, 11175, "Paid", f"{d(-3)} 16:00:00",
                f"{d(-1)} 10:00:00", "ACH-88120"))
    w10 = wo("WO-1010", "Harbor View — Building A", "Duplicate: lobby heat", "Normal", "Cancelled", created=-1)
    db.execute("UPDATE work_orders SET cancel_reason='Duplicate of WO-1002' WHERE id=?", (w10,))
    db.execute("INSERT INTO activity (wo_id, at, actor, message) VALUES (?,?,?,?)",
               (w10, now(), "Dana Reyes", "Cancelled: Duplicate of WO-1002"))


# ---------------------------------------------------------------- reads

def user_for_token(db, token):
    if not token:
        return None
    return db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token=?", (token,)).fetchone()


def login(db, username, password):
    user = db.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
    if not user or not secrets.compare_digest(hash_pw(password, user["salt"]), user["pw_hash"]):
        return None
    token = secrets.token_urlsafe(24)
    db.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)", (token, user["id"], now()))
    db.commit()
    return token


def logout(db, token):
    db.execute("DELETE FROM sessions WHERE token=?", (token,))
    db.commit()


WO_SELECT = """SELECT w.*, c.name AS customer, c.email AS customer_email, s.name AS site, s.address AS address,
  t.name AS technician, i.number AS invoice_number
  FROM work_orders w JOIN customers c ON c.id = w.customer_id JOIN sites s ON s.id = w.site_id
  LEFT JOIN users t ON t.id = w.technician_id LEFT JOIN invoices i ON i.wo_id = w.id"""


def work_orders(db, status=None, tech_id=None):
    sql, args = WO_SELECT + " WHERE 1=1", []
    if status:
        sql += " AND w.status=?"
        args.append(status)
    if tech_id:
        sql += " AND w.technician_id=?"
        args.append(tech_id)
    return db.execute(sql + " ORDER BY w.number DESC", args).fetchall()


def work_order(db, number):
    return db.execute(WO_SELECT + " WHERE w.number=?", (number,)).fetchone()


def technicians(db):
    return db.execute("SELECT * FROM users WHERE role='technician' ORDER BY name").fetchall()


def customers(db):
    return db.execute("""SELECT c.*, (SELECT COUNT(*) FROM sites WHERE customer_id=c.id) AS site_count,
        (SELECT COUNT(*) FROM work_orders WHERE customer_id=c.id AND status NOT IN ('Invoiced','Cancelled')) AS open_count
        FROM customers c ORDER BY name""").fetchall()


def sites(db, customer_id=None):
    sql = "SELECT s.*, c.name AS customer FROM sites s JOIN customers c ON c.id=s.customer_id"
    if customer_id:
        return db.execute(sql + " WHERE s.customer_id=? ORDER BY s.name", (customer_id,)).fetchall()
    return db.execute(sql + " ORDER BY c.name, s.name").fetchall()


def parts(db):
    return db.execute("SELECT * FROM parts ORDER BY name").fetchall()


def part_lines(db, wo_id):
    return db.execute("""SELECT wp.id, wp.qty, p.sku, p.name, p.unit_price_cents FROM wo_parts wp
        JOIN parts p ON p.id = wp.part_id WHERE wp.wo_id=? ORDER BY wp.id""", (wo_id,)).fetchall()


def checklist(db, wo_id):
    return db.execute("SELECT * FROM checklist WHERE wo_id=? ORDER BY position", (wo_id,)).fetchall()


def activity(db, wo_id):
    return db.execute("SELECT * FROM activity WHERE wo_id=? ORDER BY at DESC, id DESC", (wo_id,)).fetchall()


def notifications(db):
    return db.execute("""SELECT n.*, w.number FROM notifications n LEFT JOIN work_orders w ON w.id = n.wo_id
        ORDER BY n.at DESC, n.id DESC""").fetchall()


def invoices(db):
    return db.execute("""SELECT i.*, w.number AS wo_number, w.title, c.name AS customer FROM invoices i
        JOIN work_orders w ON w.id=i.wo_id JOIN customers c ON c.id=w.customer_id ORDER BY i.number DESC""").fetchall()


def invoice(db, number):
    return db.execute("""SELECT i.*, w.number AS wo_number, w.title, w.id AS wo_id, c.name AS customer,
        c.email AS customer_email, s.name AS site, s.address AS address, t.name AS technician
        FROM invoices i JOIN work_orders w ON w.id=i.wo_id JOIN customers c ON c.id=w.customer_id
        JOIN sites s ON s.id=w.site_id LEFT JOIN users t ON t.id=w.technician_id WHERE i.number=?""",
                      (number,)).fetchone()


def board(db, day):
    """Jobs on one day for each technician, with overlapping active jobs flagged as conflicts."""
    rows = db.execute(WO_SELECT + " WHERE w.sched_date=? AND w.status IN (%s) ORDER BY w.start_min"
                      % ",".join("?" * len(ON_BOARD)), (day, *ON_BOARD)).fetchall()
    columns = []
    for tech in technicians(db):
        jobs = [dict(r) for r in rows if r["technician_id"] == tech["id"]]
        for job in jobs:
            job["conflicts"] = [o["number"] for o in jobs if o is not job and conflicting(job, o)]
        columns.append({"tech": tech, "jobs": jobs})
    return columns


def conflicting(a, b):
    if a["status"] not in ACTIVE or b["status"] not in ACTIVE:
        return False
    return a["start_min"] < b["start_min"] + b["duration_min"] and b["start_min"] < a["start_min"] + a["duration_min"]


def unassigned(db):
    return db.execute(WO_SELECT + " WHERE w.status='New' ORDER BY CASE w.priority WHEN 'Urgent' THEN 0 WHEN 'High'"
                      " THEN 1 WHEN 'Normal' THEN 2 ELSE 3 END, w.sla_due").fetchall()


def dispatchable(db):
    return db.execute(WO_SELECT + " WHERE w.status IN ('New','Scheduled') ORDER BY w.number").fetchall()


# ---------------------------------------------------------------- writes

def log(db, wo_id, actor, message):
    db.execute("INSERT INTO activity (wo_id, at, actor, message) VALUES (?,?,?,?)", (wo_id, now(), actor, message))


def notify(db, wo, subject, body):
    db.execute("INSERT INTO notifications (at, recipient, subject, body, wo_id) VALUES (?,?,?,?,?)",
               (now(), wo["customer_email"], subject, body, wo["id"]))


def next_number(db, table, prefix, start):
    row = db.execute(f"SELECT MAX(CAST(SUBSTR(number, {len(prefix) + 1}) AS INTEGER)) FROM {table}").fetchone()
    return f"{prefix}{(row[0] or start - 1) + 1}"


def parse_day(value):
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None


def validate_work_order(db, form):
    errors = {}
    customer = db.execute("SELECT * FROM customers WHERE id=?", (form.get("customer_id") or 0,)).fetchone()
    if not customer:
        errors["customer_id"] = "Choose a customer."
    site = db.execute("SELECT * FROM sites WHERE id=?", (form.get("site_id") or 0,)).fetchone()
    if not site:
        errors["site_id"] = "Choose a site."
    elif customer and site["customer_id"] != customer["id"]:
        errors["site_id"] = f"The site must belong to {customer['name']}."
    title = form.get("title", "").strip()
    if not title:
        errors["title"] = "Enter a title."
    elif len(title) < 5:
        errors["title"] = "Title must be at least 5 characters."
    if form.get("priority") not in PRIORITIES:
        errors["priority"] = "Choose a priority."
    sla = form.get("sla_due", "").strip()
    if sla:
        day = parse_day(sla)
        if not day:
            errors["sla_due"] = "Enter the SLA due date as YYYY-MM-DD."
        elif day < today():
            errors["sla_due"] = "SLA due date cannot be in the past."
    if len(form.get("description", "")) > 1000:
        errors["description"] = "Description must be 1000 characters or fewer."
    return errors


def create_work_order(db, form, user):
    number = next_number(db, "work_orders", "WO-", 1001)
    priority = form["priority"]
    sla = form.get("sla_due", "").strip() or (today() + timedelta(days=SLA_DAYS[priority])).isoformat()
    wid = db.execute(
        "INSERT INTO work_orders (number, customer_id, site_id, title, description, priority, sla_due, status,"
        " created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (number, int(form["customer_id"]), int(form["site_id"]), form["title"].strip(),
         form.get("description", "").strip(), priority, sla, "New", user["id"], now())).lastrowid
    for i, label in enumerate(CHECKLIST):
        db.execute("INSERT INTO checklist (wo_id, position, label) VALUES (?,?,?)", (wid, i, label))
    log(db, wid, user["name"], f"Created work order ({priority} priority, SLA due {sla})")
    db.commit()
    return number


def assign(db, form, user):
    """Assign or reschedule. Returns (errors, work order number, conflicts)."""
    errors = {}
    wo = work_order(db, form.get("work_order", ""))
    if not wo:
        errors["work_order"] = "Choose a work order."
    elif wo["status"] not in OPEN_FOR_DISPATCH:
        errors["work_order"] = f"{wo['number']} is {wo['status']} and cannot be rescheduled."
    tech = db.execute("SELECT * FROM users WHERE id=? AND role='technician'", (form.get("technician_id") or 0,)).fetchone()
    if not tech:
        errors["technician_id"] = "Choose a technician."
    day = parse_day(form.get("day", ""))
    if not day:
        errors["day"] = "Choose a day."
    elif day < today():
        errors["day"] = "Choose today or a later day."
    try:
        start = int(form.get("start", ""))
        if not 6 * 60 <= start <= 18 * 60:
            raise ValueError
    except ValueError:
        errors["start"] = "Choose a start time."
    try:
        duration = int(form.get("duration", ""))
        if not 30 <= duration <= 8 * 60:
            raise ValueError
    except ValueError:
        errors["duration"] = "Choose a duration."
    if errors:
        return errors, None, []
    when = f"{day.isoformat()} at {start // 60:02d}:{start % 60:02d}"
    if wo["status"] == "New":
        message = f"Assigned to {tech['name']} on {when}"
    else:
        message = f"Rescheduled from {wo['technician']} on {wo['sched_date']} at {wo['start_min'] // 60:02d}:" \
                  f"{wo['start_min'] % 60:02d} to {tech['name']} on {when}"
    db.execute("UPDATE work_orders SET status='Scheduled', technician_id=?, sched_date=?, start_min=?, duration_min=?"
               " WHERE id=?", (tech["id"], day.isoformat(), start, duration, wo["id"]))
    log(db, wo["id"], user["name"], message)
    notify(db, wo, f"Visit scheduled: {wo['number']}",
           f"{tech['name']} will visit {wo['site']} on {when} for '{wo['title']}'.")
    columns = board(db, day.isoformat())
    job = next(j for c in columns for j in c["jobs"] if j["number"] == wo["number"])
    if job["conflicts"]:
        log(db, wo["id"], "FieldOps", f"Schedule conflict for {tech['name']} with {', '.join(job['conflicts'])}")
    db.commit()
    return {}, wo["number"], job["conflicts"]


def transition(db, wo, user, action):
    moves = {"travel": ("Scheduled", "En route", "Started travel"),
             "arrive": ("En route", "In progress", "Arrived on site")}
    before, after, message = moves[action]
    if wo["status"] != before:
        return f"{wo['number']} is {wo['status']}; it must be {before} first."
    db.execute("UPDATE work_orders SET status=? WHERE id=?", (after, wo["id"]))
    log(db, wo["id"], user["name"], message)
    if action == "travel":
        notify(db, wo, f"Technician on the way: {wo['number']}", f"{user['name']} is on the way to {wo['site']}.")
    db.commit()
    return None


def save_checklist(db, wo, user, done_ids):
    items = checklist(db, wo["id"])
    for item in items:
        db.execute("UPDATE checklist SET done=? WHERE id=?", (1 if str(item["id"]) in done_ids else 0, item["id"]))
    log(db, wo["id"], user["name"], f"Checklist saved: {sum(str(i['id']) in done_ids for i in items)} of "
                                     f"{len(items)} done")
    db.commit()


def add_part(db, wo, user, part_id, qty):
    errors = {}
    part = db.execute("SELECT * FROM parts WHERE id=?", (part_id or 0,)).fetchone()
    if not part:
        errors["part_id"] = "Choose a part."
    try:
        qty = int(qty)
        if not 1 <= qty <= 99:
            raise ValueError
    except ValueError:
        errors["qty"] = "Quantity must be a whole number from 1 to 99."
    if errors:
        return errors
    db.execute("INSERT INTO wo_parts (wo_id, part_id, qty) VALUES (?,?,?)", (wo["id"], part["id"], qty))
    log(db, wo["id"], user["name"], f"Added part {part['name']} × {qty}")
    db.commit()
    return {}


def remove_part(db, wo, user, line_id):
    line = db.execute("SELECT wp.*, p.name FROM wo_parts wp JOIN parts p ON p.id=wp.part_id WHERE wp.id=? AND wo_id=?",
                      (line_id, wo["id"])).fetchone()
    if line:
        db.execute("DELETE FROM wo_parts WHERE id=?", (line_id,))
        log(db, wo["id"], user["name"], f"Removed part {line['name']} × {line['qty']}")
        db.commit()


def save_notes(db, wo, user, notes):
    db.execute("UPDATE work_orders SET notes=? WHERE id=?", (notes.strip(), wo["id"]))
    log(db, wo["id"], user["name"], "Updated job notes")
    db.commit()


def complete(db, wo, user, form):
    errors = {}
    if wo["status"] != "In progress":
        errors["status"] = f"{wo['number']} is {wo['status']}; arrive on site before you complete the job."
    if any(not i["done"] for i in checklist(db, wo["id"])):
        errors["checklist"] = "Complete and save every checklist item first."
    try:
        hours = float(form.get("labor_hours", ""))
        if not 0 < hours <= 24:
            raise ValueError
    except ValueError:
        errors["labor_hours"] = "Enter labor hours between 0.25 and 24."
    name = form.get("signature_name", "").strip()
    if not name:
        errors["signature_name"] = "Enter the name of the customer who signs."
    if form.get("signature_ok") != "yes":
        errors["signature_ok"] = "The customer must confirm the work is complete."
    if errors:
        return errors
    db.execute("UPDATE work_orders SET status='Completed', labor_hours=?, signature_name=?, signature_ok=1,"
               " completed_at=? WHERE id=?", (hours, name, now(), wo["id"]))
    log(db, wo["id"], user["name"], f"Completed job; signed by {name}")
    notify(db, wo, f"Job completed: {wo['number']}",
           f"{user['name']} completed '{wo['title']}' at {wo['site']}. Signed by {name}.")
    db.commit()
    return {}


def cancel(db, wo, user, reason):
    reason = reason.strip()
    if wo["status"] not in CANCELLABLE:
        return f"{wo['number']} is {wo['status']} and cannot be cancelled."
    if not reason:
        return "Enter a reason for the cancellation."
    db.execute("UPDATE work_orders SET status='Cancelled', cancel_reason=? WHERE id=?", (reason, wo["id"]))
    log(db, wo["id"], user["name"], f"Cancelled: {reason}")
    notify(db, wo, f"Work order cancelled: {wo['number']}", f"'{wo['title']}' was cancelled. Reason: {reason}.")
    db.commit()
    return None


def create_invoice(db, wo, user):
    if wo["status"] != "Completed":
        return None, f"{wo['number']} is {wo['status']}; only completed jobs can be invoiced."
    lines = part_lines(db, wo["id"])
    labor_cents = round(wo["labor_hours"] * LABOR_RATE_CENTS)
    parts_cents = sum(line["unit_price_cents"] for line in lines)
    number = next_number(db, "invoices", "INV-", 5001)
    db.execute("INSERT INTO invoices (number, wo_id, labor_hours, labor_rate_cents, labor_cents, parts_cents,"
               " total_cents, status, issued_at) VALUES (?,?,?,?,?,?,?,?,?)",
               (number, wo["id"], wo["labor_hours"], LABOR_RATE_CENTS, labor_cents, parts_cents,
                labor_cents + parts_cents, "Unpaid", now()))
    db.execute("UPDATE work_orders SET status='Invoiced' WHERE id=?", (wo["id"],))
    log(db, wo["id"], user["name"], f"Created invoice {number}")
    notify(db, wo, f"Invoice {number} for {wo['number']}",
           f"Invoice {number} for '{wo['title']}' totals {money(labor_cents + parts_cents)}.")
    db.commit()
    return number, None


def mark_paid(db, inv, user, reference):
    reference = reference.strip()
    if inv["status"] == "Paid":
        return f"{inv['number']} is already paid."
    if not reference:
        return "Enter the payment reference."
    db.execute("UPDATE invoices SET status='Paid', paid_at=?, payment_ref=? WHERE id=?", (now(), reference, inv["id"]))
    log(db, inv["wo_id"], user["name"], f"Marked invoice {inv['number']} paid (reference {reference})")
    wo = db.execute(WO_SELECT + " WHERE w.id=?", (inv["wo_id"],)).fetchone()
    notify(db, wo, f"Payment received: {inv['number']}",
           f"We received {money(inv['total_cents'])} for invoice {inv['number']}. Reference {reference}.")
    db.commit()
    return None


def money(cents):
    return f"${cents / 100:,.2f}"
