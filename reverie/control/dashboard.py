"""Run dashboard: every test run from every session, live or finished, in one page.

Runs come from the session trails (.reverie/runs/<session>-<stamp>/trail.jsonl, plus the legacy
artifacts/agent-sessions when it exists): each `plan` event
starts a run, and its marks, actions, checks, checkpoints, and recaps follow it. Frames saved beside a trail
let a finished run be replayed step by step. Live sessions are found through their state files and add the
current frame, caption, pending proposal, and prompt.

  python -m reverie.control.dashboard [--root .reverie/runs] [--port 7788]
"""

import argparse
import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from .project import cache_dir, run_roots
from .server import load_environment, state_dir

FRAME = re.compile(r"^[\w.-]+\.jpg$")
TIMELINE = {"stalled", "finding", "back", "ui_flag", "ui_review", "pilot", "note", "act", "check", "checkpoint", "resolve", "dialog", "recap", "goal", "hint", "auto", "mark", "goto",
            "switch", "follow_tab", "open_tab", "close_tab", "say", "error"}


def dashboard_file():
    return state_dir() / "dashboard.json"


def live_sessions():
    sessions = {}
    for path in state_dir().glob("*.json"):
        if path.name == "dashboard.json":
            continue
        try:
            info = json.loads(path.read_text())
            os.kill(info["pid"], 0)
        except (OSError, ValueError, KeyError):
            continue
        sessions[Path(info["trail"]).name] = info
    return sessions


def clean_step(text):
    admin = text.lower().startswith("[admin]")
    text = re.sub(r"^\[admin\]\s*", "", text, flags=re.I)
    return (re.sub(r"`[^`]*`", "", text).strip() if admin else text.replace("`", "")), admin


def parse_trail(path):
    """Runs in one session trail, oldest first. Events before the first plan become that run's setup."""
    folder = path.parent
    session = folder.name.rsplit("-", 2)[0]
    runs, current, setup, by_step, pending_before = [], None, [], {}, {}
    closed = False
    for line in path.read_text(errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        event, t = record.get("event"), record.get("t", "")
        if event == "plan":
            steps = []
            for i, text in enumerate(record.get("steps") or []):
                title, admin = clean_step(text)
                steps.append({"n": i + 1, "title": title, "admin": admin, "status": "pending", "note": ""})
            source = record.get("source")
            current = {"id": f"{folder.name}~{len(runs)}", "dir": folder.name, "session": session,
                       "title": record.get("title") or "Test", "source": source,
                       "suite": Path(source).parent.name if source else "Ad hoc", "started": t, "ended": t,
                       "result": "running", "steps": steps, "events": [dict(e, phase="setup") for e in setup],
                       "layers": {}}
            setup = []
            runs.append(current)
            continue
        if event == "stop":
            closed = True
            continue
        if event in {"frame", "frame_before"}:
            if event == "frame_before":
                pending_before[record.get("step")] = record.get("file")
                continue
            item = by_step.get(record.get("step"))
            if item is not None:
                item["frame"] = record.get("file")
            continue
        if event not in TIMELINE:
            continue
        item = {("type_" if k == "type" else k): v for k, v in record.items() if k not in {"event", "trace"}}
        item["type"] = event
        if event == "act":
            item["by"] = "orchestrator" if item.get("by") in (None, "agent") else item["by"]
            by_step[record.get("step")] = item
            if record.get("step") in pending_before:
                item["before"] = pending_before.pop(record.get("step"))
            if current:
                current["layers"][item["by"]] = current["layers"].get(item["by"], 0) + 1
        if current is None:
            if event not in {"say"}:
                setup.append(item)
            continue
        current["events"].append(item)
        current["ended"] = t
        if event == "mark":
            n = record.get("step")
            if isinstance(n, int) and 1 <= n <= len(current["steps"]):
                current["steps"][n - 1].update(status=record.get("status"), note=record.get("note") or "")
                if record.get("ui"):
                    current["steps"][n - 1]["ui"] = record["ui"]
            current["result"] = record.get("result") or current["result"]
        if event == "finding":
            n = record.get("step")
            if isinstance(n, int) and 1 <= n <= len(current["steps"]):
                current["steps"][n - 1].setdefault("findings", []).append(
                    {k: record.get(k) for k in ("severity", "what", "expected", "actual", "workaround")})
            current.setdefault("findings", []).append({"step": n, "severity": record.get("severity"),
                                                       "what": record.get("what")})
    for run in runs:
        run["closed"] = closed or run is not runs[-1]
        attach_speech(run["events"])
    return runs


def attach_speech(events):
    """Give each spoken line to the frame it describes: the latest frame before it, else the next one."""
    last, pending = None, []
    for item in events:
        if item["type"] == "say" and item.get("text"):
            if last is not None:
                last.setdefault("speech", []).append(item["text"])
            else:
                pending.append(item["text"])
        elif item.get("frame"):
            last = item
            if pending:
                item.setdefault("speech", []).extend(pending)
                pending = []


def hidden_file(root):
    return Path(root) / "hidden-runs.json"


def hidden_ids(roots):
    ids = set()
    for root in roots:
        try:
            ids |= set(json.loads(hidden_file(root).read_text()))
        except (OSError, ValueError):
            pass
    return ids


def hide(root, run_ids):
    """Hide runs from the dashboard. Trails and frames stay on disk as evidence."""
    Path(root).mkdir(parents=True, exist_ok=True)
    path = hidden_file(root)
    try:
        current = set(json.loads(path.read_text()))
    except (OSError, ValueError):
        current = set()
    current |= set(run_ids)
    path.write_text(json.dumps(sorted(current), indent=1))
    return len(current)


def prune(roots):
    """Hide finished runs that are broken (incomplete, crashed) or failed. Live runs always stay."""
    live = live_sessions()
    doomed = []
    for run in all_runs(roots):
        is_live = run["dir"] in live and not run["closed"]
        result = "incomplete" if run["result"] == "running" and not is_live else run["result"]
        if not is_live and result in {"incomplete", "fail", "blocked"}:
            doomed.append(run["id"])
    for root in roots:
        hide(root, [d for d in doomed if (Path(root) / d.split("~")[0]).exists()])
    return doomed


def finished(run):
    """A run with a verdict and no pending or running step is final, even while its session stays open."""
    return run["result"] in {"pass", "fail", "blocked"} and all(
        st["status"] not in {"pending", "running"} for st in run["steps"])


def all_runs(roots, include_hidden=False):
    runs, seen = [], set()
    hidden = set() if include_hidden else hidden_ids(roots)
    for root in roots:
        for trail in sorted(Path(root).glob("*/trail.jsonl")):
            if trail.parent.resolve() in seen:
                continue
            seen.add(trail.parent.resolve())
            try:
                for run in parse_trail(trail):
                    if run["id"] in hidden:
                        continue
                    run["root"] = str(Path(root).resolve())
                    runs.append(run)
            except OSError:
                continue
    return runs


def index(roots):
    live = live_sessions()
    suites = {}
    for run in all_runs(roots):
        run["live"] = run["dir"] in live and not run["closed"] and not finished(run)
        if (run["suite"] == "fixtures" or run["title"].upper().startswith(("FIXTURE", "FX-"))) and not run["live"]:
            continue  # Finished fixture runs are tooling, not evidence; live ones show so you can watch them.
        if not run["live"] and run["result"] == "running":
            run["result"] = "incomplete"
        test = suites.setdefault(run["suite"], {}).setdefault(run["title"], {
            "title": run["title"], "source": run["source"], "runs": []})
        test["runs"].append({k: run[k] for k in ("id", "session", "started", "ended", "result", "live", "layers")}
                            | {"done": sum(1 for s in run["steps"] if s["status"] not in {"pending", "running"}),
                               "total": len(run["steps"])})
    out = []
    for suite, tests in suites.items():
        items = sorted(tests.values(), key=lambda t: (Path(t["source"] or "").name, t["title"]))
        for test in items:
            test["runs"].sort(key=lambda r: r["started"], reverse=True)
            # A test's result is its latest run's result; earlier runs stay browsable.
            test["result"] = test["runs"][0]["result"]
            test["live"] = any(r["live"] for r in test["runs"])
        out.append({"name": suite, "tests": items,
                    "latest": max(r["started"] for t in items for r in t["runs"])})
    out.sort(key=lambda s: s["latest"], reverse=True)
    return {"suites": out, "live": [{"session": i["name"], "dir": d} for d, i in live.items()]}


WHO = {"laya": "Laya", "mercury": "Mercury", "pilot": "Pilot", "orchestrator": "Claude", "jev": "Jev"}


def slides_for(run):
    """One slide per unique screen: a title, each action's target and result, checks, and step verdicts."""
    slides = [{"kind": "title", "run": run["id"], "dir": run["dir"], "title": run["title"], "result": run["result"],
               "session": run["session"], "started": run["started"], "layers": run["layers"],
               "steps": [{k: st[k] for k in ("n", "title", "status", "note")} for st in run["steps"]]}]
    step_now, said, seen = None, None, set()

    def add(slide, frame, speech=None):
        if not frame or frame in seen:
            return
        seen.add(frame)
        slides.append({**slide, "run": run["id"], "dir": run["dir"], "frame": frame, "step": step_now,
                       "said": said, "test": run["title"], "speech": speech or []})

    for e in run["events"]:
        t = e["type"]
        if t == "mark" and e.get("status") == "running":
            step_now = e.get("step")
            title = next((st["title"] for st in run["steps"] if st["n"] == step_now), "")
            slides.append({"kind": "step", "run": run["id"], "dir": run["dir"], "test": run["title"],
                           "step": step_now, "title": title})
        elif t in {"say", "recap"}:
            line = e.get("text") or e.get("summary") or ""
            if not line.startswith(("Check ", "Pausing", "Waiting for", "Paused", "Pilot paused")):
                said = line
        elif t == "act":
            who = WHO.get(e.get("by"), e.get("by"))
            text = f" “{e['text']}”" if e.get("text") else ""
            add({"kind": "target", "caption": f"{who} will {e.get('kind')} {e.get('label', '')}{text}",
                 "by": e.get("by")}, e.get("before"))
            add({"kind": "result", "caption": f"After {who}: {e.get('kind')} {e.get('label', '')}{text}",
                 "by": e.get("by")}, e.get("frame"), e.get("speech"))
        elif t in {"goto", "open_tab", "switch", "close_tab", "back"}:
            words = {"back": "Went back to", "goto": "Opened", "open_tab": "New tab", "switch": "Switched tab to", "close_tab": "Closed tab; now at"}
            add({"kind": "nav", "caption": f"{words[t]} {e.get('title') or e.get('url') or ''}"
                 + (" (signed out)" if e.get("isolated") else "")}, e.get("frame"), e.get("speech"))
        elif t == "check":
            add({"kind": "check", "passed": e.get("passed"),
                 "caption": ("Check passed: " if e.get("passed") else "Check FAILED: ")
                 + "; ".join(r["check"] for r in e.get("results", []))}, e.get("frame"), e.get("speech"))
        elif t == "finding":
            seen.discard(e.get("frame"))
            add({"kind": "ui", "severity": e.get("severity"),
                 "caption": f"FINDING ({e.get('severity')}): {e.get('what')}"
                 + (f" — workaround: {e['workaround']}" if e.get("workaround") else "")}, e.get("frame"))
        elif t == "ui_flag":
            seen.discard(e.get("frame"))
            add({"kind": "ui", "severity": "medium", "caption": f"Pilot noticed: {e.get('what')}"}, e.get("frame"))
        elif t == "ui_review":
            for issue in e.get("issues") or []:
                seen.discard(issue.get("frame"))  # Show a flagged frame again, with the finding.
                add({"kind": "ui", "severity": issue.get("severity"),
                     "caption": f"UI {issue.get('severity')}: {issue.get('what')}"}, issue.get("frame"))
        elif t == "mark" and e.get("status") in {"pass", "fail", "blocked", "skipped"}:
            slides.append({"kind": "verdict", "run": run["id"], "dir": run["dir"], "test": run["title"],
                           "step": e.get("step"), "status": e.get("status"), "note": e.get("note"),
                           "frame": e.get("frame"), "said": said, "speech": e.get("speech") or []})
    return slides


def walkthrough(run):
    """Markdown click-by-click instructions from a run: per plan step, the actions that worked and the proof."""
    from urllib.parse import urlparse

    lines, step, actions, proofs = [], None, [], []

    def flush():
        if step is None:
            return
        title = next((st["title"] for st in run["steps"] if st["n"] == step), "")
        status = next((st["status"] for st in run["steps"] if st["n"] == step), "")
        lines.append(f"### Step {step}: {title[:90]}" + ("" if status == "pass" else f"  _(last run: {status})_"))
        kept = []
        for line in actions:  # Drop loops: a line repeated back to back ran more than it needed.
            if not kept or kept[-1] != line:
                kept.append(line)
        lines.extend(f"{i}. {line}" for i, line in enumerate(kept, 1))
        if proofs:
            lines.append("   - Proof: " + "; ".join(dict.fromkeys(proofs)))
        lines.append("")

    for e in run["events"]:
        t = e["type"]
        if t == "mark" and e.get("status") == "running":
            flush()
            step, actions, proofs = e.get("step"), [], []
        elif step is None:
            continue
        elif t == "act" and e.get("kind") not in {"wait", "secret", "hover"}:
            label = (e.get("label") or "").split(" → ")
            path = urlparse(e.get("url") or "").path.rsplit("/", 1)[-1] or "/"
            if e.get("kind") == "fill":
                value = e.get("text") or ""
                what = f"Type '{value}' into **{label[0]}**" if value and value != "[redacted]" else \
                    f"Type the secret into **{label[0]}**"
            elif e.get("kind") == "select":
                what = f"In **{label[0]}**, choose **{label[-1]}**"
            else:
                what = f"Click **{label[0]}**"
            field = f" field `{e['hint']}`" if e.get("hint") else ""
            value = f" value `{e['value']}`" if e.get("value") not in (None, "") and e.get("kind") == "click" else ""
            actions.append(f"{what}  _(on {path}{',' if field or value else ''}{field}{value})_")
        elif t in {"goto", "open_tab", "switch", "close_tab", "back"}:
            where = e.get("url") or e.get("title") or ""
            actions.append({"back": "Press the browser Back button", "goto": f"Go to {where}", "open_tab": f"Open a {'signed-out ' if e.get('isolated') else ''}tab at {where}",
                            "switch": f"Switch to the tab {e.get('title') or where}", "close_tab": "Close this tab"}[t])
        elif t == "dialog" and e.get("message"):
            actions.append(f"A browser {e.get('type_', 'dialog')} asks \"{e['message'][:100]}\"; answer OK")
        elif t == "check" and e.get("passed"):
            proofs.extend(r["check"] for r in e.get("results", []))
    flush()
    return "\n".join(lines).strip() + "\n"


def deck(roots, run_id=None, suite=None):
    runs = all_runs(roots)
    if run_id:
        chosen = [r for r in runs if r["id"] == run_id]
    else:
        # A suite deck shows the latest run of each test, in the dashboard's test order.
        latest = {}
        for r in runs:
            if r["suite"] == suite and (r["title"] not in latest or r["started"] > latest[r["title"]]["started"]):
                latest[r["title"]] = r
        chosen = sorted(latest.values(), key=lambda r: (Path(r["source"] or "").name, r["title"]))
    slides = []
    for run in chosen:
        slides.extend(slides_for(run))
    return {"title": chosen[0]["title"] if run_id and chosen else suite, "slides": slides}


def session_call(info, command, args=None, timeout=10):
    response = httpx.post(f"http://127.0.0.1:{info['port']}/", json={"command": command, "args": args or {}},
                          headers={"X-Laya-Agent-Token": info["token"]}, timeout=timeout)
    return response.json()


def live_state(info):
    response = httpx.get(f"http://127.0.0.1:{info['port']}/watch/state", params={"token": info["token"]},
                         timeout=5)
    return response.json()


def run_detail(roots, run_id):
    folder, _, _ = run_id.partition("~")
    run = next((r for r in all_runs(roots) if r["id"] == run_id), None)
    if not run:
        return None
    live = live_sessions().get(folder)
    run["live"] = bool(live) and not run["closed"] and not finished(run)
    if not run["live"] and run["result"] == "running":
        run["result"] = "incomplete"
    if run["live"]:
        try:
            state = live_state(live)
            run["now"] = {k: state.get(k) for k in ("frame", "caption", "status", "url", "title", "pending", "goal",
                                                    "hints", "prompt", "checkpoints", "tabs", "goal_plan")}
        except (httpx.HTTPError, ValueError):
            run["now"] = None
    return run


def serve(args):
    roots = [Path(r).resolve() for r in args.root]
    path = dashboard_file()
    token = None
    if path.exists():  # Keep the same URL across restarts so an open tab keeps working.
        try:
            token = json.loads(path.read_text()).get("token")
        except ValueError:
            token = None
    token = token or secrets.token_urlsafe(18)
    page = Path(__file__).with_name("dashboard.html")
    bluetooth = "true" if os.environ.get("LAYA_AGENT_BLUETOOTH_AUDIO", "0").lower() in {"1", "true", "on", "yes"} \
        else "false"

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, mime="application/json"):
            body = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def roots(self):
            extra = {Path(i["trail"]).parent.resolve() for i in live_sessions().values()}
            return list(dict.fromkeys([*roots, *extra]))

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/":
                return self.send(200, page.read_text().replace("__BLUETOOTH__", bluetooth).encode(),
                                 "text/html; charset=utf-8")
            if url.path == "/api/index":
                return self.send(200, index(self.roots()))
            if url.path == "/replay":
                return self.send(200, Path(__file__).with_name("replay.html").read_text()
                                 .replace("__BLUETOOTH__", bluetooth).encode(), "text/html; charset=utf-8")
            if url.path == "/api/deck":
                return self.send(200, deck(self.roots(), query.get("run", [None])[0], query.get("suite", [None])[0]))
            if url.path == "/api/run":
                run = run_detail(self.roots(), query.get("id", [""])[0])
                return self.send(200, run) if run else self.send(404, {"error": "No such run"})
            if url.path == "/api/speech":
                text = query.get("text", [""])[0].strip()[:600]
                if not text:
                    return self.send(400, {"error": "No text"})
                import hashlib

                from .. import speech

                cache = cache_dir() / "speech"
                cache.mkdir(exist_ok=True)
                key = hashlib.sha1(f"{speech.provider()}|{speech.fixed_voice()}|{text}".encode()).hexdigest()
                hit = next(cache.glob(key + ".*"), None)
                if hit:
                    mime = "audio/wav" if hit.suffix == ".wav" else "audio/mpeg"
                    return self.send(200, hit.read_bytes(), mime)
                try:
                    audio, mime = speech.synthesize(text, None)
                except Exception as error:  # Narration is optional; the page keeps working without it.
                    return self.send(502, {"error": f"{type(error).__name__}: {error}"})
                (cache / f"{key}.{'wav' if 'wav' in mime else 'mp3'}").write_bytes(audio)
                return self.send(200, audio, mime)
            if url.path == "/api/frame":
                folder, name = query.get("dir", [""])[0], query.get("file", [""])[0]
                if "/" in folder or folder.startswith(".") or not FRAME.match(name):
                    return self.send(400, {"error": "Bad frame path"})
                for root in self.roots():
                    target = root / folder / "frames" / name
                    if target.is_file():
                        return self.send(200, target.read_bytes(), "image/jpeg")
                return self.send(404, {"error": "No such frame"})
            return self.send(404, {"error": "Not found"})

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            if urlparse(self.path).path != "/api/reply":
                return self.send(404, {"error": "Not found"})
            info = live_sessions().get(request.get("dir", ""))
            if not info:
                return self.send(404, {"error": "That session is not running"})
            return self.send(200, session_call(info, "reply", {"choice": request.get("choice", "Continue"),
                                                               "text": request.get("text", "")}))

        def log_message(self, *_args):
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:  # The preferred port is taken; any free loopback port works (the URL is in dashboard.json).
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    path.write_text(json.dumps({"pid": os.getpid(), "port": server.server_address[1], "token": token,
                                "roots": [str(r) for r in roots]}))
    path.chmod(0o600)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        threading.Event().wait()
    finally:
        server.shutdown()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="reverie-dashboard")
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--port", type=int, default=int(os.environ.get("LAYA_AGENT_UI_PORT", "7788")))
    args = parser.parse_args(argv)
    args.root = args.root or [str(r) for r in run_roots()]
    load_environment()  # Narration playback uses the same speech provider and voice as the sessions.
    serve(args)


if __name__ == "__main__":
    main()
