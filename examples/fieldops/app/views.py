"""FieldOps HTML: server-rendered pages with plain forms, real labels, and stable ids."""

from datetime import date, timedelta
from html import escape

from store import CANCELLABLE, PRIORITIES, STATUSES, money, today


def e(value):
    return escape("" if value is None else str(value), quote=True)


def hhmm(minutes):
    return "" if minutes is None else f"{minutes // 60:02d}:{minutes % 60:02d}"


def nice_day(iso):
    if not iso:
        return ""
    d = date.fromisoformat(iso[:10])
    label = d.strftime("%a %d %b %Y")
    if d == today():
        return label + " (today)"
    if d == today() + timedelta(days=1):
        return label + " (tomorrow)"
    return label


def nice_time(stamp):
    return f"{nice_day(stamp[:10])} {stamp[11:16]}" if stamp else ""


def badge(status):
    return f'<span class="badge s-{e(status.lower().replace(" ", "-"))}">{e(status)}</span>'


def prio(priority):
    return f'<span class="prio p-{e(priority.lower())}">{e(priority)}</span>'


def sla(wo, prefix="SLA "):
    overdue = wo["sla_due"] < today().isoformat() and wo["status"] not in ("Completed", "Invoiced", "Cancelled")
    text = f"{prefix}{nice_day(wo['sla_due'])}"
    return f'<span class="sla overdue">{e(text)} — overdue</span>' if overdue else f'<span class="sla">{e(text)}</span>'


def options(items, selected, placeholder=None):
    out = [f'<option value="">{e(placeholder)}</option>'] if placeholder else []
    for value, label in items:
        sel = " selected" if str(value) == str(selected) else ""
        out.append(f'<option value="{e(value)}"{sel}>{e(label)}</option>')
    return "".join(out)


def field(fid, label, control, errors=None, hint=None):
    err = (errors or {}).get(fid)
    hint_html = f'<p class="hint" id="{fid}-hint">{e(hint)}</p>' if hint else ""
    err_html = f'<p class="error" id="{fid}-error">{e(err)}</p>' if err else ""
    return f'<div class="field{" has-error" if err else ""}"><label for="{fid}">{e(label)}</label>{hint_html}' \
           f'{control}{err_html}</div>'


def described(fid, errors=None, hint=None):
    ids = ([f"{fid}-hint"] if hint else []) + ([f"{fid}-error"] if (errors or {}).get(fid) else [])
    invalid = ' aria-invalid="true"' if (errors or {}).get(fid) else ""
    return (f' aria-describedby="{" ".join(ids)}"' if ids else "") + invalid


def error_summary(errors):
    if not errors:
        return ""
    items = "".join(f'<li><a href="#{e(k)}">{e(v)}</a></li>' for k, v in errors.items())
    n = len(errors)
    return f'<div class="error-summary" role="alert" id="error-summary"><h2>Fix {n} error{"s" if n > 1 else ""}' \
           f'</h2><ul>{items}</ul></div>'


NAV = {
    "dispatcher": [("/dispatch", "Dispatch board"), ("/work-orders", "Work orders"),
                   ("/work-orders/new", "New work order"), ("/customers", "Customers"),
                   ("/notifications", "Notifications")],
    "manager": [("/dispatch", "Dispatch board"), ("/work-orders", "Work orders"), ("/work-orders/new", "New work order"),
                ("/invoices", "Invoices"), ("/customers", "Customers"), ("/notifications", "Notifications")],
    "technician": [("/jobs", "My jobs"), ("/notifications", "Notifications")],
}


def page(title, body, user=None, flash=None, path=""):
    nav = ""
    if user:
        links = "".join(
            f'<a href="{href}"{" aria-current=page" if path == href or (href != "/work-orders" and path.startswith(href + "/")) else ""}>'
            f'{e(label)}</a>' for href, label in NAV[user["role"]])
        nav = f"""<nav aria-label="Main">{links}</nav>
<div class="who"><span>{e(user['name'])} <small>{e(user['role'].title())}</small></span>
<form method="post" action="/logout"><button type="submit" class="link" id="sign-out">Sign out</button></form></div>"""
    flash_html = ""
    if flash:
        kind, text = flash.split(":", 1) if ":" in flash else ("ok", flash)
        flash_html = f'<div class="flash {e(kind)}" role="status" id="flash">{e(text)}</div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · FieldOps</title><link rel="stylesheet" href="/static/app.css"></head>
<body><header class="top"><a class="brand" href="/">FieldOps</a>{nav}</header>
<main id="main">{flash_html}{body}</main></body></html>"""


# ---------------------------------------------------------------- sign-in

def login_page(error=None, username=""):
    err = f'<p class="error" role="alert" id="login-error">{e(error)}</p>' if error else ""
    body = f"""<section class="card narrow"><h1>Sign in</h1><p class="muted">FieldOps field-service demo.</p>{err}
<form method="post" action="/login" id="login-form">
{field("username", "Username", f'<input id="username" name="username" autocomplete="username" value="{e(username)}" required>')}
{field("password", "Password", '<input id="password" name="password" type="password" autocomplete="current-password" required>')}
<button type="submit" id="sign-in">Sign in</button></form></section>"""
    return page("Sign in", body)


def forbidden(user):
    return page("Not allowed", '<section class="card narrow"><h1>Not allowed</h1><p>Your role cannot open this page.'
                               '</p></section>', user)


def not_found(user):
    return page("Not found", '<section class="card narrow"><h1>Not found</h1><p>There is no such page or record.</p>'
                             '</section>', user)


# ---------------------------------------------------------------- dispatch board

def dispatch_page(user, day, columns, queue, open_orders, techs, form=None, errors=None, flash=None):
    form = form or {}
    days = [(today() + timedelta(days=n)).isoformat() for n in range(0, 7)]
    prev_day = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    next_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    conflicts = sum(len(j["conflicts"]) for c in columns for j in c["jobs"]) // 2

    def card(job, in_queue=False):
        flag = ""
        if not in_queue and job["conflicts"]:
            flag = f'<p class="conflict" role="note">Conflict with {e(", ".join(job["conflicts"]))}</p>'
        when = "" if in_queue else f'<p class="when">{hhmm(job["start_min"])}–{hhmm(job["start_min"] + job["duration_min"])}</p>'
        edit = f'<a class="small" href="/dispatch?date={e(day)}&amp;wo={e(job["number"])}#assign-form">' \
               f'{"Assign" if in_queue else "Reschedule"} {e(job["number"])}</a>' \
            if job["status"] in ("New", "Scheduled") else ""
        return f"""<li class="job{" has-conflict" if flag else ""}" id="card-{e(job['number'])}">{when}
<p class="job-head"><a href="/work-orders/{e(job['number'])}">{e(job['number'])}</a> {prio(job['priority'])} {badge(job['status'])}</p>
<p class="job-title">{e(job['title'])}</p><p class="muted">{e(job['site'])}</p>{sla(job) if in_queue else ""}{flag}{edit}</li>"""

    queue_html = "".join(card(j, True) for j in queue) or '<li class="empty">No unassigned work orders.</li>'
    cols = "".join(
        f"""<section class="column" aria-labelledby="col-{c['tech']['username']}">
<h3 id="col-{c['tech']['username']}">{e(c['tech']['name'])} <small>{len(c['jobs'])} job{"" if len(c["jobs"]) == 1 else "s"}</small></h3>
<ul class="jobs">{"".join(card(j) for j in c['jobs']) or '<li class="empty">No jobs this day.</li>'}</ul></section>"""
        for c in columns)
    banner = f'<div class="flash warn" role="alert" id="conflict-banner">{conflicts} schedule conflict' \
             f'{"s" if conflicts > 1 else ""} on this day. Reschedule one of the flagged jobs.</div>' if conflicts else ""
    selected_wo = form.get("work_order", "")
    wo_opts = options([(w["number"], f"{w['number']} — {w['title']} ({w['status']})") for w in open_orders],
                      selected_wo, "Choose a work order")
    tech_opts = options([(t["id"], t["name"]) for t in techs], form.get("technician_id", ""), "Choose a technician")
    day_opts = options([(d, nice_day(d)) for d in days], form.get("day", day if day in days else days[0]))
    start_opts = options([(m, hhmm(m)) for m in range(7 * 60, 17 * 60 + 1, 30)], form.get("start", ""), "Choose a time")
    dur_opts = options([(m, f"{m / 60:g} h") for m in (30, 60, 90, 120, 180, 240)], form.get("duration", "120"))
    errors = errors or {}
    body = f"""<div class="page-head"><h1>Dispatch board</h1>
<div class="day-nav"><a href="/dispatch?date={prev_day}" id="prev-day">Previous day</a>
<strong id="board-day">{e(nice_day(day))}</strong><a href="/dispatch?date={next_day}" id="next-day">Next day</a></div></div>
{banner}
<div class="board">
<section class="column queue" aria-labelledby="queue-h"><h3 id="queue-h">Unassigned <small>{len(queue)}</small></h3>
<ul class="jobs">{queue_html}</ul></section>
{cols}
</div>
<section class="card" id="assign-panel"><h2>Assign or reschedule</h2>{error_summary(errors)}
<form method="post" action="/dispatch/assign" id="assign-form" class="grid-form">
<input type="hidden" name="board_day" value="{e(day)}">
{field("work_order", "Work order", f'<select id="work_order" name="work_order"{described("work_order", errors)}>{wo_opts}</select>', errors)}
{field("technician_id", "Technician", f'<select id="technician_id" name="technician_id"{described("technician_id", errors)}>{tech_opts}</select>', errors)}
{field("day", "Day", f'<select id="day" name="day"{described("day", errors)}>{day_opts}</select>', errors)}
{field("start", "Start time", f'<select id="start" name="start"{described("start", errors)}>{start_opts}</select>', errors)}
{field("duration", "Duration", f'<select id="duration" name="duration"{described("duration", errors)}>{dur_opts}</select>', errors)}
<div class="actions"><button type="submit" id="save-assignment">Save assignment</button></div>
</form></section>"""
    return page("Dispatch board", body, user, flash, "/dispatch")


# ---------------------------------------------------------------- work orders

def work_orders_page(user, rows, status, flash=None):
    tabs = "".join(
        f'<a href="/work-orders{"?status=" + s if s else ""}"{" aria-current=true" if (status or "") == s else ""}>{e(s or "All")}</a>'
        for s in [""] + STATUSES)
    trs = "".join(f"""<tr><td><a href="/work-orders/{e(w['number'])}">{e(w['number'])}</a></td><td>{e(w['title'])}</td>
<td>{e(w['customer'])}</td><td>{prio(w['priority'])}</td><td>{badge(w['status'])}</td><td>{e(w['technician'] or '—')}</td>
<td>{e(nice_day(w['sched_date']) + ' ' + hhmm(w['start_min']) if w['sched_date'] else '—')}</td><td>{sla(w)}</td></tr>"""
                  for w in rows) or '<tr><td colspan="8" class="empty">No work orders.</td></tr>'
    body = f"""<div class="page-head"><h1>Work orders</h1><a class="button" href="/work-orders/new" id="new-work-order">New work order</a></div>
<nav class="tabs" aria-label="Filter by status">{tabs}</nav>
<table class="table" id="work-orders"><caption class="sr-only">Work orders</caption><thead><tr><th scope="col">Number</th><th scope="col">Title</th>
<th scope="col">Customer</th><th scope="col">Priority</th><th scope="col">Status</th><th scope="col">Technician</th>
<th scope="col">Scheduled</th><th scope="col">SLA</th></tr></thead><tbody>{trs}</tbody></table>"""
    return page("Work orders", body, user, flash, "/work-orders")


def new_work_order_page(user, customers, sites, form=None, errors=None):
    form = form or {"priority": "Normal"}
    errors = errors or {}
    cust_opts = options([(c["id"], c["name"]) for c in customers], form.get("customer_id", ""), "Choose a customer")
    site_opts = options([(s["id"], f"{s['name']} ({s['address']})") for s in sites], form.get("site_id", ""),
                        "Choose a site")
    prio_opts = options([(p, p) for p in PRIORITIES], form.get("priority", "Normal"))
    sla_hint = "Optional, YYYY-MM-DD. Leave blank to use the priority default: Urgent 1 day, High 2, Normal 5, Low 10."
    body = f"""<div class="page-head"><h1>New work order</h1></div>
<section class="card">{error_summary(errors)}
<form method="post" action="/work-orders/new" id="work-order-form" novalidate class="grid-form">
{field("customer_id", "Customer", f'<select id="customer_id" name="customer_id"{described("customer_id", errors)}>{cust_opts}</select>', errors)}
{field("site_id", "Site", f'<select id="site_id" name="site_id"{described("site_id", errors)}>{site_opts}</select>', errors)}
{field("title", "Title", f'<input id="title" name="title" value="{e(form.get("title", ""))}"{described("title", errors)}>', errors)}
{field("priority", "Priority", f'<select id="priority" name="priority"{described("priority", errors)}>{prio_opts}</select>', errors)}
{field("sla_due", "SLA due date", f'<input id="sla_due" name="sla_due" placeholder="YYYY-MM-DD" value="{e(form.get("sla_due", ""))}"{described("sla_due", errors, sla_hint)}>', errors, sla_hint)}
<div class="wide">{field("description", "Description", f'<textarea id="description" name="description" rows="4"{described("description", errors)}>{e(form.get("description", ""))}</textarea>', errors)}</div>
<div class="actions wide"><button type="submit" id="create-work-order">Create work order</button>
<a href="/work-orders">Back to work orders</a></div></form></section>"""
    return page("New work order", body, user, None, "/work-orders/new")


def parts_table(lines, editable=False, wo_number=None):
    rows = ""
    for line in lines:
        remove = ""
        if editable:
            remove = f'<td><form method="post" action="/jobs/{e(wo_number)}/parts/{line["id"]}/remove">' \
                     f'<button type="submit" class="link danger" aria-label="Remove {e(line["name"])}">Remove</button></form></td>'
        rows += f"""<tr><td>{e(line['sku'])}</td><td>{e(line['name'])}</td><td class="num">{line['qty']}</td>
<td class="num">{money(line['unit_price_cents'])}</td><td class="num">{money(line['qty'] * line['unit_price_cents'])}</td>{remove}</tr>"""
    if not rows:
        rows = f'<tr><td colspan="{6 if editable else 5}" class="empty">No parts used.</td></tr>'
    extra = '<th scope="col"><span class="sr-only">Actions</span></th>' if editable else ""
    return f"""<table class="table" id="parts-used"><caption class="sr-only">Parts used</caption><thead><tr><th scope="col">SKU</th>
<th scope="col">Part</th><th scope="col" class="num">Qty</th><th scope="col" class="num">Unit price</th>
<th scope="col" class="num">Line total</th>{extra}</tr></thead><tbody>{rows}</tbody></table>"""


def activity_list(items):
    lis = "".join(f'<li><time>{e(nice_time(a["at"]))}</time> <strong>{e(a["actor"])}</strong> {e(a["message"])}</li>'
                  for a in items)
    return f'<section class="card"><h2 id="activity-h">Activity</h2><ol class="activity" id="activity" aria-labelledby="activity-h">{lis}</ol></section>'


def summary(wo):
    sched = f"{nice_day(wo['sched_date'])}, {hhmm(wo['start_min'])}–{hhmm(wo['start_min'] + wo['duration_min'])}" \
        if wo["sched_date"] else "Not scheduled"
    return f"""<dl class="facts" id="summary">
<div><dt>Status</dt><dd id="wo-status">{badge(wo['status'])}</dd></div>
<div><dt>Priority</dt><dd>{prio(wo['priority'])}</dd></div>
<div><dt>Customer</dt><dd>{e(wo['customer'])}</dd></div>
<div><dt>Site</dt><dd>{e(wo['site'])}<br><span class="muted">{e(wo['address'])}</span></dd></div>
<div><dt>Technician</dt><dd id="wo-technician">{e(wo['technician'] or 'Unassigned')}</dd></div>
<div><dt>Scheduled</dt><dd id="wo-scheduled">{e(sched)}</dd></div>
<div><dt>SLA due</dt><dd id="wo-sla">{sla(wo, "")}</dd></div>
<div><dt>Invoice</dt><dd>{f'<a href="/invoices/{e(wo["invoice_number"])}">{e(wo["invoice_number"])}</a>' if wo['invoice_number'] else '—'}</dd></div>
</dl>"""


def work_order_page(user, wo, lines, items, activity, flash=None, cancel_error=None):
    actions = []
    if user["role"] in ("dispatcher", "manager") and wo["status"] in ("New", "Scheduled"):
        actions.append(f'<a class="button" href="/dispatch?date={e(wo["sched_date"] or today().isoformat())}&amp;'
                       f'wo={e(wo["number"])}#assign-form" id="open-dispatch">'
                       f'{"Assign" if wo["status"] == "New" else "Reschedule"} on dispatch board</a>')
    if user["role"] == "manager" and wo["status"] == "Completed":
        actions.append(f'<form method="post" action="/work-orders/{e(wo["number"])}/invoice">'
                       f'<button type="submit" id="create-invoice">Create invoice</button></form>')
    cancel = ""
    if user["role"] in ("dispatcher", "manager") and wo["status"] in CANCELLABLE:
        err = {"cancel_reason": cancel_error} if cancel_error else {}
        cancel = f"""<section class="card"><h2>Cancel work order</h2>
<form method="post" action="/work-orders/{e(wo['number'])}/cancel" id="cancel-form">
{field("cancel_reason", "Reason for cancellation", f'<input id="cancel_reason" name="cancel_reason"{described("cancel_reason", err)}>', err)}
<button type="submit" class="danger" id="cancel-work-order">Cancel work order</button></form></section>"""
    done = sum(i["done"] for i in items)
    completion = ""
    if wo["completed_at"]:
        completion = f"""<section class="card"><h2>Completion</h2><dl class="facts">
<div><dt>Completed</dt><dd>{e(nice_time(wo['completed_at']))}</dd></div>
<div><dt>Labor</dt><dd>{wo['labor_hours']:g} h</dd></div>
<div><dt>Signed by</dt><dd id="signed-by">{e(wo['signature_name'])}</dd></div>
<div><dt>Checklist</dt><dd>{done} of {len(items)} done</dd></div></dl>
{f'<p class="notes">{e(wo["notes"])}</p>' if wo['notes'] else ''}</section>"""
    reason = f'<p class="flash warn">Cancelled: {e(wo["cancel_reason"])}</p>' if wo["cancel_reason"] else ""
    body = f"""<div class="page-head"><div><p class="eyebrow">Work order</p><h1 id="wo-heading">{e(wo['number'])} — {e(wo['title'])}</h1></div>
<div class="actions">{"".join(actions)}</div></div>{reason}
<div class="split"><div>
<section class="card"><h2>Details</h2>{summary(wo)}
{f'<p class="description">{e(wo["description"])}</p>' if wo['description'] else ''}</section>
<section class="card"><h2>Parts used</h2>{parts_table(lines)}</section>{completion}{cancel}
</div><div>{activity_list(activity)}</div></div>"""
    return page(wo["number"], body, user, flash, "/work-orders/" + wo["number"])


# ---------------------------------------------------------------- technician

def jobs_page(user, rows, flash=None):
    def group(title, jobs, hid):
        lis = "".join(f"""<li class="job-row"><a href="/jobs/{e(j['number'])}" id="job-{e(j['number'])}">{e(j['number'])} — {e(j['title'])}</a>
{badge(j['status'])} {prio(j['priority'])}<p class="muted">{e(nice_day(j['sched_date']))} {hhmm(j['start_min'])} · {e(j['site'])}</p></li>"""
                      for j in jobs) or '<li class="empty">Nothing here.</li>'
        return f'<section class="card"><h2 id="{hid}">{e(title)}</h2><ul class="list" aria-labelledby="{hid}">{lis}</ul></section>'
    t = today().isoformat()
    active = [r for r in rows if r["status"] in ("Scheduled", "En route", "In progress")]
    body = f"""<div class="page-head"><h1>My jobs</h1></div>
{group("Today", [r for r in active if r["sched_date"] == t], "today-h")}
{group("Upcoming", [r for r in active if r["sched_date"] > t], "upcoming-h")}
{group("Recently completed", [r for r in rows if r["status"] in ("Completed", "Invoiced")][:5], "done-h")}"""
    return page("My jobs", body, user, flash, "/jobs")


def job_page(user, wo, lines, items, activity, parts, flash=None, errors=None, form=None):
    errors = errors or {}
    form = form or {}
    n = e(wo["number"])
    step = ""
    if wo["status"] == "Scheduled":
        step = f'<form method="post" action="/jobs/{n}/travel"><button type="submit" id="start-travel">Start travel</button></form>'
    elif wo["status"] == "En route":
        step = f'<form method="post" action="/jobs/{n}/arrive"><button type="submit" id="arrive">Arrive on site</button></form>'
    working = wo["status"] == "In progress"
    checks = "".join(
        f'<li><input type="checkbox" id="check-{i["id"]}" name="done" value="{i["id"]}"{" checked" if i["done"] else ""}'
        f'{"" if working else " disabled"}> <label for="check-{i["id"]}">{e(i["label"])}</label></li>' for i in items)
    done = sum(i["done"] for i in items)
    ck_err = f'<p class="error" id="checklist-error">{e(errors["checklist"])}</p>' if errors.get("checklist") else ""
    checklist_html = f"""<section class="card"><h2 id="checklist-h">Checklist <small>{done} of {len(items)} done</small></h2>
<form method="post" action="/jobs/{n}/checklist" id="checklist-form"><fieldset{"" if working else " disabled"}>
<legend class="sr-only">Checklist</legend><ul class="checks">{checks}</ul></fieldset>{ck_err}
{'<button type="submit" id="save-checklist">Save checklist</button>' if working else ''}</form></section>"""
    part_form = ""
    if working:
        popts = options([(p["id"], f"{p['name']} ({p['sku']}) — {money(p['unit_price_cents'])}") for p in parts],
                        form.get("part_id", ""), "Choose a part")
        part_form = f"""<form method="post" action="/jobs/{n}/parts" id="part-form" class="inline-form">
{field("part_id", "Part", f'<select id="part_id" name="part_id"{described("part_id", errors)}>{popts}</select>', errors)}
{field("qty", "Quantity", f'<input id="qty" name="qty" inputmode="numeric" size="4" value="{e(form.get("qty", "1"))}"{described("qty", errors)}>', errors)}
<button type="submit" id="add-part">Add part</button></form>"""
    notes = f"""<section class="card"><h2>Notes</h2><form method="post" action="/jobs/{n}/notes" id="notes-form">
{field("notes", "Job notes", f'<textarea id="notes" name="notes" rows="3"{"" if working else " disabled"}>{e(wo["notes"])}</textarea>')}
{'<button type="submit" id="save-notes">Save notes</button>' if working else ''}</form></section>"""
    finish = ""
    if working:
        finish = f"""<section class="card"><h2>Customer sign-off</h2>{error_summary({k: v for k, v in errors.items() if k in ("labor_hours", "signature_name", "signature_ok", "checklist", "status")})}
<form method="post" action="/jobs/{n}/complete" id="complete-form" class="grid-form" novalidate>
{field("labor_hours", "Labor hours", f'<input id="labor_hours" name="labor_hours" inputmode="decimal" value="{e(form.get("labor_hours", ""))}"{described("labor_hours", errors)}>', errors)}
{field("signature_name", "Customer name (signature)", f'<input id="signature_name" name="signature_name" value="{e(form.get("signature_name", ""))}"{described("signature_name", errors)}>', errors)}
<div class="wide field{" has-error" if errors.get("signature_ok") else ""}"><div class="check-line"><input type="checkbox" id="signature_ok" name="signature_ok" value="yes"{" checked" if form.get("signature_ok") == "yes" else ""}{described("signature_ok", errors)}>
<label for="signature_ok">The customer confirms the work is complete</label></div>
{f'<p class="error" id="signature_ok-error">{e(errors["signature_ok"])}</p>' if errors.get("signature_ok") else ""}</div>
<div class="actions wide"><button type="submit" id="complete-job">Complete job</button></div></form></section>"""
    elif wo["completed_at"]:
        finish = f'<section class="card"><h2>Customer sign-off</h2><p id="signed-by">Signed by {e(wo["signature_name"])} ' \
                 f'on {e(nice_time(wo["completed_at"]))}. Labor {wo["labor_hours"]:g} h.</p></section>'
    body = f"""<div class="page-head"><div><p class="eyebrow">Job</p><h1 id="wo-heading">{n} — {e(wo['title'])}</h1></div>
<div class="actions">{step}</div></div>
<div class="split"><div>
<section class="card"><h2>Visit</h2>{summary(wo)}{f'<p class="description">{e(wo["description"])}</p>' if wo['description'] else ''}</section>
{checklist_html}
<section class="card"><h2>Parts used</h2>{parts_table(lines, working, wo['number'])}{part_form}</section>
{notes}{finish}</div><div>{activity_list(activity)}</div></div>"""
    return page(wo["number"], body, user, flash, "/jobs/" + wo["number"])


# ---------------------------------------------------------------- customers

def customers_page(user, rows, flash=None, errors=None, form=None):
    errors, form = errors or {}, form or {}
    trs = "".join(f"""<tr><td><a href="/customers/{c['id']}">{e(c['name'])}</a></td><td>{e(c['email'])}</td><td>{e(c['phone'])}</td>
<td class="num">{c['site_count']}</td><td class="num">{c['open_count']}</td></tr>""" for c in rows)
    body = f"""<div class="page-head"><h1>Customers</h1></div>
<table class="table" id="customers"><caption class="sr-only">Customers</caption><thead><tr><th scope="col">Name</th><th scope="col">Email</th><th scope="col">Phone</th>
<th scope="col" class="num">Sites</th><th scope="col" class="num">Open work orders</th></tr></thead><tbody>{trs}</tbody></table>
<section class="card"><h2>Add customer</h2>{error_summary(errors)}<form method="post" action="/customers/new" id="customer-form" class="grid-form" novalidate>
{field("name", "Customer name", f'<input id="name" name="name" value="{e(form.get("name", ""))}"{described("name", errors)}>', errors)}
{field("email", "Billing email", f'<input id="email" name="email" type="email" value="{e(form.get("email", ""))}"{described("email", errors)}>', errors)}
{field("phone", "Phone", f'<input id="phone" name="phone" value="{e(form.get("phone", ""))}"{described("phone", errors)}>', errors)}
<div class="actions wide"><button type="submit" id="add-customer">Add customer</button></div></form></section>"""
    return page("Customers", body, user, flash, "/customers")


def customer_page(user, customer, sites, orders, flash=None, errors=None, form=None):
    errors, form = errors or {}, form or {}
    site_lis = "".join(f'<li><strong>{e(s["name"])}</strong><br><span class="muted">{e(s["address"])}</span></li>'
                       for s in sites) or '<li class="empty">No sites yet.</li>'
    trs = "".join(f"""<tr><td><a href="/work-orders/{e(w['number'])}">{e(w['number'])}</a></td><td>{e(w['title'])}</td>
<td>{e(w['site'])}</td><td>{badge(w['status'])}</td></tr>""" for w in orders) or '<tr><td colspan="4" class="empty">None.</td></tr>'
    body = f"""<div class="page-head"><div><p class="eyebrow">Customer</p><h1>{e(customer['name'])}</h1>
<p class="muted">{e(customer['email'])} · {e(customer['phone'])}</p></div></div>
<div class="split"><div><section class="card"><h2>Work orders</h2><table class="table"><thead><tr><th scope="col">Number</th>
<th scope="col">Title</th><th scope="col">Site</th><th scope="col">Status</th></tr></thead><tbody>{trs}</tbody></table></section></div>
<div><section class="card"><h2>Sites</h2><ul class="list" id="sites">{site_lis}</ul>
<h3>Add site</h3>{error_summary(errors)}<form method="post" action="/customers/{customer['id']}/sites" id="site-form" novalidate>
{field("site_name", "Site name", f'<input id="site_name" name="site_name" value="{e(form.get("site_name", ""))}"{described("site_name", errors)}>', errors)}
{field("address", "Address", f'<input id="address" name="address" value="{e(form.get("address", ""))}"{described("address", errors)}>', errors)}
<button type="submit" id="add-site">Add site</button></form></section></div></div>"""
    return page(customer["name"], body, user, flash, f"/customers/{customer['id']}")


# ---------------------------------------------------------------- invoices

def invoices_page(user, rows, flash=None):
    trs = "".join(f"""<tr><td><a href="/invoices/{e(i['number'])}">{e(i['number'])}</a></td><td><a href="/work-orders/{e(i['wo_number'])}">{e(i['wo_number'])}</a></td>
<td>{e(i['customer'])}</td><td>{e(nice_day(i['issued_at']))}</td><td class="num">{money(i['total_cents'])}</td><td>{badge(i['status'])}</td></tr>"""
                  for i in rows) or '<tr><td colspan="6" class="empty">No invoices yet.</td></tr>'
    body = f"""<div class="page-head"><h1>Invoices</h1></div><p class="muted">Create an invoice from a completed work order.</p>
<table class="table" id="invoices"><caption class="sr-only">Invoices</caption><thead><tr><th scope="col">Invoice</th><th scope="col">Work order</th>
<th scope="col">Customer</th><th scope="col">Issued</th><th scope="col" class="num">Total</th><th scope="col">Status</th></tr></thead><tbody>{trs}</tbody></table>"""
    return page("Invoices", body, user, flash, "/invoices")


def invoice_page(user, inv, lines, flash=None, error=None):
    rows = f"""<tr><td>Labor</td><td class="num">{inv['labor_hours']:g} h</td><td class="num">{money(inv['labor_rate_cents'])}/h</td>
<td class="num">{money(inv['labor_cents'])}</td></tr>"""
    rows += "".join(f"""<tr><td>{e(line['name'])} <span class="muted">{e(line['sku'])}</span></td><td class="num">{line['qty']}</td>
<td class="num">{money(line['unit_price_cents'])}</td><td class="num">{money(line['qty'] * line['unit_price_cents'])}</td></tr>"""
                    for line in lines)
    pay = ""
    if inv["status"] == "Unpaid" and user["role"] == "manager":
        err = {"payment_ref": error} if error else {}
        pay = f"""<section class="card"><h2>Record payment</h2><form method="post" action="/invoices/{e(inv['number'])}/paid" id="payment-form" class="inline-form" novalidate>
{field("payment_ref", "Payment reference", f'<input id="payment_ref" name="payment_ref"{described("payment_ref", err)}>', err)}
<button type="submit" id="mark-paid">Mark as paid</button></form></section>"""
    elif inv["status"] == "Paid":
        pay = f'<section class="card"><h2>Payment</h2><p id="payment-info">Paid on {e(nice_time(inv["paid_at"]))}, ' \
              f'reference {e(inv["payment_ref"])}.</p></section>'
    body = f"""<div class="page-head"><div><p class="eyebrow">Invoice</p><h1 id="invoice-heading">{e(inv['number'])}</h1></div>
<div id="invoice-status">{badge(inv['status'])}</div></div>
<section class="card invoice"><div class="bill"><div><h2>Bill to</h2><p><strong>{e(inv['customer'])}</strong><br>{e(inv['customer_email'])}</p></div>
<div><h2>Job</h2><p><a href="/work-orders/{e(inv['wo_number'])}">{e(inv['wo_number'])}</a> — {e(inv['title'])}<br>
<span class="muted">{e(inv['site'])}, {e(inv['address'])}. Technician {e(inv['technician'])}.</span></p></div>
<div><h2>Issued</h2><p>{e(nice_time(inv['issued_at']))}</p></div></div>
<table class="table" id="invoice-lines"><caption class="sr-only">Invoice lines</caption><thead><tr><th scope="col">Item</th><th scope="col" class="num">Qty</th>
<th scope="col" class="num">Rate</th><th scope="col" class="num">Amount</th></tr></thead><tbody>{rows}</tbody>
<tfoot><tr><th scope="row" colspan="3">Labor subtotal</th><td class="num" id="labor-subtotal">{money(inv['labor_cents'])}</td></tr>
<tr><th scope="row" colspan="3">Parts subtotal</th><td class="num" id="parts-subtotal">{money(inv['parts_cents'])}</td></tr>
<tr class="total"><th scope="row" colspan="3">Total due</th><td class="num" id="invoice-total">{money(inv['total_cents'])}</td></tr></tfoot></table>
</section>{pay}"""
    return page(inv["number"], body, user, flash, "/invoices/" + inv["number"])


# ---------------------------------------------------------------- notifications

def notifications_page(user, rows):
    items = "".join(f"""<li class="note" id="notification-{n['id']}"><div class="note-head"><strong>{e(n['subject'])}</strong>
<time>{e(nice_time(n['at']))}</time></div><p class="muted">To {e(n['recipient'])}{f' · <a href="/work-orders/{e(n["number"])}">{e(n["number"])}</a>' if n['number'] and user['role'] != 'technician' else ''}</p>
<p>{e(n['body'])}</p></li>""" for n in rows) or '<li class="empty">No notifications.</li>'
    body = f"""<div class="page-head"><h1>Notifications</h1></div>
<p class="muted">Messages FieldOps would send by email. The demo keeps them here instead of sending them.</p>
<ul class="inbox" id="notifications">{items}</ul>"""
    return page("Notifications", body, user, None, "/notifications")
