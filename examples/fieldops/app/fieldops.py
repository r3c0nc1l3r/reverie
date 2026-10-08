#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""FieldOps: a small field-service management app for the Reverie examples.

Standard library only: http.server, sqlite3, and server-rendered HTML.

    fieldops.py serve [--port 8765]   start the app (seeds the database on first run)
    fieldops.py reset                 delete the database and seed it again
    fieldops.py query "SQL"           print the rows of one read-only query (for [admin] checkpoints)
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import date
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, str(Path(__file__).parent))

import store  # noqa: E402
import views  # noqa: E402

STATIC = Path(__file__).parent / "static"
ROUTES = []


def route(method, pattern, roles=None):
    def wrap(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), roles, fn))
        return fn
    return wrap


class Response(Exception):
    def __init__(self, status=200, body="", headers=None):
        self.status, self.body, self.headers = status, body, headers or {}


def redirect(location, flash=None):
    headers = {"Location": location}
    if flash:
        headers["Set-Cookie"] = f"flash={quote(flash)}; Path=/; HttpOnly; SameSite=Lax"
    return Response(303, "", headers)


class Handler(BaseHTTPRequestHandler):
    server_version = "FieldOps/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("FIELDOPS_QUIET") != "1":
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        url = urlparse(self.path)
        self.query = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.form, self.multi = {}, {}
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            raw = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
            self.form = {k: v[0] for k, v in raw.items()}
            self.multi = raw
        cookies = SimpleCookie(self.headers.get("Cookie") or "")
        self.token = cookies["session"].value if "session" in cookies else None
        self.flash = None
        extra = {}
        if "flash" in cookies and cookies["flash"].value:
            from urllib.parse import unquote
            self.flash = unquote(cookies["flash"].value)
            extra["Set-Cookie"] = "flash=; Path=/; Max-Age=0"
        self.db = store.connect()
        try:
            self.user = store.user_for_token(self.db, self.token)
            result = self.handle_route(method, url.path)
        except Response as r:
            result = r
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            result = Response(500, views.page("Error", f'<section class="card narrow"><h1>Something went wrong</h1>'
                                                        f'<p>{views.e(exc)}</p></section>', self.user))
        finally:
            self.db.close()
        if isinstance(result, str):
            result = Response(200, result)
        headers = dict(result.headers)
        if "Set-Cookie" in extra and "Set-Cookie" not in headers:
            headers["Set-Cookie"] = extra["Set-Cookie"]
        body = result.body.encode() if isinstance(result.body, str) else result.body
        self.send_response(result.status)
        headers.setdefault("Content-Type", "text/html; charset=utf-8")
        for k, v in headers.items():
            for value in (v if isinstance(v, list) else [v]):
                self.send_header(k, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_route(self, method, path):
        if path.startswith("/static/"):
            f = STATIC / path.removeprefix("/static/")
            if f.is_file() and f.parent == STATIC:
                ctype = "text/css" if f.suffix == ".css" else "application/octet-stream"
                return Response(200, f.read_bytes(), {"Content-Type": ctype})
            return Response(404, "not found", {"Content-Type": "text/plain"})
        for m, pattern, roles, fn in ROUTES:
            match = pattern.match(path)
            if m == method and match:
                if roles is not None:
                    if not self.user:
                        return redirect("/login")
                    if roles and self.user["role"] not in roles:
                        return Response(403, views.forbidden(self.user))
                return fn(self, *match.groups())
        return Response(404, views.not_found(self.user))

    # helpers
    def wo_or_404(self, number):
        wo = store.work_order(self.db, number)
        if not wo:
            raise Response(404, views.not_found(self.user))
        return wo


DESK = ("dispatcher", "manager")
TECH = ("technician",)
ANY = ()


# ---------------------------------------------------------------- sign-in

@route("GET", "/health")
def health(h):
    return Response(200, "ok", {"Content-Type": "text/plain"})


@route("GET", "/login")
def login_form(h):
    if h.user:
        return redirect("/")
    return views.login_page()


@route("POST", "/login")
def login(h):
    token = store.login(h.db, h.form.get("username", ""), h.form.get("password", ""))
    if not token:
        return Response(200, views.login_page("Username or password is incorrect.", h.form.get("username", "")))
    return Response(303, "", {"Location": "/", "Set-Cookie": f"session={token}; Path=/; HttpOnly; SameSite=Lax"})


@route("POST", "/logout")
def logout(h):
    if h.token:
        store.logout(h.db, h.token)
    return Response(303, "", {"Location": "/login", "Set-Cookie": "session=; Path=/; Max-Age=0"})


@route("GET", "/", ANY)
def home(h):
    return redirect({"technician": "/jobs", "dispatcher": "/dispatch", "manager": "/work-orders"}[h.user["role"]])


# ---------------------------------------------------------------- dispatch

def render_board(h, day, form=None, errors=None, flash=None, status=200):
    body = views.dispatch_page(h.user, day, store.board(h.db, day), store.unassigned(h.db), store.dispatchable(h.db),
                               store.technicians(h.db), form, errors, flash)
    return Response(status, body)


@route("GET", "/dispatch", DESK)
def dispatch_board(h):
    day = store.parse_day(h.query.get("date", "")) or store.today()
    form = {"work_order": h.query.get("wo", "")}
    wo = store.work_order(h.db, form["work_order"]) if form["work_order"] else None
    if wo and wo["technician_id"]:
        form.update(technician_id=wo["technician_id"], start=wo["start_min"], duration=wo["duration_min"],
                    day=wo["sched_date"])
    return render_board(h, day.isoformat(), form, flash=h.flash)


@route("POST", "/dispatch/assign", DESK)
def dispatch_assign(h):
    errors, number, conflicts = store.assign(h.db, h.form, h.user)
    board_day = h.form.get("board_day") or store.today().isoformat()
    if errors:
        return render_board(h, board_day, h.form, errors, status=422)
    msg = f"ok:Saved the assignment for {number}."
    if conflicts:
        msg = f"warn:Saved the assignment for {number}, but it conflicts with {', '.join(conflicts)}."
    return redirect(f"/dispatch?date={h.form['day']}", msg)


# ---------------------------------------------------------------- work orders

@route("GET", "/work-orders", DESK)
def list_work_orders(h):
    status = h.query.get("status") if h.query.get("status") in store.STATUSES else None
    return views.work_orders_page(h.user, store.work_orders(h.db, status), status, h.flash)


@route("GET", "/work-orders/new", DESK)
def new_work_order(h):
    return views.new_work_order_page(h.user, store.customers(h.db), store.sites(h.db))


@route("POST", "/work-orders/new", DESK)
def create_work_order(h):
    errors = store.validate_work_order(h.db, h.form)
    if errors:
        return Response(422, views.new_work_order_page(h.user, store.customers(h.db), store.sites(h.db), h.form, errors))
    number = store.create_work_order(h.db, h.form, h.user)
    return redirect(f"/work-orders/{number}", f"ok:Created work order {number}.")


def render_wo(h, wo, flash=None, cancel_error=None, status=200):
    return Response(status, views.work_order_page(h.user, wo, store.part_lines(h.db, wo["id"]),
                                                  store.checklist(h.db, wo["id"]), store.activity(h.db, wo["id"]),
                                                  flash, cancel_error))


@route("GET", r"/work-orders/(WO-\d+)", ANY)
def show_work_order(h, number):
    wo = h.wo_or_404(number)
    if h.user["role"] == "technician":
        return redirect(f"/jobs/{number}")
    return render_wo(h, wo, h.flash)


@route("POST", r"/work-orders/(WO-\d+)/cancel", DESK)
def cancel_work_order(h, number):
    wo = h.wo_or_404(number)
    error = store.cancel(h.db, wo, h.user, h.form.get("cancel_reason", ""))
    if error:
        return render_wo(h, wo, cancel_error=error, status=422)
    return redirect(f"/work-orders/{number}", f"ok:Cancelled {number}.")


@route("POST", r"/work-orders/(WO-\d+)/invoice", ("manager",))
def invoice_work_order(h, number):
    wo = h.wo_or_404(number)
    inv, error = store.create_invoice(h.db, wo, h.user)
    if error:
        return redirect(f"/work-orders/{number}", "error:" + error)
    return redirect(f"/invoices/{inv}", f"ok:Created invoice {inv} for {number}.")


# ---------------------------------------------------------------- technician jobs

@route("GET", "/jobs", TECH)
def my_jobs(h):
    rows = sorted(store.work_orders(h.db, tech_id=h.user["id"]), key=lambda r: (r["sched_date"] or "", r["start_min"] or 0))
    return views.jobs_page(h.user, rows, h.flash)


def own_job(h, number):
    wo = h.wo_or_404(number)
    if wo["technician_id"] != h.user["id"]:
        raise Response(403, views.forbidden(h.user))
    return wo


def render_job(h, wo, flash=None, errors=None, form=None, status=200):
    return Response(status, views.job_page(h.user, wo, store.part_lines(h.db, wo["id"]), store.checklist(h.db, wo["id"]),
                                           store.activity(h.db, wo["id"]), store.parts(h.db), flash, errors, form))


@route("GET", r"/jobs/(WO-\d+)", TECH)
def show_job(h, number):
    return render_job(h, own_job(h, number), h.flash)


@route("POST", r"/jobs/(WO-\d+)/(travel|arrive)", TECH)
def move_job(h, number, action):
    wo = own_job(h, number)
    error = store.transition(h.db, wo, h.user, action)
    if error:
        return redirect(f"/jobs/{number}", "error:" + error)
    return redirect(f"/jobs/{number}", "ok:" + ("Travel started." if action == "travel" else "Arrived on site."))


def require_working(h, wo):
    if wo["status"] != "In progress":
        raise redirect(f"/jobs/{wo['number']}", f"error:{wo['number']} is {wo['status']}; arrive on site first.")


@route("POST", r"/jobs/(WO-\d+)/checklist", TECH)
def job_checklist(h, number):
    wo = own_job(h, number)
    require_working(h, wo)
    store.save_checklist(h.db, wo, h.user, set(h.multi.get("done", [])))
    return redirect(f"/jobs/{number}", "ok:Checklist saved.")


@route("POST", r"/jobs/(WO-\d+)/parts", TECH)
def job_add_part(h, number):
    wo = own_job(h, number)
    require_working(h, wo)
    errors = store.add_part(h.db, wo, h.user, h.form.get("part_id"), h.form.get("qty", ""))
    if errors:
        return render_job(h, wo, errors=errors, form=h.form, status=422)
    return redirect(f"/jobs/{number}", "ok:Part added.")


@route("POST", r"/jobs/(WO-\d+)/parts/(\d+)/remove", TECH)
def job_remove_part(h, number, line_id):
    wo = own_job(h, number)
    require_working(h, wo)
    store.remove_part(h.db, wo, h.user, int(line_id))
    return redirect(f"/jobs/{number}", "ok:Part removed.")


@route("POST", r"/jobs/(WO-\d+)/notes", TECH)
def job_notes(h, number):
    wo = own_job(h, number)
    require_working(h, wo)
    store.save_notes(h.db, wo, h.user, h.form.get("notes", ""))
    return redirect(f"/jobs/{number}", "ok:Notes saved.")


@route("POST", r"/jobs/(WO-\d+)/complete", TECH)
def job_complete(h, number):
    wo = own_job(h, number)
    errors = store.complete(h.db, wo, h.user, h.form)
    if errors:
        return render_job(h, wo, errors=errors, form=h.form, status=422)
    return redirect(f"/jobs/{number}", f"ok:Job {number} completed.")


# ---------------------------------------------------------------- customers

@route("GET", "/customers", DESK)
def list_customers(h):
    return views.customers_page(h.user, store.customers(h.db), h.flash)


@route("POST", "/customers/new", DESK)
def add_customer(h):
    errors = {}
    name, email, phone = (h.form.get(k, "").strip() for k in ("name", "email", "phone"))
    if not name:
        errors["name"] = "Enter the customer name."
    elif h.db.execute("SELECT 1 FROM customers WHERE name=?", (name,)).fetchone():
        errors["name"] = "A customer with this name already exists."
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors["email"] = "Enter a billing email like name@example.com."
    if not phone:
        errors["phone"] = "Enter a phone number."
    if errors:
        return Response(422, views.customers_page(h.user, store.customers(h.db), None, errors, h.form))
    cid = h.db.execute("INSERT INTO customers (name, email, phone) VALUES (?,?,?)", (name, email, phone)).lastrowid
    h.db.commit()
    return redirect(f"/customers/{cid}", f"ok:Added customer {name}.")


def customer_or_404(h, cid):
    customer = h.db.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    if not customer:
        raise Response(404, views.not_found(h.user))
    return customer


def customer_orders(h, cid):
    return [w for w in store.work_orders(h.db) if w["customer_id"] == int(cid)]


@route("GET", r"/customers/(\d+)", DESK)
def show_customer(h, cid):
    customer = customer_or_404(h, cid)
    return views.customer_page(h.user, customer, store.sites(h.db, customer["id"]), customer_orders(h, cid), h.flash)


@route("POST", r"/customers/(\d+)/sites", DESK)
def add_site(h, cid):
    customer = customer_or_404(h, cid)
    errors = {}
    name, address = h.form.get("site_name", "").strip(), h.form.get("address", "").strip()
    if not name:
        errors["site_name"] = "Enter the site name."
    if not address:
        errors["address"] = "Enter the site address."
    if errors:
        return Response(422, views.customer_page(h.user, customer, store.sites(h.db, customer["id"]),
                                                 customer_orders(h, cid), None, errors, h.form))
    h.db.execute("INSERT INTO sites (customer_id, name, address) VALUES (?,?,?)", (customer["id"], name, address))
    h.db.commit()
    return redirect(f"/customers/{cid}", f"ok:Added site {name}.")


# ---------------------------------------------------------------- invoices and notifications

@route("GET", "/invoices", ("manager",))
def list_invoices(h):
    return views.invoices_page(h.user, store.invoices(h.db), h.flash)


def invoice_or_404(h, number):
    inv = store.invoice(h.db, number)
    if not inv:
        raise Response(404, views.not_found(h.user))
    return inv


@route("GET", r"/invoices/(INV-\d+)", ("manager",))
def show_invoice(h, number):
    inv = invoice_or_404(h, number)
    return views.invoice_page(h.user, inv, store.part_lines(h.db, inv["wo_id"]), h.flash)


@route("POST", r"/invoices/(INV-\d+)/paid", ("manager",))
def pay_invoice(h, number):
    inv = invoice_or_404(h, number)
    error = store.mark_paid(h.db, inv, h.user, h.form.get("payment_ref", ""))
    if error:
        return Response(422, views.invoice_page(h.user, inv, store.part_lines(h.db, inv["wo_id"]), None, error))
    return redirect(f"/invoices/{number}", f"ok:Marked {number} as paid.")


@route("GET", "/notifications", ANY)
def list_notifications(h):
    return views.notifications_page(h.user, store.notifications(h.db))


# ---------------------------------------------------------------- CLI

def main():
    parser = argparse.ArgumentParser(description="FieldOps demo app")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    sub.add_parser("reset")
    q = sub.add_parser("query")
    q.add_argument("sql")
    args = parser.parse_args()
    if args.cmd == "reset":
        store.reset()
        print(f"FieldOps database reset: {store.DB_PATH} (today is {date.today().isoformat()})")
    elif args.cmd == "query":
        store.ensure()
        db = sqlite3.connect(f"file:{store.DB_PATH}?mode=ro", uri=True)
        cur = db.execute(args.sql)
        print(" | ".join(c[0] for c in cur.description or []))
        for row in cur.fetchall():
            print(" | ".join("" if v is None else str(v) for v in row))
    else:
        store.ensure()
        server = ThreadingHTTPServer((args.host, args.port), Handler)
        print(f"FieldOps on http://{args.host}:{args.port}/login  (database {store.DB_PATH})", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
