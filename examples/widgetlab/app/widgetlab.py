#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""WidgetLab: a small practice app for Reverie's decision engines (Jev, Laya) and its escalation model.

It covers the decision types FieldOps does not: a multi-step wizard, native confirm and prompt dialogs,
content that loads late, a file download, tabs, and type-ahead suggestions. Standard library only; all
state lives in memory and resets when the server restarts or on POST /reset.

    widgetlab.py [--port 8766]
"""

import argparse
import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PLANS = {"starter": "Starter", "team": "Team", "studio": "Studio"}
COLORS = ["Amber", "Apricot", "Aqua", "Azure", "Beige", "Coral", "Crimson", "Indigo", "Ivory", "Lavender",
          "Lilac", "Lime", "Magenta", "Mint", "Olive", "Orchid", "Peach", "Plum", "Sage", "Teal"]


def fresh_state():
    return {"tasks": ["Water the ferns", "Sort the seed packets", "Oil the bicycle chain", "Label the jam jars"],
            "accounts": [], "settings": {"theme": "Light", "digest": False, "alerts": True}, "notice": ""}


STATE = fresh_state()

CSS = """body{font-family:system-ui,sans-serif;margin:0;color:#1d2433;background:#f6f7fb}
header{background:#24305e;color:#fff;padding:12px 24px;display:flex;gap:18px;align-items:center}
header a{color:#fff;text-decoration:none}header strong{margin-right:12px}
main{max-width:760px;margin:24px auto;background:#fff;padding:24px 32px;border-radius:10px;box-shadow:0 1px 4px #0002}
label{display:block;margin:12px 0 4px;font-weight:600}input,select{padding:6px 8px;font-size:15px}
button{padding:7px 14px;font-size:15px;margin:10px 8px 0 0;cursor:pointer}.notice{background:#e6f4ea;padding:8px 12px;
border-radius:6px}.error{color:#b3261e;margin:4px 0}.spinner{color:#555}li{margin:6px 0}
[role=tablist] button[aria-selected=true]{background:#24305e;color:#fff}.hidden{display:none}
#suggestions li{list-style:none;padding:4px 8px;border:1px solid #ccd;margin:0;cursor:pointer;background:#fff}"""


def page(title, body):
    nav = "".join(f'<a href="{href}">{name}</a>' for href, name in (
        ("/signup", "Sign up"), ("/tasks", "Tasks"), ("/reports", "Reports"), ("/settings", "Settings"),
        ("/search", "Color search")))
    notice = STATE.pop("notice", "") or ""
    STATE["notice"] = ""
    banner = f'<p class="notice" role="status">{html.escape(notice)}</p>' if notice else ""
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{html.escape(title)} · WidgetLab</title>"
            f"<style>{CSS}</style></head><body><header><strong><a href=\"/\">WidgetLab</a></strong>{nav}</header>"
            f"<main><h1>{html.escape(title)}</h1>{banner}{body}</main></body></html>")


def home():
    return page("Welcome", "<p>WidgetLab is a practice app with common web widgets. Pick an area above.</p><ul>"
                "<li><a href=\"/signup\">Sign up</a>: a three-step wizard</li>"
                "<li><a href=\"/tasks\">Tasks</a>: confirm and prompt dialogs</li>"
                "<li><a href=\"/reports\">Reports</a>: content that loads late, and a download</li>"
                "<li><a href=\"/settings\">Settings</a>: tabs, checkboxes, and a select</li>"
                "<li><a href=\"/search\">Color search</a>: type-ahead suggestions</li></ul>")


def signup(step, data, errors=()):
    hidden = "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in data.items()
                     if k != "step")
    errs = "".join(f'<p class="error">{html.escape(e)}</p>' for e in errors)
    if step == 1:
        body = (f'<p>Step 1 of 3: About you</p>{errs}<form method="post" action="/signup">'
                '<input type="hidden" name="step" value="1">'
                f'<label for="name">Full name</label><input id="name" name="name" value="{html.escape(data.get("name", ""))}">'
                f'<label for="email">Email</label><input id="email" name="email" value="{html.escape(data.get("email", ""))}">'
                '<br><button type="submit">Next</button></form>')
    elif step == 2:
        radios = "".join(
            f'<div><input type="radio" id="plan-{k}" name="plan" value="{k}"{" checked" if data.get("plan") == k else ""}>'
            f'<label for="plan-{k}" style="display:inline">{v}</label></div>' for k, v in PLANS.items())
        billing = "".join(f'<option{" selected" if data.get("billing") == b else ""}>{b}</option>'
                          for b in ("Monthly", "Yearly"))
        body = (f'<p>Step 2 of 3: Choose a plan</p>{errs}<form method="post" action="/signup">'
                f'<input type="hidden" name="step" value="2">{hidden}<fieldset><legend>Plan</legend>{radios}</fieldset>'
                f'<label for="billing">Billing</label><select id="billing" name="billing">{billing}</select><br>'
                '<button type="submit" name="go" value="back">Back</button>'
                '<button type="submit" name="go" value="next">Next</button></form>')
    else:
        body = (f'<p>Step 3 of 3: Review</p><dl><dt>Name</dt><dd>{html.escape(data["name"])}</dd><dt>Email</dt>'
                f'<dd>{html.escape(data["email"])}</dd><dt>Plan</dt><dd>{PLANS[data["plan"]]}, billed '
                f'{html.escape(data["billing"]).lower()}</dd></dl><form method="post" action="/signup">'
                f'<input type="hidden" name="step" value="3">{hidden}'
                '<button type="submit" name="go" value="back">Back</button>'
                '<button type="submit" name="go" value="create">Create account</button></form>')
    return page("Sign up", body)


def signup_post(form):
    data = {k: v[0].strip() for k, v in form.items()}
    step, go = int(data.get("step", "1")), data.pop("go", "next")
    if step == 1:
        errors = [e for e, bad in (("Enter your full name.", not data.get("name")),
                                   ("Enter an email address with an @.", "@" not in data.get("email", ""))) if bad]
        return signup(1 if errors else 2, data, errors)
    if step == 2:
        if go == "back":
            return signup(1, data)
        if data.get("plan") not in PLANS:
            return signup(2, data, ["Choose a plan."])
        return signup(3, data)
    if go == "back":
        return signup(2, data)
    ref = f"WL-{1001 + len(STATE['accounts'])}"
    STATE["accounts"].append({**data, "ref": ref})
    return page("Account created", f'<p role="status">Welcome, {html.escape(data["name"])}! Your {PLANS[data["plan"]]}'
                f' account is ready. Reference: <strong>{ref}</strong>.</p><p><a href="/signup">Sign up someone else</a></p>')


def tasks():
    rows = "".join(
        f'<li><span>{html.escape(t)}</span> '
        f'<button type="button" aria-label="Rename {html.escape(t)}" onclick="renameTask({i}, {html.escape(json.dumps(t))})">Rename</button>'
        f'<button type="button" aria-label="Delete {html.escape(t)}" onclick="deleteTask({i}, {html.escape(json.dumps(t))})">Delete</button></li>'
        for i, t in enumerate(STATE["tasks"]))
    script = """<form id="act" method="post" action="/tasks"><input type="hidden" name="op"><input type="hidden" name="i">
<input type="hidden" name="name"></form><script>
function send(op, i, name){const f=document.getElementById('act');f.op.value=op;f.i.value=i;f.name.value=name||'';f.submit();}
function deleteTask(i, t){ if (confirm("Delete the task '" + t + "'?")) send('delete', i); }
function renameTask(i, t){ const n = prompt("New name for '" + t + "'", t); if (n && n.trim()) send('rename', i, n.trim()); }
</script>"""
    return page("Tasks", f"<p>{len(STATE['tasks'])} tasks</p><ul>{rows}</ul>{script}")


def tasks_post(form):
    op, i = form.get("op", [""])[0], int(form.get("i", ["-1"])[0])
    if 0 <= i < len(STATE["tasks"]):
        old = STATE["tasks"][i]
        if op == "delete":
            STATE["tasks"].pop(i)
            STATE["notice"] = f"Deleted '{old}'."
        elif op == "rename" and form.get("name", [""])[0].strip():
            STATE["tasks"][i] = form["name"][0].strip()[:80]
            STATE["notice"] = f"Renamed '{old}' to '{STATE['tasks'][i]}'."


def reports():
    return page("Reports", """<p>Build the monthly garden report. It takes a few seconds.</p>
<button type="button" id="build" onclick="build()">Build report</button>
<p id="status" class="spinner" role="status"></p><div id="ready" class="hidden"><p>Report ready: 4 tasks, 12 plantings.</p>
<a id="download" href="/reports/garden-report.csv" download>Download CSV</a></div>
<script>function build(){document.getElementById('build').disabled=true;
document.getElementById('status').textContent='Building the report…';
setTimeout(()=>{document.getElementById('status').textContent='';
document.getElementById('ready').classList.remove('hidden');},3000);}</script>""")


def settings():
    s = STATE["settings"]
    themes = "".join(f'<option{" selected" if s["theme"] == t else ""}>{t}</option>' for t in ("Light", "Dark", "High contrast"))
    return page("Settings", f"""<div role="tablist" aria-label="Settings sections">
<button type="button" role="tab" id="tab-general" aria-selected="true" onclick="show('general')">General</button>
<button type="button" role="tab" id="tab-notifications" aria-selected="false" onclick="show('notifications')">Notifications</button></div>
<form method="post" action="/settings"><section id="panel-general" role="tabpanel" aria-labelledby="tab-general">
<label for="theme">Theme</label><select id="theme" name="theme">{themes}</select></section>
<section id="panel-notifications" role="tabpanel" aria-labelledby="tab-notifications" class="hidden">
<div><input type="checkbox" id="digest" name="digest"{" checked" if s["digest"] else ""}>
<label for="digest" style="display:inline">Weekly digest email</label></div>
<div><input type="checkbox" id="alerts" name="alerts"{" checked" if s["alerts"] else ""}>
<label for="alerts" style="display:inline">Frost alerts</label></div></section>
<button type="submit">Save settings</button></form>
<p>Current: theme {s["theme"]}; weekly digest {"on" if s["digest"] else "off"}; frost alerts {"on" if s["alerts"] else "off"}.</p>
<script>function show(name){{for (const n of ['general','notifications']){{
document.getElementById('panel-'+n).classList.toggle('hidden', n!==name);
document.getElementById('tab-'+n).setAttribute('aria-selected', String(n===name));}}}}</script>""")


def settings_post(form):
    theme = form.get("theme", ["Light"])[0]
    STATE["settings"] = {"theme": theme if theme in ("Light", "Dark", "High contrast") else "Light",
                         "digest": "digest" in form, "alerts": "alerts" in form}
    STATE["notice"] = "Settings saved."


def search(chosen=""):
    picked = f'<p role="status">Selected color: <strong>{html.escape(chosen)}</strong></p>' if chosen else ""
    return page("Color search", f"""{picked}<form method="get" action="/search" autocomplete="off">
<label for="color">Color</label><input id="color" name="color" role="combobox" aria-autocomplete="list"
aria-controls="suggestions" placeholder="Type two letters"><ul id="suggestions" role="listbox"></ul>
<button type="submit">Choose</button></form>
<script>const colors={json.dumps(COLORS)};const box=document.getElementById('suggestions');
const input=document.getElementById('color');
input.addEventListener('input',()=>{{box.innerHTML='';const q=input.value.trim().toLowerCase();if(q.length<2)return;
setTimeout(()=>{{for(const c of colors.filter(c=>c.toLowerCase().startsWith(q))){{const li=document.createElement('li');
li.setAttribute('role','option');li.textContent=c;li.onclick=()=>{{input.value=c;box.innerHTML='';}};box.appendChild(li);}}}},400);}});
</script>""")


class Handler(BaseHTTPRequestHandler):
    def send(self, body, status=200, kind="text/html; charset=utf-8", extra=()):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, where):
        self.send_response(303)
        self.send_header("Location", where)
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        routes = {"/": home, "/signup": lambda: signup(1, {}), "/tasks": tasks, "/reports": reports,
                  "/settings": settings}
        if url.path in routes:
            return self.send(routes[url.path]())
        if url.path == "/search":
            color = query.get("color", [""])[0].strip()
            return self.send(search(color if color in COLORS else ""))
        if url.path == "/reports/garden-report.csv":
            rows = "task,status\n" + "".join(f"{t},open\n" for t in STATE["tasks"])
            return self.send(rows, kind="text/csv; charset=utf-8",
                             extra=[("Content-Disposition", 'attachment; filename="garden-report.csv"')])
        if url.path == "/health":
            return self.send('{"status":"ok"}', kind="application/json")
        self.send(page("Not found", "<p>No such page.</p>"), 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
        path = urlparse(self.path).path
        if path == "/signup":
            return self.send(signup_post(form))
        if path == "/tasks":
            tasks_post(form)
            return self.redirect("/tasks")
        if path == "/settings":
            settings_post(form)
            return self.redirect("/settings")
        if path == "/reset":
            STATE.clear()
            STATE.update(fresh_state())
            return self.send('{"status":"reset"}', kind="application/json")
        self.send(page("Not found", "<p>No such page.</p>"), 404)

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8766")))
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"WidgetLab on http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
