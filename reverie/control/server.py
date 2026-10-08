"""Session daemon: owns the headed Chromium and one Session, answers loopback commands with a token."""

import argparse
import json
import os
import secrets
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


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
    "act": lambda s, a: s.act(a.get("ref"), a.get("label"), a.get("kind"), a.get("text"), a.get("option"),
                              a.get("narration"), a.get("redact", False), "orchestrator", None, a.get("hint"),
                              a.get("value")),
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
    "plan": lambda s, a: s.plan(a.get("title"), a.get("steps") or [], a.get("source")),
    "mark": lambda s, a: s.mark(int(a["step"]), a["status"], a.get("note", "")),
}


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
    from .session import Session, SessionError

    try:
        session = Session(args.url, name=args.name, voice=args.voice, trail_dir=args.trail_dir,
                          goal=args.goal, engine=args.engine, download_dir=download_dir, stream_interval=0.8 if args.headless else 0.0)
    except Exception:
        chromium.close()
        raise
    token = secrets.token_urlsafe(24)
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, payload):
            body = json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # Read-only watch page for a person; the token travels in the URL that `reverie ui` opens.
            url = urlparse(self.path)  # Loopback only; the read-only watch pages need no token.
            if url.path == "/watch":
                page = (Path(__file__).with_name("watch.html").read_text().replace("__TOKEN__", token)).encode()
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
            # Loopback-only server; commands need no token.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length) or b"{}")
                name, arguments = request.get("command"), request.get("args") or {}
                if name == "stop":
                    stop.set()
                    return self.reply(200, {"stopped": args.name})
                if name == "reload":
                    # Developer aid: pick up edited session/steer code without losing the browser or login.
                    import importlib

                    from .. import browser as browser_module
                    from . import session as session_module
                    from . import steer

                    browser_module.READ_STATE = Path(browser_module.__file__).with_name("snapshot.js").read_text()
                    browser_module.MARKER = (
                        f"(() => {{ const state={browser_module.READ_STATE}; return state?.marker ?? null; }})()")
                    importlib.reload(steer)
                    importlib.reload(session_module)
                    session.__class__ = session_module.Session
                    session.browser.__class__ = session_module.HeadedBrowser
                    session.browser.configure_session()
                    for attr, default in (("checkpoints", []), ("fresh_hint", False), ("laya_min", 0.6)):
                        if not hasattr(session, attr):
                            setattr(session, attr, default)
                    session.log("reload")
                    return self.reply(200, {"reloaded": True, **session.summary()})
                if name in COMMANDS:
                    return self.reply(200, COMMANDS[name](session, arguments))
                handler = getattr(session, f"cmd_{name}", None)  # new commands work after `reload`
                if handler is None:
                    return self.reply(400, {"error": f"Unknown command {name}"})
                return self.reply(200, handler(**arguments))
            except SessionError as error:
                return self.reply(409, {"error": str(error)})
            except Exception as error:
                if type(error).__name__ == "SessionError":  # raised by reloaded session code
                    return self.reply(409, {"error": str(error)})
                session.log("error", error=repr(error), trace=traceback.format_exc(limit=4))
                return self.reply(500, {"error": f"{type(error).__name__}: {error}. No automatic retry."})

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    info = {"name": args.name, "pid": os.getpid(), "port": server.server_address[1], "token": token,
            "trail": str(session.trail_dir), "voice": session.narrator.voice, "browser": chromium.executable}
    path = state_file(args.name)
    path.write_text(json.dumps(info))
    path.chmod(0o600)
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
    parser.add_argument("--engine", choices=["laya", "jev"])
    parser.add_argument("--trail-dir")
    parser.add_argument("--profile")
    parser.add_argument("--download-dir")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args(argv)
    try:
        serve(args)
    except Exception as error:
        print(f"reverie: session failed to start: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
