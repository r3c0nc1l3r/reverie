"""Session daemon: owns the headed Chromium and one Session, answers loopback commands with a token."""

import argparse
import hashlib
import json
import os
import secrets
import sys
import threading
import traceback
from contextlib import nullcontext
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

READ_ONLY_COMMANDS = {"status", "progress", "state", "changes", "events", "history", "tabs", "checkpoints"}
UNBOUND_COMMANDS = {
    "audio", "checkpoint", "inspect", "note", "observe", "pilot_pause", "pilot_stop", "release_control", "reply",
    "resolve", "request_claim", "request_resolve", "take_control",
}
SESSION_COOKIE = "reverie-session"
MAX_REQUEST_BYTES = 1 << 20


class DispatchConflict(ValueError):
    """A command cannot safely be executed or replayed."""


def _same_token(left, right):
    return bool(left and right) and secrets.compare_digest(str(left), str(right))


def _cookie_token(value):
    try:
        cookie = SimpleCookie(value or "")
        return cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else None
    except (CookieError, KeyError):
        return None


def _same_origin(origin, host):
    if not origin:
        return True  # Native CLI requests do not carry an Origin header.
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and parsed.netloc == host \
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _execute(session, name, arguments):
    if name in COMMANDS:
        return COMMANDS[name](session, arguments)
    handler = getattr(session, f"cmd_{name}", None)
    if handler is None:
        raise KeyError(f"Unknown command {name}")
    return handler(**arguments)


def _digest_marker(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return {"redacted_sha256": hashlib.sha256(encoded).hexdigest()}


def _ledger_arguments(name, arguments):
    """Keep retry identity for sensitive actions without persisting their plaintext values."""
    persisted = dict(arguments)
    sensitive = name == "secret" or (name == "act" and bool(arguments.get("redact")))
    if sensitive:
        for field in ("value", "text"):
            if field in persisted and persisted[field] is not None:
                persisted[field] = _digest_marker(persisted[field])
    return persisted, sensitive


def dispatch(session, name, arguments=None, metadata=None):
    """Execute one request with optional durable idempotency and command context."""
    arguments, metadata = arguments or {}, metadata or {}
    operation_id = metadata.get("operation_id")
    coordination = getattr(session, "coordination", None)
    session_id = getattr(session, "testing_session_id", None)
    actor = metadata.get("actor") or "coordinator"
    epoch = metadata.get("epoch")
    observation_id = metadata.get("observation_id")
    begun = None
    ledger_arguments, sensitive = _ledger_arguments(name, arguments)
    if operation_id and coordination and session_id and name not in READ_ONLY_COMMANDS:
        bound = name not in UNBOUND_COMMANDS
        begun = coordination.begin_command(
            session_id, operation_id, name, arguments=ledger_arguments,
            worker_id=getattr(session, "worker_id", None) if bound else None,
            owner=actor if bound else None, epoch=epoch if bound else None,
            incarnation=getattr(session, "incarnation", None) if bound else None,
        )
        if begun["status"] == "completed":
            return begun.get("result")
        if begun["status"] == "failed":
            raise DispatchConflict(f"operation {operation_id!r} previously failed: {begun.get('error')}")
        if begun["status"] != "new":
            raise DispatchConflict(
                f"operation {operation_id!r} is already running; its outcome is indeterminate, do not repeat it"
            )
        if bound:
            epoch = begun["epoch"]
    context = session.command_context(actor, epoch, observation_id) \
        if hasattr(session, "command_context") else nullcontext()
    try:
        with context:
            result = _execute(session, name, arguments)
    except Exception as error:
        if begun:
            persisted_error = {"type": type(error).__name__,
                               "message": "redacted" if sensitive else str(error)}
            coordination.finish_command(session_id, operation_id, error=persisted_error)
        raise
    if begun:
        coordination.finish_command(session_id, operation_id,
                                    result={"redacted": True} if sensitive else result)
    return result


def state_dir():
    base = os.environ.get("XDG_RUNTIME_DIR") or str(Path.home() / ".cache")
    path = Path(base) / "laya-agent"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def daemon_name(name):
    return f"laya-agent-{name}"


def state_file(name):
    return state_dir() / f"{name}.json"


def load_environment():
    """Fill os.environ from the .env files in `project.env_files()`. Set variables and earlier files win. An empty
    value (`OPENROUTER_API_KEY=` copied from .env.example) does not hide a value from a later file."""
    from .project import env_files

    for path in env_files():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            if value:
                os.environ.setdefault(key.strip(), value)


COMMANDS = {
    "status": lambda s, a: s.summary(),
    "observe": lambda s, a: {**s.observe(settle=a.get("settle", False)),
                             "items": s.elements(a.get("grep"), a.get("limit", 80)),
                             "text": s.text(a.get("text_limit", 0)) if a.get("text_limit") else None},
    "expand": lambda s, a: s.expand(a.get("ref")),
    "act": lambda s, a: s.act(a.get("ref"), a.get("label"), a.get("kind"), a.get("text"), a.get("option"),
                              a.get("narration"), a.get("redact", False), "orchestrator", None, a.get("hint"),
                              a.get("value")),
    "visual_act": lambda s, a: s.visual_act(a.get("x"), a.get("y"), text=a.get("text")),
    "visual_hover": lambda s, a: s.visual_hover(a.get("x"), a.get("y")),
    "hover": lambda s, a: s.hover(a.get("ref"), a.get("label")),
    "secret": lambda s, a: s.secret(a["value"], a.get("field")),
    "press": lambda s, a: s.press(a["key"]),
    "goto": lambda s, a: s.goto(a["url"]),
    "tabs": lambda s, a: {"tabs": s.tabs()},
    "open_tab": lambda s, a: s.open_tab(a["url"], a.get("isolated", False)),
    "close_tab": lambda s, a: s.close_tab(),
    "do": lambda s, a: s.do(a["intent"], a.get("hints") or [], a.get("max_steps", 6), a.get("until_text"),
                            a.get("until_url"), a.get("min_confidence", 0.55)),
    "switch": lambda s, a: s.switch(a.get("target")),
    "check": lambda s, a: s.check(a.get("text"), a.get("absent"), a.get("url"), a.get("link"), a.get("href")),
    "say": lambda s, a: (s.say(a["text"], wait=a.get("wait", False)), s.summary())[1],
    "ask": lambda s, a: s.ask(a["question"], a.get("choices"), a.get("allow_text", True), a.get("timeout", 900)),
    "reply": lambda s, a: s.reply(a.get("choice", "Continue"), a.get("text", "")),
    "screenshot": lambda s, a: s.screenshot(a.get("path")),
    "step": lambda s, a: s.step(a.get("goal"), a.get("engine"), a.get("confirm", False)),
    "run": lambda s, a: s.run(a.get("goal"), a.get("engine"), a.get("max_steps", 20), a.get("confirm", False)),
    "history": lambda s, a: {"history": s.history},
    "goal": lambda s, a: s.set_goal(a["goal"]),
    "suggest": lambda s, a: s.suggest(a.get("engine") or "stack", a.get("hint"), a.get("goal")),
    "accept": lambda s, a: s.accept(),
    "reject": lambda s, a: s.reject(a.get("hint")),
    "auto": lambda s, a: s.auto(a.get("engine") or "stack", a.get("max_steps", 8), a.get("min_confidence", 0.55),
                                a.get("until_text"), a.get("until_url")),
    "checkpoint": lambda s, a: s.checkpoint(a["title"], a.get("command"), a.get("step"), "orchestrator"),
    "checkpoints": lambda s, a: {"checkpoints": s.checkpoints},
    "resolve": lambda s, a: s.resolve_checkpoint(a["id"], a["status"], a.get("exit_code"), a.get("output"),
                                                 a.get("note", "")),
    "wait": lambda s, a: s.wait(a.get("timeout", 900)),
    "recap": lambda s, a: s.recap(a.get("outcome"), a.get("note", "")),
    "plan": lambda s, a: s.plan(a.get("title"), a.get("steps") or [], a.get("source"),
                                 a.get("role", "unspecified"), a.get("purpose")),
    "mark": lambda s, a: s.mark(int(a["step"]), a["status"], a.get("note", ""), recap=a.get("recap", True)),
}


def make_handler(session, token, stop, name="default", publish_state=None):
    """Create the loopback HTTP handler; split out so transport rules can be integration tested."""
    session_error = type("SessionErrorPlaceholder", (ValueError,), {})
    try:
        from .session import SessionError as session_error
    except ImportError:
        pass

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, payload):
            body = json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            query = dict(item.split("=", 1) if "=" in item else (item, "")
                         for item in url.query.split("&") if item)
            supplied = self.headers.get("X-Laya-Agent-Token") or _cookie_token(self.headers.get("Cookie")) \
                or query.get("token")
            if not _same_token(supplied, token):
                return self.reply(401, {"error": "Session authentication required"})
            if url.path == "/watch":
                if query.get("token"):
                    self.send_response(303)
                    self.send_header("Location", "/watch")
                    self.send_header("Set-Cookie", f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                page = (Path(__file__).with_name("watch.html").read_text().replace("__TOKEN__", "")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(page)
            if url.path == "/watch/state":
                return self.reply(200, session.watch_state())
            return self.reply(404, {"error": "Not found"})

        def do_POST(self):
            try:
                header_token = self.headers.get("X-Laya-Agent-Token")
                cookie_token = _cookie_token(self.headers.get("Cookie"))
                supplied = header_token or cookie_token
                if not _same_token(supplied, token):
                    return self.reply(401, {"error": "Session authentication required"})
                if not header_token and not self.headers.get("Origin"):
                    return self.reply(403, {"error": "Origin required"})
                if not _same_origin(self.headers.get("Origin"), self.headers.get("Host", "")):
                    return self.reply(403, {"error": "Origin rejected"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self.reply(400, {"error": "Invalid Content-Length"})
                if length < 0 or length > MAX_REQUEST_BYTES:
                    return self.reply(413, {"error": "Request body exceeds 1 MiB"})
                try:
                    request = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self.reply(400, {"error": "Request body must be valid JSON"})
                if not isinstance(request, dict):
                    return self.reply(400, {"error": "Request body must be a JSON object"})
                command, arguments = request.get("command"), request.get("args", {})
                if not isinstance(command, str) or not command:
                    return self.reply(400, {"error": "command must be a non-empty string"})
                if not isinstance(arguments, dict):
                    return self.reply(400, {"error": "args must be a JSON object"})
                if command == "stop":
                    stop.set()
                    return self.reply(200, {"stopped": name})
                if command == "reload":
                    return self.reply(200, _reload_session(session))
                metadata = {key: request.get(key) for key in
                            ("operation_id", "actor", "epoch", "observation_id") if request.get(key) is not None}
                payload = dispatch(session, command, arguments, metadata)
                if publish_state:
                    publish_state(self.server.server_address[1])
                return self.reply(200, payload)
            except (session_error, DispatchConflict, ValueError) as error:
                return self.reply(409, {"error": str(error)})
            except Exception as error:
                if type(error).__name__ in {"SessionError", "ControlError", "CoordinationConflict",
                                            "CoordinationNotFound"}:
                    return self.reply(409, {"error": str(error)})
                session.log("error", error=repr(error), trace=traceback.format_exc(limit=4))
                return self.reply(500, {"error": f"{type(error).__name__}: {error}. No automatic retry."})

        def log_message(self, *_args):
            pass

    return Handler


def _reload_session(session):
    """Developer aid: pick up edited session/steer code without losing browser state."""
    import importlib

    from .. import browser as browser_module
    from . import session as session_module
    from . import steer

    browser_module.READ_STATE = Path(browser_module.__file__).with_name("snapshot.js").read_text()
    browser_module.MARKER = f"(() => {{ const state={browser_module.READ_STATE}; return state?.marker ?? null; }})()"
    importlib.reload(steer)
    importlib.reload(session_module)
    session.__class__ = session_module.Session
    session.browser.__class__ = session_module.HeadedBrowser
    session.browser.configure_session()
    for attr, default in (("checkpoints", []), ("fresh_hint", False), ("laya_min", 0.6)):
        if not hasattr(session, attr):
            setattr(session, attr, default)
    session.log("reload")
    return {"reloaded": True, **session.summary()}


def serve(args):
    load_environment()
    from .chromium import Chromium

    profile = Path(args.profile or state_dir() / f"{args.name}-profile")
    # browser_harness reads BU_NAME at import time, and importing this package imports it. The CLI therefore
    # sets BU_NAME in this process's environment at spawn; refuse to share the default daemon by accident.
    if os.environ.get("BU_NAME") != daemon_name(args.name):
        raise RuntimeError("Start sessions with `reverie start` so the browser daemon gets its own name")
    from . import downloads

    download_dir = downloads.resolve(args.download_dir)
    chromium = Chromium(profile, headed=not args.headless, download_dir=download_dir)
    os.environ["BU_CDP_URL"] = chromium.cdp_url
    from .session import Session

    try:
        session = Session(args.url, name=args.name, voice=args.voice, trail_dir=args.trail_dir,
                          goal=args.goal, engine=args.engine, download_dir=download_dir,
                          stream_interval=0.8 if args.headless else 0.0,
                          testing_session_id=args.testing_session, project_root=args.project_root,
                          follow_along=args.follow_along, padding_ms=args.padding_ms)
    except Exception:
        chromium.close()
        raise
    token = secrets.token_urlsafe(24)
    stop = threading.Event()
    path = state_file(args.name)
    state_lock = threading.Lock()

    def publish_state(port):
        info = {"name": args.name, "pid": os.getpid(), "port": port, "token": token,
                "trail": str(session.trail_dir), "voice": session.narrator.voice,
                "browser": chromium.executable, "testing_session_id": session.testing_session_id,
                "worker_id": session.worker_id, "project_root": str(session.coordination.root),
                "run_id": session.run_id}
        with state_lock:
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(info))
            temporary.chmod(0o600)
            temporary.replace(path)
        return info

    Handler = make_handler(session, token, stop, args.name, publish_state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    publish_state(server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    session.say(f"Agent session {args.name} is ready")
    try:
        while not stop.wait(0.5):
            if chromium.process.poll() is not None:
                break  # The person closed the window.
    finally:
        session.say("Session closed", wait=True)
        server.shutdown()
        session.close()
        chromium.close()
        path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="reverie-server")
    parser.add_argument("--name", default="default")
    parser.add_argument("--url", required=True)
    parser.add_argument("--voice", default="auto")
    parser.add_argument("--goal")
    parser.add_argument("--engine", choices=["laya", "jev", "liquid"])
    parser.add_argument("--trail-dir")
    parser.add_argument("--profile")
    parser.add_argument("--download-dir")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--testing-session")
    parser.add_argument("--project-root")
    parser.add_argument("--follow-along", action="store_true")
    parser.add_argument("--padding-ms", type=int, default=350)
    args = parser.parse_args(argv)
    try:
        serve(args)
    except Exception as error:
        print(f"reverie: session failed to start: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
