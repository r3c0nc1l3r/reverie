"""Run dashboard: every test run from every session, live or finished, in one page.

Runs come from the session trails (.reverie/runs/<session>-<stamp>/trail.jsonl, plus the legacy
artifacts/agent-sessions when it exists): each `plan` event
starts a run, and its marks, actions, checks, checkpoints, and recaps follow it. Frames saved beside a trail
let a finished run be replayed step by step. Live sessions are found through their state files and add the
current frame, caption, pending proposal, and prompt.

  python -m reverie.control.dashboard [--root .reverie/runs] [--port 7788]
"""

import argparse
import asyncio
import json
import os
import re
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from aiohttp import WSMsgType, web

from ..settings import setting
from .live import ViewerBuffer
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
            if item["by"] in LEGACY_LAYERS:  # runs from before the role names: laya/jev -> decision, mercury
                item.setdefault("decision_engine", item["by"] if item["by"] != "mercury" else None)
                item["by"] = LEGACY_LAYERS[item["by"]]
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


LEGACY_LAYERS = {"laya": "decision", "jev": "decision", "liquid": "decision", "mercury": "escalation"}
WHO = {"decision": "Decision engine", "escalation": "Escalation model", "pilot": "Pilot", "orchestrator": "Claude"}
ENGINES = {"jev": "Jev", "laya": "Laya", "liquid": "Liquid"}


def who_label(event):
    """'Decision engine · Jev', 'Escalation model', 'Pilot', ... for an act event (old or new names)."""
    label = WHO.get(event.get("by"), event.get("by"))
    engine = ENGINES.get(event.get("decision_engine"))
    return f"{label} · {engine}" if event.get("by") == "decision" and engine else label


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
            who = who_label(e)
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
    response = httpx.post(f"http://127.0.0.1:{info['port']}/", json={"command": command, "args": args or {},
                                                                              "operation_id": uuid.uuid4().hex},
                          headers={"X-Laya-Agent-Token": info["token"]}, timeout=timeout)
    return response.json()


def live_state(info):
    response = httpx.get(f"http://127.0.0.1:{info['port']}/watch/state", params={"token": info["token"]},
                         timeout=5)
    return response.json()


def run_detail(roots, run_id):
    folder, _, _ = run_id.partition("~")
    run = None
    for root in roots:
        base = Path(root).resolve()
        candidate = (base / folder).resolve()
        if candidate.parent != base or not (candidate / "trail.jsonl").is_file():
            continue
        run = next((r for r in parse_trail(candidate / "trail.jsonl") if r["id"] == run_id), None)
        if run:
            break
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


DASHBOARD_COOKIE = "reverie-dashboard"
LIVE_FIELDS = {
    "name", "session_id", "run_id", "revision", "status", "url", "title", "caption", "pending", "goal",
    "hints", "prompt", "checkpoints", "tabs", "goal_plan", "test", "layers", "observation", "controls",
    "narration", "frame", "frame_captured_at", "frame_id",
}


def _same_token(left, right):
    return bool(left and right) and secrets.compare_digest(str(left), str(right))


def _project_for_roots(roots):
    first = Path(roots[0]).resolve() if roots else Path.cwd().resolve()
    if first.name == "runs" and first.parent.name == ".reverie":
        return first.parent.parent
    return first


def _coordination_store(project_root):
    try:
        from .coordination import CoordinationStore

        return CoordinationStore(project_root)
    except (ImportError, OSError):
        return None


def _legacy_sessions(roots):
    sessions = []
    for number, root in enumerate(roots):
        if not any(Path(root).glob("*/trail.jsonl")):
            continue
        legacy = number > 0 or Path(root).parts[-2:] == ("artifacts", "agent-sessions")
        sessions.append({
            "id": "legacy-history" if legacy else "run-history",
            "title": "Legacy history" if legacy else "Run history",
            "status": "archived", "temporary": False, "archived": True, "legacy": True,
            "root": str(Path(root).resolve()), "revision": 0,
        })
    return sessions


def _store_sessions(store, roots, include_archived=True):
    sessions = list(store.list_sessions(include_archived=include_archived)) if store else []
    existing = {item.get("id") for item in sessions}
    sessions.extend(item for item in _legacy_sessions(roots) if item["id"] not in existing)
    return sessions


def _history_snapshot(roots, session_id):
    legacy = session_id == "legacy-history"
    selected = [root for number, root in enumerate(roots)
                if (number > 0 or Path(root).parts[-2:] == ("artifacts", "agent-sessions")) == legacy]
    runs = all_runs(selected or roots)
    return {
        "session": next((s for s in _legacy_sessions(roots) if s["id"] == session_id),
                        {"id": session_id, "title": "Run history", "legacy": True, "archived": True}),
        "runs": runs, "requests": [], "revision": 0, "cursor": 0,
    }


def _snapshot(store, roots, session_id):
    if session_id in {"run-history", "legacy-history"}:
        return _history_snapshot(roots, session_id)
    if not store:
        raise KeyError(session_id)
    snapshot = store.snapshot(session_id)
    recent = store.events(session_id, after=max(0, snapshot["cursor"] - 200), limit=200)
    snapshot["events"] = [e for e in recent["events"] if e["seq"] <= snapshot["cursor"]]
    return snapshot


def _event_delta(store, session_id, after, limit=200):
    if not store or session_id in {"run-history", "legacy-history"}:
        return {"events": [], "cursor": after, "revision": 0, "truncated": False}
    return store.events(session_id, after=after, limit=limit)


def _matching_live_sessions(session_id):
    matches = []
    for folder, info in live_sessions().items():
        if info.get("testing_session_id") == session_id:
            matches.append((folder, info))
    return matches


def _safe_live_state(session_id, folder, info):
    try:
        state = live_state(info)
    except (httpx.HTTPError, ValueError, OSError):
        return None
    if (state.get("session_id") or info.get("testing_session_id")) != session_id:
        return None
    run_id = state.get("run_id") or info.get("run_id")
    clean = {key: value for key, value in state.items() if key in LIVE_FIELDS}
    clean["session_id"], clean["run_id"] = session_id, run_id
    observation = clean.get("observation") or {}
    # A frame without a run-bound observation may be left over from an earlier test.  It is still
    # available through recorded replay, but must never be presented as the current live screen.
    if not run_id or not (observation.get("id") or observation.get("frame_id")):
        clean.pop("frame", None)
    return run_id or folder, clean


def _speech(text):
    import hashlib

    from .. import speech

    cache = cache_dir() / "speech"
    cache.mkdir(exist_ok=True)
    key = hashlib.sha1(f"{speech.provider()}|{speech.fixed_voice()}|{text}".encode()).hexdigest()
    hit = next(cache.glob(key + ".*"), None)
    if hit:
        return hit.read_bytes(), "audio/wav" if hit.suffix == ".wav" else "audio/mpeg"
    audio, mime = speech.synthesize(text, None)
    (cache / f"{key}.{'wav' if 'wav' in mime else 'mp3'}").write_bytes(audio)
    return audio, mime


def create_app(roots, token, project_root=None, poll_interval=0.25, viewer_event_limit=64):
    """Build the aiohttp dashboard application (also used by integration tests)."""
    roots = [Path(root).resolve() for root in roots]
    store = _coordination_store(project_root or _project_for_roots(roots))
    page = Path(__file__).with_name("dashboard.html")
    replay_page = Path(__file__).with_name("replay.html")
    bluetooth = "true" if setting("REVERIE_BLUETOOTH_AUDIO", "0").lower() in {"1", "true", "on", "yes"} \
        else "false"

    @web.middleware
    async def headers(request, handler):
        try:
            response = await handler(request)
        except ValueError as error:
            response = web.json_response({"error": str(error)}, status=409)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app = web.Application(middlewares=[headers], client_max_size=2 * 1024 * 1024)

    def auth_kind(request, allow_query=True):
        if _same_token(request.headers.get("X-Laya-Agent-Token"), token):
            return "header"
        if _same_token(request.cookies.get(DASHBOARD_COOKIE), token):
            return "cookie"
        if allow_query and request.method == "GET" and _same_token(request.query.get("token"), token):
            return "query"
        return None

    def require_auth(request, allow_query=True):
        kind = auth_kind(request, allow_query)
        if not kind:
            raise web.HTTPUnauthorized(text="Dashboard authentication required")
        return kind

    def require_origin(request, kind):
        origin = request.headers.get("Origin")
        if not origin:
            if kind == "header":
                return
            raise web.HTTPForbidden(text="Origin required")
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != request.host \
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise web.HTTPForbidden(text="Origin rejected")

    def current_roots():
        extra = {Path(info["trail"]).parent.resolve() for info in live_sessions().values()
                 if info.get("trail")}
        return list(dict.fromkeys([*roots, *extra]))

    async def home(request):
        if _same_token(request.query.get("token"), token):
            response = web.Response(status=303, headers={"Location": "/"})
            response.set_cookie(DASHBOARD_COOKIE, token, httponly=True, samesite="Strict", path="/")
            return response
        require_auth(request, allow_query=False)
        return web.Response(text=page.read_text().replace("__BLUETOOTH__", bluetooth),
                            content_type="text/html", charset="utf-8")

    async def replay(request):
        require_auth(request)
        return web.Response(text=replay_page.read_text().replace("__BLUETOOTH__", bluetooth),
                            content_type="text/html", charset="utf-8")

    async def api_sessions(request):
        require_auth(request)
        sessions = await asyncio.to_thread(_store_sessions, store, current_roots(), True)
        return web.json_response({"sessions": sessions})

    async def api_index(request):
        require_auth(request)
        active_roots = current_roots()
        payload, sessions = await asyncio.gather(
            asyncio.to_thread(index, active_roots),
            asyncio.to_thread(_store_sessions, store, active_roots, True),
        )
        payload["sessions"] = sessions
        return web.json_response(payload)

    async def api_session(request):
        require_auth(request)
        try:
            payload = await asyncio.to_thread(_snapshot, store, current_roots(), request.match_info["session_id"])
        except (KeyError, ValueError):
            raise web.HTTPNotFound(text="No such testing session")
        return web.json_response(payload, dumps=lambda value: json.dumps(value, default=str))

    async def api_runs(request):
        require_auth(request)
        payload = await asyncio.to_thread(store.snapshot, request.match_info["session_id"],
                                          int(request.query.get("offset", "0")),
                                          int(request.query.get("limit", "200")))
        return web.json_response(payload)

    async def api_deck(request):
        require_auth(request)
        payload = await asyncio.to_thread(deck, current_roots(), request.query.get("run"), request.query.get("suite"))
        return web.json_response(payload)

    async def api_run(request):
        require_auth(request)
        run = await asyncio.to_thread(run_detail, current_roots(), request.query.get("id", ""))
        if not run:
            raise web.HTTPNotFound(text=json.dumps({"error": "No such run"}), content_type="application/json")
        return web.json_response(run)

    async def api_frame(request):
        require_auth(request)
        folder, name = request.query.get("dir", ""), request.query.get("file", "")
        if "/" in folder or folder.startswith(".") or not FRAME.match(name):
            raise web.HTTPBadRequest(text=json.dumps({"error": "Bad frame path"}), content_type="application/json")
        for root in current_roots():
            target = root / folder / "frames" / name
            if target.is_file():
                return web.Response(body=await asyncio.to_thread(target.read_bytes), content_type="image/jpeg")
        raise web.HTTPNotFound(text=json.dumps({"error": "No such frame"}), content_type="application/json")

    async def api_speech(request):
        require_auth(request)
        text = request.query.get("text", "").strip()[:600]
        if not text:
            raise web.HTTPBadRequest(text=json.dumps({"error": "No text"}), content_type="application/json")
        try:
            audio, mime = await asyncio.to_thread(_speech, text)
        except Exception as error:  # Narration is optional; the dashboard remains usable.
            raise web.HTTPBadGateway(text=json.dumps({"error": f"{type(error).__name__}: {error}"}),
                                     content_type="application/json")
        return web.Response(body=audio, content_type=mime)

    async def api_reply(request):
        kind = require_auth(request, allow_query=False)
        require_origin(request, kind)
        body = await request.json()
        info = live_sessions().get(body.get("dir", ""))
        if not info:
            raise web.HTTPNotFound(text=json.dumps({"error": "That session is not running"}),
                                   content_type="application/json")
        payload = await asyncio.to_thread(session_call, info, "reply",
                                          {"choice": body.get("choice", "Continue"), "text": body.get("text", "")})
        return web.json_response(payload)

    async def api_action(request):
        kind = require_auth(request, allow_query=False)
        require_origin(request, kind)
        session_id = request.match_info["session_id"]
        body = await request.json()
        action, run_id = body.get("action"), body.get("run_id")
        runs = await asyncio.to_thread(store.list_runs, session_id, True) if store else []
        run = next((r for r in runs if r["id"] == run_id), None)
        if run_id and not run:
            raise web.HTTPNotFound(text="Attempt is not in this testing session")
        if action in {"pin", "unpin", "triage"}:
            if not run:
                raise web.HTTPBadRequest(text="Select an attempt")
            if action == "triage":
                result = await asyncio.to_thread(store.triage_run, run_id, body.get("status"),
                                                 note=body.get("note", ""))
            else:
                result = await asyncio.to_thread(store.pin_run, run_id, action == "pin")
        elif action == "audio_source":
            source = body.get("source_run_id")
            target = next((r for r in runs if r["id"] == source), None)
            if not target:
                raise web.HTTPNotFound(text="Narration source is not in this session")
            result = await asyncio.gather(*(asyncio.to_thread(session_call, info, "audio",
                          {"muted": info.get("name") != target.get("browser_session")})
                          for _, info in _matching_live_sessions(session_id)))
        elif action in {"claim", "resolve"}:
            request_id = body.get("request_id")
            requests = await asyncio.to_thread(store.list_requests, session_id)
            if not any(r["id"] == request_id for r in requests):
                raise web.HTTPNotFound(text="Request is not in this testing session")
            if action == "claim":
                result = await asyncio.to_thread(store.claim_request, request_id, body.get("owner", "human"))
            else:
                result = await asyncio.to_thread(store.resolve_request, request_id, body.get("result", {}),
                                                 owner=body.get("owner"))
        else:
            commands = {"pause": "pilot_pause", "resume": "pilot", "take_control": "take_control",
                        "release_control": "release_control", "audio": "audio", "inspect": "inspect"}
            command = commands.get(action)
            matches = _matching_live_sessions(session_id)
            if run:
                matches = [(folder, info) for folder, info in matches
                           if info.get("name") == run.get("browser_session")]
            if not command or not matches:
                raise web.HTTPNotFound(text=json.dumps({"error": "No matching live worker or action"}),
                                       content_type="application/json")
            arguments = {key: value for key, value in body.items()
                         if key not in {"action", "session_id", "run_id"}}
            result = await asyncio.to_thread(session_call, matches[0][1], command, arguments)
        return web.json_response(result or {"ok": True}, dumps=lambda value: json.dumps(value, default=str))

    async def websocket(request):
        kind = require_auth(request, allow_query=False)
        require_origin(request, kind)
        session_id = request.query.get("session", "")
        if not session_id:
            raise web.HTTPBadRequest(text="A testing session is required")
        try:
            after = max(0, int(request.query.get("after", "0")))
        except ValueError:
            raise web.HTTPBadRequest(text="Bad event cursor")

        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=64 * 1024)
        await ws.prepare(request)
        buffer = ViewerBuffer(event_limit=viewer_event_limit)
        cursor, last_live = after, {}
        delivery_revision = {}
        cursor_lock = asyncio.Lock()

        async def send_snapshot(reason):
            nonlocal cursor
            try:
                async with cursor_lock:
                    snapshot = await asyncio.to_thread(_snapshot, store, current_roots(), session_id)
                    revision = int(snapshot.get("revision") or 0)
                    cursor = int(snapshot["cursor"])
                    last_live.clear()  # Resend the latest frame after a slow-viewer resync.
                    await ws.send_json({"type": "snapshot", "session_id": session_id, "cursor": cursor,
                                        "revision": revision, "reason": reason, "data": snapshot})
            except (KeyError, ValueError):
                await ws.send_json({"type": "error", "error": "No such testing session"})

        async def sender():
            while not ws.closed:
                message = await buffer.get()
                if message is None:
                    return
                if message["type"] == "resync_required":
                    await send_snapshot(message["reason"])
                else:
                    await ws.send_json(message)

        async def producer():
            session_identity = tuple((s["id"], s.get("title"), s.get("state"))
                                     for s in await asyncio.to_thread(_store_sessions, store, current_roots()))
            nonlocal cursor
            ping_at = asyncio.get_running_loop().time() + 5
            while not ws.closed:
                async with cursor_lock:
                    delta = await asyncio.to_thread(_event_delta, store, session_id, cursor, 200)
                    if delta.get("truncated"):
                        await buffer.put_control({"type": "resync_required", "reason": "cursor_miss"})
                        cursor = int(delta.get("cursor") or cursor)
                    else:
                        for event in delta.get("events") or []:
                            seq = int(event.get("seq") or 0)
                            if seq <= cursor:
                                continue
                            cursor = seq
                            await buffer.put_event({"type": "event", "session_id": session_id, "cursor": cursor,
                                                    "revision": int(delta.get("revision") or 0), "event": event})
                        cursor = max(cursor, int(delta.get("cursor") or 0))

                sessions = await asyncio.to_thread(_store_sessions, store, current_roots())
                identity = tuple((s["id"], s.get("title"), s.get("state")) for s in sessions)
                if identity != session_identity:
                    session_identity = identity
                    await buffer.put_control({"type": "sessions", "sessions": sessions})
                matches = await asyncio.to_thread(_matching_live_sessions, session_id)
                states = await asyncio.gather(*(asyncio.to_thread(_safe_live_state, session_id, folder, info)
                                                for folder, info in matches))
                for item in states:
                    if not item:
                        continue
                    run_id, state = item
                    revision = int(state.get("revision") or 0)
                    observation = state.get("observation") or {}
                    identity = (revision, observation.get("id"), observation.get("frame_id"),
                                state.get("status"), state.get("caption"), state.get("frame_captured_at"),
                                json.dumps(state.get("narration"), sort_keys=True),
                                json.dumps(state.get("controls"), sort_keys=True))
                    if last_live.get(run_id) == identity:
                        continue
                    last_live[run_id] = identity
                    delivery_revision[run_id] = max(revision, delivery_revision.get(run_id, 0) + 1)
                    await buffer.put_live(run_id, {"type": "live", "session_id": session_id,
                                                   "run_id": run_id, "revision": delivery_revision[run_id],
                                                   "sent_at": time.time(), "state": state})
                now = asyncio.get_running_loop().time()
                if now >= ping_at:
                    await buffer.put_control({"type": "ping", "at": now})
                    ping_at = now + 5
                await asyncio.sleep(poll_interval)

        if after:
            delta = await asyncio.to_thread(_event_delta, store, session_id, after, 200)
            if delta.get("truncated") or after > int(delta.get("watermark", 0)):
                await send_snapshot("cursor_miss")
            else:
                events = [event for event in delta.get("events") or []
                          if int(event.get("seq") or 0) > after]
                cursor = max(after, int(delta.get("cursor") or 0))
                await ws.send_json({"type": "catchup", "session_id": session_id, "events": events,
                                    "cursor": cursor, "revision": int(delta.get("revision") or 0)})
        else:
            await send_snapshot("initial")

        send_task, produce_task = asyncio.create_task(sender()), asyncio.create_task(producer())
        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        incoming = json.loads(message.data)
                    except ValueError:
                        continue
                    if incoming.get("type") == "pong":
                        continue
                    if incoming.get("type") == "resync":
                        await buffer.put_control({"type": "resync_required", "reason": "client_request"})
                elif message.type in {WSMsgType.ERROR, WSMsgType.CLOSE}:
                    break
        finally:
            await buffer.close()
            for task in (send_task, produce_task):
                task.cancel()
            await asyncio.gather(send_task, produce_task, return_exceptions=True)
        return ws

    app.router.add_get("/", home)
    app.router.add_get("/replay", replay)
    app.router.add_get("/api/index", api_index)
    app.router.add_get("/api/sessions", api_sessions)
    app.router.add_get("/api/session/{session_id}", api_session)
    app.router.add_get("/api/session/{session_id}/runs", api_runs)
    app.router.add_get("/api/deck", api_deck)
    app.router.add_get("/api/run", api_run)
    app.router.add_get("/api/frame", api_frame)
    app.router.add_get("/api/speech", api_speech)
    app.router.add_post("/api/reply", api_reply)
    app.router.add_post("/api/session/{session_id}/action", api_action)
    app.router.add_get("/api/ws", websocket)
    return app


async def _serve(args):
    roots = [Path(root).resolve() for root in args.root]
    path = dashboard_file()
    token = None
    if path.exists():  # Keep the URL and browser cookie stable across restarts.
        try:
            token = json.loads(path.read_text()).get("token")
        except (OSError, ValueError):
            pass
    token = token or secrets.token_urlsafe(24)
    app = create_app(roots, token)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", args.port)
    try:
        await site.start()
    except OSError:  # Preferred port occupied; publish the selected free port in dashboard.json.
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
    port = site._server.sockets[0].getsockname()[1]
    path.write_text(json.dumps({"pid": os.getpid(), "port": port, "token": token,
                                "roots": [str(root) for root in roots]}))
    path.chmod(0o600)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def serve(args):
    asyncio.run(_serve(args))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="reverie-dashboard")
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--port", type=int, default=int(setting("REVERIE_UI_PORT", "7788")))
    args = parser.parse_args(argv)
    args.root = args.root or [str(r) for r in run_roots()]
    load_environment()  # Narration playback uses the same speech provider and voice as the sessions.
    try:
        serve(args)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
