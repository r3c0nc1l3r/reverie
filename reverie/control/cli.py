"""reverie: run spec-driven browser tests one command at a time (also installed as laya-agent).

  reverie init                                       create .reverie/ (runs, specs) in this project
  reverie start --url https://example.com            open a browser session (narration on by default)
  reverie spec test.md && reverie pilot               the pilot runs a stored spec in the background
  reverie progress                                    plan steps, pilot state, open checkpoints
  reverie do "Open work order WO-1012"                the stack carries out one intent
  reverie observe [--grep TEXT]                       list the observed elements with their ids
  reverie act e7 [--text "hello"]                     click / type / select an observed element
  reverie stop
  reverie ui                                         review current and past runs from .reverie/runs"""

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

from .. import __version__
from ..settings import setting
from . import project
from .server import daemon_name, state_file

READ_ONLY_COMMANDS = {"status", "state", "changes", "events", "history", "tabs", "checkpoints", "wait"}
_CALL_CONTEXT = {"actor": "coordinator", "epoch": None, "observation_id": None,
                 "operation_id": None, "operation_id_used": False}


def parse_plan(text, section=None):
    """Title and numbered/bulleted steps from Markdown. With a section, read only under the heading that
    starts with it (e.g. `## DEMO-01 — Resend the order confirmation`) until the next heading of that level."""
    lines = text.splitlines()
    title = None
    if section:
        start = next((i for i, line in enumerate(lines)
                      if re.match(r"^#{1,6}\s", line) and line.lstrip("#").strip().startswith(section)), None)
        if start is None:
            raise SystemExit(f"reverie: no heading starting with {section!r}")
        level = len(lines[start]) - len(lines[start].lstrip("#"))
        title = lines[start].lstrip("#").strip()
        end = next((i for i in range(start + 1, len(lines))
                    if re.match(r"^#{1,%d}\s" % level, lines[i])), len(lines))
        lines = lines[start + 1:end]
    else:
        title = next((line.lstrip("#").strip() for line in lines if line.startswith("#")), None)
    steps = []
    for line in lines:
        match = re.match(r"^(?:\d+[.)]|[-*])\s+(?:\[[ xX]\]\s*)?(.+)$", line)
        if not match and steps and line.startswith((" ", "\t")) and line.strip():
            # An indented line or sub-bullet belongs to the step above it.
            steps[-1] += " " + re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip()
            continue
        if match:
            body = match.group(1)
            steps.append((body.replace("**", "") if body.lower().startswith("[admin]")
                          else re.sub(r"[`*]", "", body)).strip())
    return title, steps


def parse_spec(text):
    """A stored spec: YAML-ish front matter, a title, `## Steps`, and note sections."""
    meta = {}
    if text.startswith("---"):
        head, _, text = text[3:].partition("\n---")
        for line in head.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.split(" #")[0].strip()
    sections, current = {}, None
    title = None
    for line in text.splitlines():
        if line.startswith("# ") and title is None:
            title = line[2:].strip()
        elif line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
        elif current:
            sections[current].append(line)
    if "steps" not in sections:
        raise SystemExit("reverie: a spec needs a '## Steps' section")
    _, steps = parse_plan("\n".join(sections["steps"]))
    notes = [f"{name.title()}: " + " ".join(line.strip() for line in sections[name] if line.strip())
             for name in ("goal", "fixtures", "evidence", "guidance", "walkthrough") if name in sections
             and any(line.strip() for line in sections[name])]
    return title or meta.get("id") or "Test", steps, notes, meta


def run_checkpoint(name, args):
    """The session never runs shell commands; the orchestrator's own terminal does, after review."""
    checkpoint = next((c for c in call(name, "checkpoints")["checkpoints"] if c["id"] == args.id), None)
    if not checkpoint:
        print(f"refused: unknown checkpoint {args.id}", file=sys.stderr)
        raise SystemExit(2)
    if checkpoint["status"] != "pending" or not checkpoint.get("command"):
        print("refused: checkpoint is not pending or carries no command; handle it and use `resolve`",
              file=sys.stderr)
        raise SystemExit(2)
    print(f"checkpoint {checkpoint['id']} ({checkpoint['source']}): {checkpoint['title']}")
    print(f"command: {checkpoint['command']}")
    if not args.yes:
        if not sys.stdin.isatty() or input("Run it? [y/N] ").strip().lower() != "y":
            print("refused: not confirmed", file=sys.stderr)
            raise SystemExit(2)
    try:
        done = subprocess.run(checkpoint["command"], shell=True, capture_output=True, text=True,
                              timeout=args.timeout)
        code, output = done.returncode, (done.stdout + done.stderr)
    except subprocess.TimeoutExpired as error:
        code, output = 124, f"timed out after {args.timeout}s\n{error.stdout or ''}"
    print(output[-3000:])
    return call(name, "resolve", {"id": checkpoint["id"], "status": "done" if code == 0 else "failed",
                                  "exit_code": code, "output": output, "note": f"exit {code}"})


def load(name):
    path = state_file(name)
    if not path.exists():
        return None
    info = json.loads(path.read_text())
    try:
        os.kill(info["pid"], 0)
    except OSError:
        path.unlink(missing_ok=True)
        return None
    return info


def call(name, command, args=None, timeout=120, *, actor=None, epoch=None, observation_id=None, operation_id=None):
    info = load(name)
    if not info:
        print(f"reverie: no session named {name!r}. Run `reverie start --url ...`.", file=sys.stderr)
        raise SystemExit(4)
    try:
        context = _CALL_CONTEXT
        actor = actor or context.get("actor") or "coordinator"
        epoch = context.get("epoch") if epoch is None else epoch
        observation_id = context.get("observation_id") if observation_id is None else observation_id
        if command not in READ_ONLY_COMMANDS:
            if operation_id is None and context.get("operation_id") and not context.get("operation_id_used"):
                operation_id = context["operation_id"]
                context["operation_id_used"] = True
            operation_id = operation_id or uuid.uuid4().hex
        request = {"command": command, "args": args or {}, "actor": actor}
        for key, value in (("epoch", epoch), ("observation_id", observation_id),
                           ("operation_id", operation_id)):
            if value is not None:
                request[key] = value
        response = httpx.post(
            f"http://127.0.0.1:{info['port']}/",
            json=request,
            headers={"X-Laya-Agent-Token": info["token"]},
            timeout=timeout,
        )
    except httpx.HTTPError as error:
        print(f"reverie: session {name!r} did not answer: {error}", file=sys.stderr)
        raise SystemExit(3)
    payload = response.json()
    if response.status_code == 409:
        print(f"refused: {payload['error']}", file=sys.stderr)
        raise SystemExit(2)
    if response.status_code != 200:
        print(f"error: {payload.get('error')}", file=sys.stderr)
        raise SystemExit(3)
    return payload


def start(args):
    if load(args.session):
        print(f"reverie: session {args.session!r} is already running", file=sys.stderr)
        raise SystemExit(2)
    command = [sys.executable, "-m", "reverie.control.server", "--name", args.session, "--url", args.url,
               "--voice", args.voice, "--project-root", str(project.project_root()),
               "--padding-ms", str(args.padding_ms)]
    for flag in ("goal", "engine", "trail_dir", "profile", "download_dir"):
        if getattr(args, flag):
            command += [f"--{flag.replace('_', '-')}", getattr(args, flag)]
    if args.headless:
        command.append("--headless")
    if args.testing_session:
        command += ["--testing-session", args.testing_session]
    if args.follow_along:
        command.append("--follow-along")
    log = state_file(args.session).with_suffix(".log")
    env = {**os.environ, "BU_NAME": daemon_name(args.session)}
    if getattr(args, "bluetooth", False):
        env["REVERIE_BLUETOOTH_AUDIO"] = "1"
    with open(log, "ab") as sink:
        process = subprocess.Popen(command, stdout=sink, stderr=sink, stdin=subprocess.DEVNULL,
                                   start_new_session=True, env=env)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if info := load(args.session):
            return {**info, "token": "(hidden)", **call(args.session, "status")}
        if process.poll() is not None:
            tail = log.read_text()[-800:]
            print(f"reverie: session failed to start.\n{tail}", file=sys.stderr)
            raise SystemExit(3)
        time.sleep(0.3)
    print("reverie: session did not become ready within 60 seconds", file=sys.stderr)
    raise SystemExit(3)


def run_roots(extra=None):
    """Run folders to read: the given --root dirs, else .reverie/runs plus legacy artifacts/agent-sessions."""
    return [os.path.abspath(r) for r in extra] if extra else [str(r) for r in project.run_roots()]


def active_session_file():
    return project.reverie_dir() / "active-session.json"


def activate_session(session_id):
    """Select the testing session inherited by subsequently started workers."""
    path = active_session_file()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"session_id": session_id}, indent=1) + "\n")
    temporary.replace(path)
    return path


def dashboard(open_browser=True, roots=None):
    """Start the run dashboard once (shared by every session) and return its URL."""
    from .dashboard import dashboard_file

    roots = roots or run_roots()
    path = dashboard_file()
    info = None
    if path.exists():
        try:
            info = json.loads(path.read_text())
            os.kill(info["pid"], 0)
            httpx.get(f"http://127.0.0.1:{info['port']}/api/index", params={"token": info["token"]}, timeout=3)
            if [str(r) for r in info.get("roots", [])] != [str(os.path.realpath(r)) for r in roots]:
                os.kill(info["pid"], 15)  # Another project's dashboard: restart it on this project's runs.
                time.sleep(0.3)
                info = None
        except (OSError, ValueError, KeyError, httpx.HTTPError):
            info = None
    if not info:
        before = path.stat().st_mtime if path.exists() else 0
        log = path.with_suffix(".log")
        command = [sys.executable, "-m", "reverie.control.dashboard"]
        for root in roots:
            command += ["--root", str(root)]
        with open(log, "ab") as sink:
            subprocess.Popen(command, stdout=sink, stderr=sink, cwd=str(project.project_root()),
                             stdin=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if path.exists() and path.stat().st_mtime != before:
                info = json.loads(path.read_text())
                break
            time.sleep(0.2)
        if not info:
            print(f"reverie: the dashboard did not start; see {log}", file=sys.stderr)
            raise SystemExit(3)
    url = f"http://127.0.0.1:{info['port']}/"
    if open_browser:
        bootstrap = f"{url}?token={info['token']}"
        subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", bootstrap],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"url": f"{url}?token={info['token']}"}


def format_event(e):
    """One line per event, agent-browser style: a stable ref, then what happened."""
    return " ".join(_format_event(e).split())


def _format_event(e):
    kind, head = e.get("event"), f"#{e.get('seq'):<4} {e.get('t', '')[11:19]}"
    if kind == "act":
        text = f" “{e['text']}”" if e.get("text") else ""
        return f"{head} {e.get('by', 'orchestrator'):<12} {e.get('kind')} {e.get('label', '')}{text}"
    if kind == "pilot":
        what = e.get("intent") or e.get("text") or e.get("url") or e.get("need") or e.get("lesson") or \
            (f"{e.get('status')}: {e.get('note', '')}" if e.get("op") == "mark" else "")
        return f"{head} PILOT[{e.get('step')}] {e.get('op')}: {str(what)[:140]}"
    if kind == "pilot_outcome":
        return f"{head}   -> {str(e.get('outcome'))[:160]}"
    if kind == "finding":
        return f"{head} FINDING[{e.get('step')}] {e.get('severity')}: {e.get('what')}" + (
            f" (workaround: {e['workaround']})" if e.get("workaround") else "")
    if kind == "ui_flag":
        return f"{head} UI FLAG[{e.get('step')}]: {e.get('what')}"
    if kind == "ui_review":
        issues = e.get("issues") or []
        return f"{head} UI REVIEW[{e.get('step')}]: " + ("; ".join(f"{i['severity']}: {i['what']}" for i in issues)
                                                        or f"no problems. {e.get('summary', '')}")
    if kind == "check":
        return f"{head} check {'PASS' if e.get('passed') else 'FAIL'}: " + "; ".join(r["check"] for r in e.get("results", []))
    if kind == "mark":
        return f"{head} STEP {e.get('step')} {str(e.get('status')).upper()} {str(e.get('note') or '')[:140]}"
    if kind == "checkpoint":
        return f"{head} CHECKPOINT {e.get('id')} ({e.get('source')}): {e.get('title')}"
    if kind == "resolve":
        return f"{head} resolved {e.get('id')} {e.get('status')}: {str(e.get('note') or '')[:120]}"
    if kind in {"say", "recap"}:
        return f"{head} said: {e.get('text') or e.get('summary')}"
    if kind == "auto":
        return f"{head}   stack paused: {e.get('reason')} {e.get('layers')}"
    if kind in {"goal", "hint", "note"}:
        return f"{head} {kind}: {str(e.get('goal') or e.get('hint') or e.get('text'))[:150]}"
    if kind in {"goto", "open_tab", "switch", "close_tab", "follow_tab", "back"}:
        return f"{head} {kind} {e.get('url') or e.get('target') or ''}"
    if kind in {"pilot_end", "error", "dialog"}:
        return f"{head} {kind}: {e.get('paused') or e.get('error') or e.get('message')}"
    return f"{head} {kind}"


def show(payload, as_json):
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return
    items = payload.pop("items", None)
    text = payload.pop("text", None) if "items" in payload or items is not None else None
    for key in ("status", "url", "title", "goal", "passed", "choice", "path", "decision", "detail", "stopped",
                "reloaded", "download_dir"):
        if payload.get(key) not in (None, ""):
            print(f"{key}: {payload[key]}")
    if payload.get("recap"):
        print(f"recap: {payload['recap']}")
    if payload.get("needs"):
        print(f"needs: {payload['needs']}")
    for session in payload.get("sessions", []):
        print(f"{session['id']:<32} {session.get('state', 'active'):<10} {session.get('title', '')}")
    for run in payload.get("runs", []):
        print(f"{run['id']:<40} {run.get('result', run.get('status', '')):<10} "
              f"{run.get('title', run.get('test_id', ''))}")
    for request in payload.get("requests", []):
        print(f"{request['id']:<32} {request.get('status', ''):<10} {request.get('need', '')}")
    for cp in ([payload["checkpoint"]] if payload.get("checkpoint") else []) + payload.get("checkpoints", []):
        result = cp.get("result") or {}
        extra = f"  exit={result.get('exit_code')}" if result else ""
        print(f"checkpoint {cp['id']} [{cp['status']}] ({cp['source']}) {cp['title']}{extra}")
        if cp.get("command"):
            print(f"  command: {cp['command']}")
    if payload.get("layers"):
        print(f"layers: {payload['layers']}")
    if payload.get("paused"):
        print(f"paused: {payload['paused']}")
    for entry in payload.get("pilot_log", []):
        what = entry.get("intent") or entry.get("text") or entry.get("url") or entry.get("need") or entry.get("status")
        print(f"  pilot[{entry['step']}] {entry['op']}: {str(what)[:110]}  -> {str(entry['outcome'])[:140]}")
    proposal = payload.get("proposal")
    if proposal:
        typed = f" text={proposal['text']!r}" if proposal.get("text") else ""
        print(f"proposal: @{proposal['ref']}  {proposal['label']}{typed}  "
              f"conf={proposal['confidence']:.2f}  layer={proposal.get('layer', proposal['engine'])} "
              f"{proposal['latency_ms']}ms")
        if proposal.get("escalation"):
            engine = (proposal.get("decision_engine") or "decision engine").title()
            confidence = proposal.get("decision_confidence", proposal.get("laya_confidence"))
            print(f"  escalated: {proposal['escalation']} ({engine} {confidence})")
        if proposal.get("reason"):
            print(f"  reason: {proposal['reason']}")
    if payload.get("rejected") is not None or payload.get("hints"):
        print(f"hints: {payload.get('hints')}")
    if payload.get("plan"):
        print(f"plan: {json.dumps(payload['plan'], default=str)[:600]}")
    test = payload.get("test")
    if test:
        print(f"test: {test['title']}  [{test['result']}]")
        for step in test["steps"]:
            note = f"  — {step['note']}" if step["note"] else ""
            print(f"  {step['n']:>2}. [{step['status']:<7}] {step['title'][:90]}{note}")
    for result in payload.get("results", []):
        print(f"  [{'PASS' if result['pass'] else 'FAIL'}] {result['check']}")
    if "choice" in payload and payload.get("text"):
        print(f"reply: {payload['text']}")
    if payload.get("prompt"):
        print(f"waiting: {payload['prompt']['question']}")
    for tab in payload.get("tabs", []):
        print(f"{'*' if tab['current'] else ' '} {tab['id']}  {tab['title'][:50]}  {tab['url']}")
    for step in payload.get("history", []):
        print(f"{step['step']:>3} {step.get('by', '')} {step['kind']} {step.get('label', '')} {step.get('text') or ''}")
    for step in payload.get("steps", []) if isinstance(payload.get("steps"), list) else []:
        print(f"  - {step}")
    if items is not None:
        for item in items:
            extra = " ".join(f"{k}={item[k]!r}" for k in ("value", "hint", "checked", "expanded") if k in item)
            label = item.get("label", "")[:70]
            print(f"{item['id']:>12}  {item['kind']:<6} {item.get('role', ''):<10} {label}  {extra}")
        print(f"({len(items)} shown)")
    if text:
        print("--- page text ---")
        print(text)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="reverie", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"reverie {__version__}")
    parser.add_argument("--session", default=setting("REVERIE_SESSION", "default"))
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    parser.add_argument("--actor", default="coordinator", help="Coordination owner issuing this command")
    parser.add_argument("--epoch", type=int, help="Expected worker control epoch")
    parser.add_argument("--observation-id", help="Expected visual observation id")
    parser.add_argument("--operation-id", help="Stable id for safely retrying one mutating command")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("start", help="Open a headed, narrated session")
    p.add_argument("--url", required=True)
    p.add_argument("--voice", default="auto", choices=["auto", "kitten", "kokoro", "fish", "espeak", "spd", "off"])
    p.add_argument("--goal", help="Goal for autonomous step/run")
    p.add_argument("--engine", choices=["laya", "jev", "liquid"],
                   help="Decision engine: jev (hosted, default; needs OPENROUTER_API_KEY), liquid (hosted), or laya (local laya.cpp or MLX). Default: $REVERIE_DECISION_ENGINE, else jev")
    p.add_argument("--trail-dir")
    p.add_argument("--profile", help="Chromium profile dir (default: per-session, isolated)")
    p.add_argument("--download-dir", help="Save browser downloads here (default: $REVERIE_DOWNLOAD_DIR, "
                   "else downloads/ in the run folder; never ~/Downloads)")
    p.add_argument("--headless", action="store_true", help="No window; the watch page streams frames instead")
    p.add_argument("--ui", action="store_true", help="Open the run dashboard in your default browser")
    p.add_argument("--bluetooth", action="store_true",
                   help="Bluetooth audio mode: wake sleeping headphones before each spoken line")
    p.add_argument("--testing-session", help="Attach this worker to an existing testing session")
    p.add_argument("--follow-along", action="store_true", help="Wait for narration at action boundaries")
    p.add_argument("--padding-ms", type=int, default=350,
                   help="Follow-along pause after narration completes (default: 350)")

    sub.add_parser("status")
    p = sub.add_parser("goal", help="Set the current sub-goal for the fast model")
    p.add_argument("goal")
    p = sub.add_parser("do", help="Default driver: the stack carries out one intent, pausing when it needs you")
    p.add_argument("intent", help="What to accomplish on the page; quote any value to type, e.g. rate 2 '300'")
    p.add_argument("--hint", action="append", default=[], help="Steering for the escalation model (field names, which button)")
    p.add_argument("--max", type=int, default=6, dest="max_steps")
    p.add_argument("--until-text")
    p.add_argument("--until-url")
    p = sub.add_parser("pilot", help="Start the pilot on the loaded plan in the background (pilot stop to halt)")
    p.add_argument("action", nargs="?", choices=["start", "stop"], default="start")
    p.add_argument("--foreground", action="store_true", help="Block until the pilot pauses")
    p.add_argument("--max", type=int, default=30, dest="max_ops")
    p.add_argument("--through", type=int, help="Stop before this step number + 1")
    p = sub.add_parser("events", help="Show session events by ref (#N); --follow streams until the pilot stops")
    p.add_argument("--since", type=int, default=None, help="Start after this ref (default: the latest 40)")
    p.add_argument("--follow", "-f", action="store_true")
    p.add_argument("--timeout", type=float, default=1800)
    p = sub.add_parser("progress", help="One-screen summary: plan steps, pilot state, pending checkpoint, last events")
    p = sub.add_parser("runs", help="Run evidence, retention, and legacy history maintenance")
    p.add_argument("action", choices=["prune", "hide", "list", "import-legacy", "pin", "triage", "expire"])
    p.add_argument("ids", nargs="*")
    p.add_argument("--root", action="append", default=[], help="Read runs from this directory (repeatable)")
    p.add_argument("--from", dest="source", metavar="DIR",
                   help="import-legacy: runs directory to import, such as another checkout's artifacts/agent-sessions")
    p.add_argument("--copy", action="store_true", help="import-legacy: copy the runs and keep the originals")
    p.add_argument("--map-source", action="append", default=[], metavar="OLD=NEW",
                   help="import-legacy: rewrite spec path prefixes in the imported trails (repeatable)")
    p.add_argument("--unpin", action="store_true", help="pin: return the run to retained history")
    p.add_argument("--triage", help="triage: optional disposition label")
    p.add_argument("--apply", action="store_true", help="expire: purge due evidence (default is a dry run)")
    p.add_argument("--include-expired", action="store_true", help="list: include expired run metadata")
    p = sub.add_parser("sessions", help="Create, select, inspect, and archive testing sessions")
    p.add_argument("action", choices=["list", "create", "show", "attach", "archive"])
    p.add_argument("value", nargs="?", help="Title for create; session id for show/attach/archive")
    p.add_argument("--id", dest="session_id", help="Stable id for create")
    p.add_argument("--environment", default="")
    p.add_argument("--revision", default="", help="Source revision under test")
    p.add_argument("--purpose", choices=["smoke", "regression", "exploratory"], default="smoke")
    p.add_argument("--retained", action="store_true", help="Keep the session beyond temporary retention")
    p.add_argument("--all", action="store_true", help="list: include archived sessions")
    sub.add_parser("state", help="Current testing session, runs, requests, worker, and cursor")
    p = sub.add_parser("changes", help="Durable testing-session changes after a cursor")
    p.add_argument("--after", type=int, default=0)
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--timeout", type=float, default=0)
    p = sub.add_parser("control", help="Pause, take, release, or resume coordinated execution")
    p.add_argument("action", choices=["pause", "take", "release", "resume"])
    p.add_argument("--owner", default="human", help="New owner for take")
    p = sub.add_parser("request", help="Claim or resolve a coordination request")
    p.add_argument("action", choices=["claim", "resolve"])
    p.add_argument("id")
    p.add_argument("--owner")
    p.add_argument("--revision", type=int, help="Expected testing-session revision")
    p.add_argument("--result", help="Resolution JSON or plain text")
    sub.add_parser("init", help="Create .reverie/ (README, .gitignore, runs/, specs/) in this directory")
    p = sub.add_parser("walkthrough", help="Click-by-click Markdown from a run; --write puts it in a spec's ## Walkthrough")
    p.add_argument("run", help="Run id (see `runs list`)")
    p.add_argument("--write", metavar="SPEC", help="Replace or add the ## Walkthrough section of this spec")
    p.add_argument("--root", action="append", default=[], help="Read runs from this directory (repeatable)")
    p = sub.add_parser("audio", help="Show or set narration audio and follow-along mode")
    p.add_argument("--bluetooth", choices=["on", "off"])
    p.add_argument("--wake", type=float, help="Seconds of wake-up audio in Bluetooth mode")
    p.add_argument("--mode", choices=["fast", "follow", "step"])
    p.add_argument("--padding-ms", type=int)
    p.add_argument("--skip", action="store_true", help="Skip the current narration item")
    p.add_argument("--retry", action="store_true", help="Retry the most recent narration item")
    p = sub.add_parser("note", help="Give the pilot fixture facts (record ids, emails, URLs); no secrets")
    p.add_argument("text")
    p = sub.add_parser("suggest", help="Fast model proposes ONE step (nothing runs until accept)")
    p.add_argument("--engine", default="stack", choices=["stack", "escalation", "mercury", "laya", "jev", "liquid"],
                   help="stack (default): the decision engine proposes; the escalation model overrules when it is "
                   "unsure. escalation (old name: mercury): the escalation model alone. laya, jev or liquid: that decision "
                   "engine alone, for this command")
    p.add_argument("--hint", help="Steer the model, e.g. 'use the search box, not the menu'")
    p.add_argument("--goal")
    sub.add_parser("accept", help="Execute the pending suggestion")
    p = sub.add_parser("reject", help="Drop the pending suggestion, optionally adding a steering hint")
    p.add_argument("--hint")
    p = sub.add_parser("auto", help="Fast loop; pauses on low confidence, DONE/BLOCKED/ADMIN, or an until-condition")
    p.add_argument("--engine", default="stack", choices=["stack", "escalation", "mercury", "laya", "jev", "liquid"],
                   help="as for suggest")
    p.add_argument("--max", type=int, default=8, dest="max_steps")
    p.add_argument("--min-confidence", type=float, default=0.55)
    p.add_argument("--until-text")
    p.add_argument("--until-url")
    p.add_argument("--goal")
    p = sub.add_parser("checkpoint", help="Raise an admin checkpoint for the orchestrator (terminal work)")
    p.add_argument("title")
    p.add_argument("--command", dest="admin_command", help="The terminal command the orchestrator should run")
    p.add_argument("--step", type=int, help="Plan step this checkpoint completes")
    sub.add_parser("checkpoints", help="List admin checkpoints")
    p = sub.add_parser("wait", help="Block until the session needs the orchestrator (admin / steer / person)")
    p.add_argument("--timeout", type=float, default=900)
    p = sub.add_parser("exec", help="Run a checkpoint's command in THIS terminal and record the result")
    p.add_argument("id")
    p.add_argument("--yes", action="store_true", help="Run without the interactive confirmation")
    p.add_argument("--timeout", type=float, default=600)
    p = sub.add_parser("resolve", help="Record the outcome of a checkpoint you handled yourself")
    p.add_argument("id")
    p.add_argument("status", choices=["done", "failed", "skipped"])
    p.add_argument("--note", default="")
    p.add_argument("--exit-code", type=int)
    p = sub.add_parser("plan", help="Load a test plan: --file plan.md [--section DEMO-01] or --step ... (repeat)")
    p.add_argument("--title")
    p.add_argument("--file")
    p.add_argument("--section")
    p.add_argument("--step", action="append", default=[])
    p.add_argument("--role", default="unspecified")
    p.add_argument("--purpose", choices=["smoke", "regression", "exploratory"])
    p = sub.add_parser("spec", help="Load a stored spec: its steps become the plan, its notes go to the pilot")
    p.add_argument("file")
    p = sub.add_parser("mark", help="Set a plan step's status: mark 2 pass --note '...'")
    p.add_argument("step", type=int)
    p.add_argument("status", choices=["pending", "running", "pass", "fail", "blocked", "skipped"])
    p.add_argument("--note", default="")
    p = sub.add_parser("observe", aliases=["snapshot"], help="List observed elements (refs usable as @e5)")
    p.add_argument("--grep")
    p.add_argument("--limit", type=int, default=80)
    p.add_argument("--text", type=int, default=0, metavar="CHARS", help="Also print visible page text")
    p.add_argument("--settle", action="store_true")
    p = sub.add_parser("inspect", help="Capture native pixels and readiness details for an optional target")
    p.add_argument("ref", nargs="?")

    p = sub.add_parser("expand", help="Navigate an observed action bucket")
    p.add_argument("ref", help="Bucket id, or bucket_back / bucket_root")

    for verb, kind in (("act", None), ("click", "click"), ("fill", "fill"), ("select", "select")):
        p = sub.add_parser(verb, help=f"{'Execute' if not kind else kind.title()} an observed element")
        p.add_argument("ref", nargs="?", help="Element id from observe, e.g. e7")
        p.add_argument("--label", help="Match by label instead of id (must be unique)")
        p.add_argument("--hint", help="Match by field hint (name/id); stable across re-renders")
        p.add_argument("--value", help="With --hint: match the element whose value is this (radios)")
        if verb in {"act", "fill"}:
            p.add_argument("--text")
            p.add_argument("--redact", action="store_true", help="Keep the typed value out of narration and logs")
        if verb in {"act", "select"}:
            p.add_argument("--option", help="Option label or value for a select")
        p.add_argument("--say", help="Narrate this instead of the default phrase")
        p.set_defaults(kind=kind)

    p = sub.add_parser("visual-act", help="Act on a point in the latest screenshot (viewport CSS pixels)")
    p.add_argument("x", type=float)
    p.add_argument("y", type=float)
    p.add_argument("--text", help="Stated value to type into a safe editable field")

    p = sub.add_parser("visual-hover", help="Hover over a point in the latest screenshot (viewport CSS pixels)")
    p.add_argument("x", type=float)
    p.add_argument("y", type=float)

    p = sub.add_parser("hover", help="Move the pointer over an element (opens hover menus)")
    p.add_argument("ref", nargs="?")
    p.add_argument("--label")
    p = sub.add_parser("dialog", help="Accept or dismiss a native alert/confirm/prompt")
    p.add_argument("answer", choices=["accept", "dismiss"])
    p.add_argument("--text", help="Prompt text to enter")
    p = sub.add_parser("secret", help="Type a secret into the one visible password field (stdin or env)")
    p.add_argument("--field", help="Label/name substring to pick the password field")
    p.add_argument("--env", help="Read the value from this environment variable")
    p = sub.add_parser("press", help="Press Enter, Tab, or Escape")
    p.add_argument("key", choices=["Enter", "Tab", "Escape"])
    p = sub.add_parser("goto")
    p.add_argument("url")
    sub.add_parser("tabs")
    sub.add_parser("back", help="Press the browser Back button")
    sub.add_parser("tidy-tabs", help="Close every tab except the current one")
    p = sub.add_parser("tab", help="tab new URL [--isolated] | tab close")
    p.add_argument("action", choices=["new", "close"])
    p.add_argument("url", nargs="?")
    p.add_argument("--isolated", action="store_true", help="Fresh cookie jar: test a link signed out")
    p = sub.add_parser("switch", help="Switch to another tab (default: the newest other tab)")
    p.add_argument("target", nargs="?")
    p = sub.add_parser("check", help="Assert visible text or URL; exit 1 on failure")
    p.add_argument("--text")
    p.add_argument("--absent")
    p.add_argument("--url")
    p.add_argument("--link", help="Visible link text; with --href, check its target without printing it")
    p.add_argument("--href")
    p = sub.add_parser("say", help="Narrate text (caption + speech)")
    p.add_argument("text")
    p.add_argument("--wait", action="store_true")
    p = sub.add_parser("ask", help="Wait for a person to answer in the window")
    p.add_argument("question")
    p.add_argument("--choices", help="Comma-separated buttons (default: Continue)")
    p.add_argument("--no-text", action="store_true")
    p.add_argument("--timeout", type=float, default=900)
    p = sub.add_parser("reply", help="Answer the pending prompt from the terminal")
    p.add_argument("choice", nargs="?", default="Continue")
    p.add_argument("--text", default="")
    p = sub.add_parser("screenshot")
    p.add_argument("path", nargs="?")
    for verb in ("step", "run"):
        p = sub.add_parser(verb, help="Autonomous decision-engine " + ("step" if verb == "step" else "run"))
        p.add_argument("--goal")
        p.add_argument("--engine", choices=["laya", "jev", "liquid"])
        p.add_argument("--confirm", action="store_true", help="Ask in the window before each action")
        if verb == "run":
            p.add_argument("--max-steps", type=int, default=20)
    sub.add_parser("history")
    p = sub.add_parser("ui", help="Open the run dashboard (current and past runs) in your default browser")
    p.add_argument("--print-only", action="store_true")
    p.add_argument("--root", action="append", default=[],
                   help="Read runs from this directory instead of .reverie/runs (repeatable)")
    p = sub.add_parser("watch", help="Open this session's single-session watch page")
    p.add_argument("--print-only", action="store_true")
    p = sub.add_parser("recap", help="Speak a medium-level summary of the steps since the last recap")
    p.add_argument("--note", default="")
    sub.add_parser("reload", help="Reload session code in place (developer aid; keeps browser and login)")
    sub.add_parser("stop")

    argv = list(sys.argv[1:] if argv is None else argv)
    if "--json" in argv:  # agent-browser style: accept --json anywhere on the line
        argv.remove("--json")
        argv.insert(0, "--json")
    args = parser.parse_args(argv)
    _CALL_CONTEXT.update(actor=args.actor, epoch=args.epoch, observation_id=args.observation_id,
                         operation_id=args.operation_id, operation_id_used=False)
    name, command = args.session, args.command
    if command == "start":
        result = start(args)
        if args.ui:
            main(["--session", name, "ui"])
    elif command == "sessions":
        from .coordination import CoordinationStore

        store = CoordinationStore(project.project_root())
        if args.action == "list":
            result = {"sessions": store.list_sessions(include_archived=args.all)}
        elif args.action == "create":
            if not args.value:
                print("refused: sessions create needs a title", file=sys.stderr)
                raise SystemExit(2)
            created = store.create_session(args.value, environment=args.environment, revision=args.revision,
                                           purpose=args.purpose, temporary=not args.retained,
                                           session_id=args.session_id)
            activate_session(created["id"])
            result = {"session": created, "active": True}
        else:
            if not args.value:
                print(f"refused: sessions {args.action} needs a session id", file=sys.stderr)
                raise SystemExit(2)
            selected = store.get_session(args.value)
            if not selected:
                print(f"refused: no testing session {args.value!r}", file=sys.stderr)
                raise SystemExit(2)
            if args.action == "show":
                result = store.snapshot(args.value)
            elif args.action == "attach":
                path = activate_session(args.value)
                result = {"session": selected, "active": True, "path": str(path),
                          "note": "Subsequently started workers inherit this session; live workers stay bound."}
            else:
                selected = store.update_session(args.value, archived=True)
                try:
                    active = json.loads(active_session_file().read_text()).get("session_id")
                except (OSError, ValueError):
                    active = None
                if active == args.value:
                    active_session_file().unlink(missing_ok=True)
                result = {"session": selected}
    elif command == "state":
        result = call(name, "state")
    elif command == "changes":
        result = call(name, "changes", {"after": args.after, "limit": args.limit, "timeout": args.timeout},
                      timeout=args.timeout + 30)
    elif command == "control":
        if args.action == "pause":
            result = call(name, "pilot_pause")
        elif args.action == "take":
            result = call(name, "take_control", {"owner": args.owner, "expected_epoch": args.epoch})
        elif args.action == "release":
            result = call(name, "release_control", {"expected_epoch": args.epoch})
        else:
            released = call(name, "release_control", {"expected_epoch": args.epoch})
            resumed = call(name, "pilot", {"detach": True})
            result = {"released": released, "pilot": resumed}
    elif command == "request":
        body = {"request_id": args.id, "owner": args.owner, "expected_revision": args.revision}
        if args.action == "claim":
            body["owner"] = args.owner or args.actor
            result = call(name, "request_claim", body)
        else:
            try:
                body["result"] = json.loads(args.result) if args.result is not None else {}
            except ValueError:
                body["result"] = args.result
            result = call(name, "request_resolve", body)
    elif command == "recap":
        result = call(name, "recap", {"note": args.note}, timeout=120)
    elif command == "checkpoint":
        result = call(name, "checkpoint", {"title": args.title, "command": args.admin_command, "step": args.step})
    elif command == "checkpoints":
        result = call(name, "checkpoints")
    elif command == "wait":
        result = call(name, "wait", {"timeout": args.timeout}, timeout=args.timeout + 30)
    elif command == "exec":
        result = run_checkpoint(name, args)
    elif command == "resolve":
        result = call(name, "resolve", {"id": args.id, "status": args.status, "note": args.note,
                                        "exit_code": args.exit_code})
    elif command == "plan":
        title, steps = args.title, list(args.step)
        source = None
        if args.file:
            parsed_title, parsed = parse_plan(open(args.file).read(), args.section)
            title, steps, source = title or parsed_title, steps + parsed, args.file
        result = call(name, "plan", {"title": title, "steps": steps, "source": source,
                                      "role": args.role, "purpose": args.purpose})
    elif command == "spec":
        title, steps, notes, meta = parse_spec(open(args.file).read())
        result = call(name, "plan", {"title": title, "steps": steps, "source": os.path.abspath(args.file),
                                      "role": meta.get("role", "unspecified"), "purpose": meta.get("purpose")})
        for note in notes:
            call(name, "note", {"text": note})
        result["notes_loaded"] = len(notes)
    elif command == "mark":
        result = call(name, "mark", {"step": args.step, "status": args.status, "note": args.note})
    elif command == "do":
        result = call(name, "do", {"intent": args.intent, "hints": args.hint, "max_steps": args.max_steps,
                                   "until_text": args.until_text, "until_url": args.until_url}, timeout=1800)
    elif command == "pilot":
        if args.action == "stop":
            result = call(name, "pilot_stop", timeout=180)
        else:
            result = call(name, "pilot", {"max_ops": args.max_ops, "through": args.through,
                                          "detach": not args.foreground}, timeout=3600)
            if result.get("started") and not args.json:
                print(f"pilot started; follow with: reverie --session {name} events --since {result['from_ref']} -f")
    elif command == "events":
        since, deadline = args.since, time.monotonic() + args.timeout
        collected = []
        while True:
            batch = call(name, "events", {"since": since})
            collected.extend(batch["events"])
            if args.follow and args.json:
                print(json.dumps(batch, default=str), flush=True)
                collected = collected[-200:]
            for event in batch["events"]:
                if not args.json:
                    print(format_event(event), flush=True)
            since = batch["next"]
            if not args.follow or time.monotonic() > deadline or (
                    batch["pilot"] == "idle" and not batch["events"]):
                break
            time.sleep(1.0)
        result = {"next": since, "pilot": batch["pilot"],
                  "paused": (batch.get("pilot_result") or {}).get("paused"), "events": collected}
        if args.json and not args.follow:
            show(result, True)
        elif not args.json:
            print(f"next: --since {since}  pilot: {batch['pilot']}"
                  + (f"  paused: {result['paused']}" if result["paused"] else ""))
        return
    elif command == "progress":
        batch = call(name, "progress")
        if args.json:
            show(batch, True)
            return
        test = batch.get("test")
        print(f"status: {batch['status']}  pilot: {batch['pilot']}  url: {batch['url']}")
        if batch.get("pilot_result"):
            print(f"last pause: {batch['pilot_result'].get('paused')}")
        if test:
            print(f"test: {test['title']}  [{test['result']}]")
            for step in test["steps"]:
                note = f"  — {step['note'][:100]}" if step["note"] else ""
                print(f"  {step['n']:>2}. [{step['status']:<7}] {step['title'][:80]}{note}")
                for finding in step.get("findings", []):
                    print(f"      FINDING {finding.get('severity')}: {finding.get('what')}")
        pending = batch.get("checkpoints", [e for e in batch["events"] if e["event"] == "checkpoint"])
        resolved = {e.get("id") for e in batch["events"] if e["event"] == "resolve"}
        for cp in pending:
            if cp.get("id") not in resolved:
                print(f"checkpoint {cp['id']} waiting: {cp['title']}")
        for event in batch["events"][-8:]:
            print(format_event(event))
        return
    elif command == "init":
        created = project.init()
        root = project.project_root()
        if created:
            print(f"created in {root}:")
            for path in created:
                print(f"  {path.relative_to(root)}{'/' if path.is_dir() else ''}")
        else:
            print(f"{root / project.NAME} is ready; nothing to create")
        return
    elif command == "runs":
        from . import dashboard as board
        from .coordination import CoordinationStore

        roots = run_roots(args.root)
        store = CoordinationStore(project.project_root())
        if args.action == "pin":
            if len(args.ids) != 1:
                print("refused: runs pin needs one run id", file=sys.stderr)
                raise SystemExit(2)
            result = {"run": store.pin_run(args.ids[0], pinned=not args.unpin)}
        elif args.action == "triage":
            if len(args.ids) != 1:
                print("refused: runs triage needs one run id", file=sys.stderr)
                raise SystemExit(2)
            result = {"run": store.triage_run(args.ids[0], args.triage)}
        elif args.action == "expire":
            result = {"runs": store.expire_runs(dry_run=not args.apply), "applied": bool(args.apply)}
        elif args.action == "import-legacy":
            legacy = Path(args.source).expanduser() if args.source else project.legacy_runs_dir()
            mapping = [tuple(pair.split("=", 1)) for pair in args.map_source if "=" in pair]
            moved = project.import_legacy(source=legacy, copy=args.copy, mapping=mapping)
            verb = "copied" if args.copy else "moved"
            print(f"{verb} {len(moved)} runs from {legacy} to {project.runs_dir()}" if legacy
                  else "no legacy artifacts/agent-sessions directory; nothing to import")
            for folder in moved:
                print(f"  {folder}")
            return
        elif args.action == "prune":
            hidden = board.prune(roots)
            print(f"hid {len(hidden)} broken or failed runs (trails kept on disk):")
            for run_id in hidden:
                print(f"  {run_id}")
            return
        elif args.action == "hide":
            for root in roots:
                mine = [i for i in args.ids if os.path.isdir(os.path.join(root, i.split("~")[0]))]
                if mine:
                    board.hide(root, mine)
            print(f"hid {len(args.ids)} runs")
            return
        else:
            coordinated = store.list_runs(include_expired=args.include_expired)
            if coordinated:
                known = {run["id"] for run in coordinated}
                legacy = [run for run in board.all_runs(roots) if run["id"] not in known]
                result = {"runs": coordinated + legacy}
            else:
                for run in board.all_runs(roots):
                    print(f"{run['id']:<40} {run['result']:<10} {run['title'][:60]}")
                return
    elif command == "walkthrough":
        from . import dashboard as board

        run = next((r for r in board.all_runs(run_roots(args.root), include_hidden=True) if r["id"] == args.run), None)
        if not run:
            print(f"refused: no run {args.run}", file=sys.stderr)
            raise SystemExit(2)
        text = f"Recorded from run `{run['id']}` ({run['result']}, {run['started'].replace('T', ' ')}).\n\n" \
            + board.walkthrough(run)
        if args.write:
            spec = open(args.write).read()
            section = "## Walkthrough\n\n" + text + "\n"
            if "## Walkthrough" in spec:
                spec = re.sub(r"## Walkthrough\n.*?(?=\n## |\Z)", lambda m: section.rstrip("\n") + "\n", spec, flags=re.S)
            elif "## Evidence" in spec:
                spec = spec.replace("## Evidence", section + "## Evidence", 1)
            else:
                spec = spec.rstrip("\n") + "\n\n" + section
            open(args.write, "w").write(spec)
            print(f"wrote the walkthrough into {args.write}")
        else:
            print(text)
        return
    elif command == "tidy-tabs":
        result = call(name, "tidy_tabs")
    elif command == "audio":
        result = call(name, "audio", {"bluetooth": None if args.bluetooth is None else args.bluetooth == "on",
                                      "wake_seconds": args.wake, "mode": args.mode,
                                      "padding_ms": args.padding_ms, "skip": args.skip, "retry": args.retry})
    elif command == "note":
        result = call(name, "note", {"text": args.text})
    elif command == "tab":
        if args.action == "new":
            if not args.url:
                print("refused: tab new needs a URL", file=sys.stderr)
                raise SystemExit(2)
            result = call(name, "open_tab", {"url": args.url, "isolated": args.isolated})
        else:
            result = call(name, "close_tab")
    elif command == "goal":
        result = call(name, "goal", {"goal": args.goal})
    elif command == "suggest":
        result = call(name, "suggest", {"engine": args.engine, "hint": args.hint, "goal": args.goal}, timeout=180)
    elif command in {"accept", "reject"}:
        result = call(name, command, {"hint": getattr(args, "hint", None)}, timeout=180)
    elif command == "auto":
        if args.goal:
            call(name, "goal", {"goal": args.goal})
        result = call(name, "auto", {"engine": args.engine, "max_steps": args.max_steps,
                                     "min_confidence": args.min_confidence, "until_text": args.until_text,
                                     "until_url": args.until_url}, timeout=1800)
    elif command in {"observe", "snapshot"}:
        result = call(name, "observe", {"grep": args.grep, "limit": args.limit, "text_limit": args.text,
                                        "settle": args.settle})
    elif command == "inspect":
        result = call(name, "inspect", {"ref": args.ref})
    elif command == "expand":
        result = call(name, "expand", {"ref": args.ref})
    elif command in {"act", "click", "fill", "select"}:
        result = call(name, "act", {"ref": args.ref, "label": args.label, "kind": args.kind,
                                    "text": getattr(args, "text", None), "option": getattr(args, "option", None),
                                    "narration": args.say, "redact": getattr(args, "redact", False),
                                    "hint": args.hint, "value": args.value})
    elif command == "visual-act":
        result = call(name, "visual_act", {"x": args.x, "y": args.y, "text": args.text})
    elif command == "visual-hover":
        result = call(name, "visual_hover", {"x": args.x, "y": args.y})
    elif command == "hover":
        result = call(name, "hover", {"ref": args.ref, "label": args.label})
    elif command == "dialog":
        result = call(name, "dialog", {"accept": args.answer == "accept", "text": args.text})
    elif command == "secret":
        value = os.environ.get(args.env, "") if args.env else (
            getpass.getpass("secret: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n"))
        if not value:
            print("refused: empty secret", file=sys.stderr)
            raise SystemExit(2)
        result = call(name, "secret", {"value": value, "field": args.field})
    elif command in {"press", "goto", "switch"}:
        key = {"press": "key", "goto": "url", "switch": "target"}[command]
        result = call(name, command, {key: getattr(args, {"press": "key", "goto": "url", "switch": "target"}[command])})
    elif command == "check":
        result = call(name, "check", {"text": args.text, "absent": args.absent, "url": args.url,
                                      "link": args.link, "href": args.href})
    elif command == "say":
        result = call(name, "say", {"text": args.text, "wait": args.wait})
    elif command == "ask":
        choices = [c.strip() for c in args.choices.split(",")] if args.choices else None
        result = call(name, "ask", {"question": args.question, "choices": choices, "allow_text": not args.no_text,
                                    "timeout": args.timeout}, timeout=args.timeout + 30)
    elif command == "reply":
        result = call(name, "reply", {"choice": args.choice, "text": args.text})
    elif command == "screenshot":
        result = call(name, "screenshot", {"path": args.path})
    elif command in {"step", "run"}:
        body = {"goal": args.goal, "engine": args.engine, "confirm": args.confirm}
        if command == "run":
            body["max_steps"] = args.max_steps
        result = call(name, command, body, timeout=3600)
    elif command == "ui":
        result = dashboard(not args.print_only, run_roots(args.root))
    elif command == "watch":
        info = load(name)
        if not info:
            print(f"reverie: no session named {name!r}.", file=sys.stderr)
            raise SystemExit(4)
        url = f"http://127.0.0.1:{info['port']}/watch"
        if not args.print_only:
            bootstrap = f"{url}?token={info['token']}"
            subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", bootstrap],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        result = {"url": f"{url}?token={info['token']}"}
    elif command == "reload":
        result = call(name, "reload")
        call(name, "reload_modules")
    else:
        result = call(name, command)
    show(result, args.json)
    if command == "check" and not result.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
