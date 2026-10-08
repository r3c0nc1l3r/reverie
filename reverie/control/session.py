"""One headed, narrated browser session. Every mutation goes through the observed-action executor.

The controlling agent (a person, a coding agent, or a decision engine: Jev or Laya) picks among actions that the
last observation actually contains. Nothing here accepts selectors or executable code from the caller.
"""

import base64
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from browser_harness.helpers import cdp

from ..browser import Browser, StalePage
from ..model import MissingKey
from ..settings import setting
from . import downloads
from .narrator import Narrator
from .project import runs_dir, spec_id, write_run_summary

OVERLAY = Path(__file__).with_name("overlay.js").read_text()
KEYS = {
    "Enter": {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"},
    "Tab": {"key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
    "Escape": {"key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27},
}
# Password inputs are excluded from observed actions on purpose. `secret` is an explicit, separate path for
# authorized test credentials: the value never enters argv, narration, overlay text, or the trail.
SECRET_TARGET = """(query => {
  const words = s => (s || '').toLowerCase();
  const describe = e => words([...(e.labels || [])].map(l => l.innerText).join(' ') + ' ' +
    (e.getAttribute('aria-label') || '') + ' ' + e.name + ' ' + e.id + ' ' + (e.placeholder || ''));
  const fields = [...document.querySelectorAll('input[type="password"]')].filter(e =>
    e.isConnected && !e.disabled && !e.readOnly && e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) &&
    (!query || describe(e).includes(words(query))));
  if (fields.length !== 1) return {count: fields.length};
  const e = fields[0], r = e.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2;
  if (!r.width || !r.height || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return {count: 1, hidden: true};
  if (!e.contains(document.elementFromPoint(x, y))) return {count: 1, covered: true};
  return {count: 1, x, y, rect: {x: r.x, y: r.y, w: r.width, h: r.height}};
})"""


STOP_WORDS = {"the", "a", "an", "and", "or", "to", "of", "on", "in", "this", "that", "for", "from", "with", "page",
              "click", "open", "button", "link", "then", "case"}


SECRET_PARAM = re.compile(r"(?i)\b(token|code|otp|key|sig|signature|password|pwd)=([^&\s\"'<>]+)")


def scrub(value):
    """Mask one-time tokens and codes in URLs and text before they reach a trail, a model, or the screen."""
    if isinstance(value, str):
        return SECRET_PARAM.sub(lambda m: f"{m.group(1)}=[redacted]", value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


COMMIT = re.compile(r"^(yes|ok|okay|confirm|delete|remove|submit|save|approve|decline|deny|send|pay|agree|"
                    r"i agree|accept|cancel \w+|delete login|edit details|resend|reset|place order|amend|update|"
                    r"save changes|continue to submit)\b", re.I)


def commit_word(label):
    """The committing verb of a control label (Yes, Delete, Submit...), or None for navigation and fields."""
    clean = re.sub(r"\s*\((button|link|radio|checkbox|textbox|combobox)\)\s*$", "", (label or "").strip())
    match = COMMIT.match(clean)
    return match.group(1).lower() if match else None


def words_of(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 1 and w not in STOP_WORDS}


RECAP = """You narrate a QA browser test for the tester who is watching. Summarize the listed steps in one or two
short first-person sentences at a medium level (for example: "I logged into the appearance management system
and entered the TOTP code. Everything looks good here; I didn't notice any errors."). Group clicks into what
they accomplished; never list individual clicks or element ids, and never repeat typed secrets. Mention an
error only if error_words_on_page is non-empty or a check failed. Reflect the outcome if given
(pass/fail/blocked). Answer with JSON only: {"summary": "..."}"""


class SessionError(ValueError):
    """A command the session refuses; nothing was executed."""


class HeadedBrowser(Browser):
    """The standard observed-action browser, brought to the front of a visible window."""

    VIEWPORT = tuple(int(v) for v in setting("REVERIE_VIEWPORT", "1920x1080").lower().split("x"))

    def __init__(self, url, prepare=None):
        self.prepare = prepare  # Also called with each isolated context's id, so its downloads go to the same folder.
        super().__init__(url, prepare)
        self.activate()

    def configure_session(self):
        # Wide enough for desktop layouts and wide data grids; the observer only sees on-screen elements.
        width, height = self.VIEWPORT
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)

    def activate(self):
        cdp("Target.activateTarget", targetId=self.target)

    def observe(self, screenshot=True, screenshot_fallback=True):
        # Agent sessions see the whole page; off-screen controls come back flagged offscreen.
        policy = getattr(self, "dialog_answer", None) or setting("REVERIE_DIALOGS", "accept")
        answer = "false" if policy == "dismiss" else "true"
        prompt_text = json.dumps(getattr(self, "prompt_text", None))
        # Native dialogs would block CDP input; answer them per policy and record what they said.
        # The hooks read window.__layaDialogAnswer at call time, so the pilot can switch accept/dismiss.
        guard = (f"window.__jevFullPage = true; window.__layaDialogAnswer = {answer};"
                 f" window.__layaPromptText = {prompt_text};"
                 " if (!window.__layaDialogHook) { window.__layaDialogHook = true; window.__layaDialogs = [];"
                 " window.alert = m => { window.__layaDialogs.push({type: 'alert', message: String(m)}); };"
                 " window.confirm = m => { const a = window.__layaDialogAnswer !== false;"
                 " window.__layaDialogs.push({type: 'confirm', message: String(m), answer: a}); return a; };"
                 " window.prompt = (m, d) => { const a = window.__layaDialogAnswer !== false;"
                 " const t = a ? (window.__layaPromptText ?? d ?? '') : null;"
                 " window.__layaDialogs.push({type: 'prompt', message: String(m), answer: a, text: t}); return t; }; }")
        try:
            self.call("Runtime.evaluate", expression=guard, returnByValue=True)
        except (RuntimeError, TimeoutError):
            pass
        return super().observe(screenshot=screenshot, screenshot_fallback=screenshot_fallback)

    def tabs(self):
        targets = [t for t in cdp("Target.getTargets")["targetInfos"] if t["type"] == "page"]
        isolated = getattr(self, "isolated_contexts", None)
        if isolated is None:  # Sessions from before context tracking: the majority context is the signed-in one.
            from collections import Counter

            counts = Counter(t.get("browserContextId") for t in targets)
            main = counts.most_common(1)[0][0] if counts else None
            isolated = {t.get("browserContextId") for t in targets} - {main}
        return [
            {"id": t["targetId"], "url": t["url"], "title": t["title"], "current": t["targetId"] == self.target,
             "isolated": t.get("browserContextId") in isolated}
            for t in targets
        ]

    def open_tab(self, url, isolated=False):
        params = {"url": url}
        if isolated:
            params["browserContextId"] = cdp("Target.createBrowserContext")["browserContextId"]
            self.isolated_contexts = getattr(self, "isolated_contexts", set()) | {params["browserContextId"]}
            if self.prepare:
                self.prepare(params["browserContextId"])
        self.switch(cdp("Target.createTarget", **params)["targetId"])
        deadline = time.monotonic() + 10  # A new target starts on about:blank before its first navigation.
        while time.monotonic() < deadline:
            try:
                if self.evaluate("location.href") != "about:blank":
                    return
            except (StalePage, RuntimeError, TimeoutError):
                pass
            time.sleep(0.1)

    def switch(self, target_id):
        previous = self.session
        self.target = target_id
        self.session = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
        self.configure_session()
        self.after_input = None
        try:
            cdp("Target.detachFromTarget", sessionId=previous)
        except RuntimeError:
            pass
        self.activate()


def element(action):
    fields = ("id", "kind", "role", "label", "value", "hint", "checked", "selected", "expanded")
    return {k: action[k] for k in fields if action.get(k) not in (None, "")}


DECISION, ESCALATION = "decision", "escalation"
ESCALATED = {ESCALATION, "mercury"}  # "mercury" in runs and sessions from before the rename


def escalation_disabled():
    """The escalation layer (Mercury, the text model) is switched off with REVERIE_ESCALATION=off."""
    return setting("REVERIE_ESCALATION", "on").lower() in {"off", "0", "false", "no"}


class Session:
    def __init__(self, url, *, name="default", voice="auto", trail_dir=None, goal=None, engine=None,
                 download_dir=None, stream_interval=0.0):
        self.name = name
        self.lock = threading.RLock()
        self.narrator = Narrator(voice)
        self.prompt = None
        self.external_reply = None
        self.goal = goal
        # The fast decision layer under the stack: hosted Jev on OpenRouter (default), or local Laya.
        self.engine = engine or setting("REVERIE_DECISION_ENGINE", "").strip().lower() or None
        if self.engine not in {None, "laya", "jev"}:
            raise ValueError("REVERIE_DECISION_ENGINE must be laya or jev")
        if self.fast_engine() == "jev":
            from ..model import MissingKey, openrouter_key

            try:
                openrouter_key()  # Fail at start, with the fix, rather than on the first step.
            except MissingKey as error:
                raise SessionError(str(error)) from None
        self.agent = None
        self.history = []
        self.caption = ""
        self.status = "starting"
        self.frame = None
        self.checks = []
        self.test = None
        self.stream_interval = stream_interval
        self.hints = []
        self.fresh_hint = False
        self.pending = None
        self.checkpoints = []
        self.tab_list = []
        self.dialogs = []
        self.laya_min = float(setting("REVERIE_DECISION_MIN_CONFIDENCE", "0.6"))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.started = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.trail_dir = Path(trail_dir or runs_dir()) / f"{name}-{stamp}"
        self.trail_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir = Path(download_dir) if download_dir else downloads.default_for(self.trail_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.browser = HeadedBrowser(url, prepare=self.apply_download_dir)
        self.page = None
        self.observe(settle=True)
        self.status = "ready"
        self.log("start", url=url, voice=self.narrator.voice, goal=goal, engine=engine)
        if stream_interval > 0:
            # Headless runs have no window to watch; keep the watch page's frame fresh between actions.
            threading.Thread(target=self._stream, daemon=True).start()

    def apply_download_dir(self, context_id=None):
        """Send downloads to this session's folder, in the default context or one isolated context."""
        params = {"behavior": "allow", "downloadPath": str(self.download_dir), "eventsEnabled": False}
        if context_id:
            params["browserContextId"] = context_id
        try:
            cdp("Browser.setDownloadBehavior", **params)
        except RuntimeError:
            pass  # The profile preference still applies when a Chromium build rejects the command.

    def _stream(self):
        while not getattr(self, "closed", False):
            time.sleep(self.stream_interval)
            if self.lock.acquire(timeout=0.05):
                try:
                    self.capture()
                finally:
                    self.lock.release()

    # ---- trail -------------------------------------------------------------------------------------
    def log(self, event, **fields):
        record = scrub({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **fields})
        self.last_activity = time.monotonic()  # Heartbeat for the pilot watchdog.
        feed = self.__dict__.setdefault("feed", [])
        record_ref = len(feed) + 1  # Event refs (#N) are separate from element refs (e7).
        if event not in {"caption", "frame", "frame_before", "suggest"}:
            feed.append({**record, "seq": record_ref})
        with open(self.trail_dir / "trail.jsonl", "a") as trail:
            trail.write(json.dumps(record, default=str) + "\n")

    # ---- observation -------------------------------------------------------------------------------
    def settle(self, origin=None, timeout=15.0):
        """Wait for a navigation that an action may have started, then for the document to load."""
        deadline = time.monotonic() + timeout
        started = origin is None
        probe_until = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            try:
                state = self.browser.evaluate("[document.readyState, performance.timeOrigin]")
            except (StalePage, RuntimeError, TimeoutError):
                started = True
                time.sleep(0.1)
                continue
            if state and (state[1] != origin or state[0] != "complete"):
                started = True
            if started and state and state[0] == "complete":
                return
            if not started and time.monotonic() > probe_until:
                return
            time.sleep(0.05)

    def observe(self, settle=False):
        if settle:
            self.settle()
        deadline = time.monotonic() + 15
        while True:
            try:
                self.page = self.browser.observe(screenshot=False, screenshot_fallback=True)
                break
            except (StalePage, RuntimeError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        self.render()
        self.capture()
        try:
            self.open_tabs = self.browser.tabs()
        except (RuntimeError, TimeoutError):
            pass
        self.keep_frame()
        return self.summary()

    def save_frame(self, prefix):
        """Store the current frame beside the trail so the dashboard can replay a run. Best effort."""
        if not self.frame:
            return None
        if self.frame == getattr(self, "last_saved_frame", None):
            return self.last_saved_name  # Unchanged screen: reuse the frame so a replay shows only real changes.
        self.frame_seq = getattr(self, "frame_seq", 0) + 1
        name = f"{prefix}-{self.frame_seq:04d}.jpg"
        try:
            (self.trail_dir / "frames").mkdir(exist_ok=True)
            (self.trail_dir / "frames" / name).write_bytes(base64.b64decode(self.frame))
        except OSError:
            return None
        self.last_saved_frame, self.last_saved_name = self.frame, name
        self.__dict__.setdefault("step_frames", []).append(name)
        return name

    def keep_frame(self):
        done = len(self.history)
        if done <= getattr(self, "framed", 0):
            return
        self.framed = done
        name = self.save_frame(f"step-{done:03d}")
        if name:
            self.log("frame", step=done, file=name)

    def capture(self):
        """Keep one small frame for the watch page. Best effort; it never blocks a decision."""
        # Hide our caption box for the shot: frames show the page as a user sees it, so the UI review never
        # mistakes the agent's own overlay for broken layout. The target highlight stays visible.
        toggle = ("(v => { const r = document.getElementById('laya-agent-overlay');"
                  " const b = r && r.shadowRoot && r.shadowRoot.querySelector('.box'); if (b) b.style.visibility = v; })")
        try:
            self.browser.call("Runtime.evaluate", expression=f"{toggle}('hidden')", _response_timeout=2)
        except Exception:
            pass
        try:
            self.frame = self.browser.call("Page.captureScreenshot", format="jpeg", quality=55,
                                           _response_timeout=4)["data"]
        except Exception:
            pass
        finally:
            try:
                self.browser.call("Runtime.evaluate", expression=f"{toggle}('')", _response_timeout=2)
            except Exception:
                pass

    # ---- layered steering -----------------------------------------------------------------------------
    # Layer 1  decision engine    a typed decision on every step: jev (hosted, default) or laya (local).
    # Layer 2  escalation model   the text model (Mercury); overrules the decision engine when it is unsure,
    #                             repeating itself, stopping, or when the orchestrator has just given a hint.
    # Layer 3  orchestrator (the controlling agent, or the pilot): goals, hints, checks, plan marks, checkpoints.
    # Proposals and the trail name the layer by role ("decision", "escalation"); `decision_engine` says which
    # engine decided. Runs written before the rename used "laya", "jev" and "mercury"; readers map them.
    ENGINES = ("stack", "escalation", "laya", "jev")
    ENGINE_ALIASES = {"mercury": "escalation"}

    def set_goal(self, goal):
        with self.lock:
            self.goal = goal.strip()
            self.hints = []
            self.fresh_hint = False
            self.pending = None
            self.agent = None  # The decision engine re-plans once per goal.
            self.goal_start = len(self.history)
            self.avoid, self.allow_values, self.read_only = [], [], False
            self.log("goal", goal=self.goal)
            self.say(f"New goal: {self.goal}", speak=False)
            return {"goal": self.goal, **self.summary()}

    def add_hint(self, hint):
        self.hints.append(hint)
        self.fresh_hint = True  # The next step goes to the escalation model, which reads hints directly.
        self.agent = None  # The decision engine re-plans with the hints folded into its goal.
        self.log("hint", hint=hint)

    def laya_goal(self):
        if not self.hints:
            return self.goal
        return f"{self.goal}\nOrchestrator corrections (these override the goal): " + " ".join(self.hints[-4:])

    def _laya_candidates(self, decision, page):
        labels = {a["id"]: a for a in page["actions"]}
        ranked = sorted(decision.get("probabilities", {}).items(), key=lambda item: -item[1])[:3]
        return [{"id": ref, "probability": round(float(p), 3), "kind": labels.get(ref, {}).get("kind"),
                 "label": labels.get(ref, {}).get("label", ref)} for ref, p in ranked]

    def fast_engine(self):
        """The layer that makes each typed decision under the stack: jev (default, hosted) or laya (local)."""
        return getattr(self, "engine", None) or "jev"

    def _fast_propose(self, engine=None):
        engine = engine or self.fast_engine()
        agent = self.autonomous(self.laya_goal(), engine)
        if agent.state["status"] in {"done", "blocked", "aborted"}:
            self.agent = None
            agent = self.autonomous(self.laya_goal(), engine)
        agent.state["page"] = self.page
        agent.command("predict")
        decision = agent.state["decision"]
        if engine == "jev":
            self._jev_field_value(agent, decision)
        return decision

    def _jev_field_value(self, agent, decision):
        """Jev picks the field; the text helper supplies the value now, before anything runs, so the
        stated-value guard checks it and the proposal shows it. The agent then types exactly this value."""
        from ..model import field_context, field_text

        action = next((a for a in self.page["actions"] if a["id"] == decision["choice"]), None)
        if not action or action["kind"] != "fill" or decision.get("text") is not None:
            return
        try:
            text, helper = field_text(field_context(agent.state["goal"], action, self.page, agent.state["history"]))
        except ValueError as error:
            raise SessionError(f"Jev chose {action.get('label')!r}, but {error}") from error
        decision["text"] = text
        agent.state["text_calls"].append({**helper, "field": action["label"], "value": text})

    def stated_value(self, typed):
        """A value is stated when the goal/hints quote it, or it is a distinctive token (digit or @) they contain.
        Plain words ("click") are not values just because they appear in an instruction."""
        if typed in getattr(self, "allow_values", []):
            return True
        stated = self.goal + " " + " ".join(self.hints)
        quoted = [q.lower() for q in re.findall(r"'([^']+)'|\"([^\"]+)\"", stated) for q in q if q]
        if typed in quoted:
            return True
        # Unquoted tokens (an order number in "open order 8") count only when the whole typed value is that token.
        return bool(re.fullmatch(r"[\w.@+-]*[\d@][\w.@+-]*", typed)) and re.search(
            rf"(?<![\w@.+-]){re.escape(typed)}(?![\w@.+-])", stated.lower()) is not None

    def _escalation(self, decision):
        who = self.fast_engine().title()
        if self.fresh_hint and not escalation_disabled():
            # The escalation model reads hints directly. With it off, the decision engine already has the hint in its goal
            # (laya_goal), so a fresh hint alone must not block every step.
            return "orchestrator hint"
        if decision["choice"] in {"DONE", "BLOCKED"}:
            return f"{who} reported {decision['choice']}"
        if float(decision.get("confidence", 0.0)) < self.laya_min:
            return f"{who} confidence {float(decision.get('confidence', 0.0)):.2f} < {self.laya_min:.2f}"
        if decision["choice"] == "wait" and self.history and self.history[-1].get("kind") == "wait":
            return f"{who} keeps waiting"
        action = next((a for a in self.page["actions"] if a["id"] == decision["choice"]), None)
        typed = (decision.get("text") or "").strip().lower()
        if action and action["kind"] == "fill" and typed and not self.stated_value(typed):
            return f"{who} would type a value the goal does not state"
        last = self.history[-1] if self.history else {}
        if action and action["kind"] == "fill" and last.get("by") in ESCALATED and last.get("kind") == "fill" \
                and last.get("label") == action.get("label") and last.get("text") != decision.get("text"):
            return f"{who} would undo the escalation model's last entry"
        # A confident click that shares no words with the goal, while another visible element clearly does,
        # is the classic "confident but wrong" pick (a site logo instead of the named button).
        if action and action["kind"] == "click":
            goal_words = words_of(self.goal)
            picked = words_of(action.get("label", ""))
            if picked and not picked & goal_words and any(
                    len(words_of(a.get("label", "")) & goal_words) >= 2 for a in self.page["actions"]
                    if a["kind"] == "click" and a["id"] != action["id"]):
                return f"{who}'s pick does not match the goal wording"
        # A link that leaves the page after this goal typed into fields would throw the input away.
        if action and action["kind"] == "click" and action.get("role") == "link" and self.goal:
            typed_here = any(h.get("kind") in {"fill", "select"} for h in self.history[getattr(self, "goal_start", 0):])
            if typed_here and not words_of(action.get("label", "")) & words_of(self.goal + " " + " ".join(self.hints)):
                return f"{who} would leave the page and lose the typed input"
        # Loops hide behind waits (submit, wait, submit, wait) and behind pages that re-render identically.
        recent = [h for h in self.history[-5:] if h.get("kind") != "wait"]
        if action and sum(1 for h in recent if h.get("label") == action.get("label")
                          and h.get("kind") == action["kind"]) >= 2:
            return f"{who} is looping on the same action"
        # Alternating loops (type, click, type, click) repeat a pair without progress.
        if action and len(recent) >= 2 and recent[-2].get("label") == action.get("label") \
                and recent[-2].get("kind") == action["kind"] and recent[-2].get("text") == decision.get("text"):
            return f"{who} is repeating a two-step cycle"
        return None

    def _escalate(self, candidates=None, escalation=None):
        from .steer import escalation_choose

        plan = self.agent.state.get("goal_plan") if self.agent else None
        self.tab_list = [t for t in self.browser.tabs() if t["url"] != "about:blank"]
        tabs = [{"tab": f"TAB:{i}", "title": t["title"][:80], "url": t["url"][:160], "current": t["current"]}
                for i, t in enumerate(self.tab_list)]
        try:
            choice, meta = escalation_choose(self.goal, self.page, self.history, self.hints,
                                          candidates=candidates, escalation=escalation, plan=plan, tabs=tabs)
        except ValueError as error:
            raise SessionError(str(error)) from error
        self.fresh_hint = False
        return choice, meta.get("model")

    def suggest(self, engine="stack", hint=None, goal=None):
        """Propose exactly one next step. Nothing executes until accept."""
        engine = self.ENGINE_ALIASES.get(engine, engine)
        if engine not in self.ENGINES:
            raise SessionError(f"Engine must be one of {', '.join(self.ENGINES)}")
        with self.lock:
            if goal:
                self.set_goal(goal)
            if not self.goal:
                raise SessionError('Set a goal first (reverie goal "...")')
            if hint:
                self.add_hint(hint)
            self.observe()
            started = time.perf_counter()
            layer, model, escalation, decision_confidence, candidates = engine, engine, None, None, None
            decided = {}
            fast = self.fast_engine() if engine in {"stack", "escalation"} else engine
            if engine in {"stack", "laya", "jev"}:
                try:
                    decision = self._fast_propose(fast)
                    decision_confidence = round(float(decision.get("confidence", 0.0)), 3)
                    candidates = self._laya_candidates(decision, self.page)
                    choice = {"choice": decision["choice"], "text": decision.get("text"),
                              "confidence": decision_confidence,
                              "reason": f"{decision.get('operation', '')} {decision.get('target', '')}".strip()}
                    layer = DECISION
                    # What the fast decision cost, for the trail: model, its own latency, and USD (Jev reports it).
                    usage = decision.get("usage") or {}
                    decided = {"decision_model": decision.get("model"), "decision_ms": decision.get("latency_ms"),
                               "decision_cost": usage.get("cost")}
                    escalation = self._escalation(decision) if engine == "stack" else None
                    typed = (decision.get("text") or "").strip().lower()
                    if engine == "jev" and typed and not self.stated_value(typed):
                        # Without the escalation model behind it, Jev keeps the same rule: only stated values.
                        raise SessionError(f"Jev would type {decision['text']!r}, which the goal does not state. "
                                           "Nothing executed; state the value in quotes.")
                except (SessionError, StalePage, RuntimeError, ValueError) as error:
                    if isinstance(error, MissingKey):
                        raise SessionError(str(error)) from None  # A missing key is a setup error, not doubt.
                    if engine != "stack":
                        raise SessionError(f"{engine} could not decide: {error}") from error
                    escalation = f"{self.fast_engine().title()} unavailable: {error}"
            escalation_off = escalation_disabled()
            if escalation and escalation_off and engine == "stack" and choice.get("choice") == "DONE" \
                    and escalation.endswith("reported DONE"):
                # Nobody is behind the decision engine to confirm DONE; report it as DONE and let the caller check.
                escalation = None
            elif escalation and escalation_off and engine == "stack":
                # Escalation off: a doubtful step goes back to the pilot (which can act by sight) unexecuted.
                choice = {"choice": "BLOCKED", "text": None, "confidence": 0.0,
                          "reason": f"{self.fast_engine().title()} escalated ({escalation}) and the escalation model "
                                    "is off"}
                layer = DECISION
            elif engine == "escalation" and escalation_off:
                raise SessionError("The escalation model is off (REVERIE_ESCALATION=off)")
            elif engine == "escalation" or escalation:
                if self.agent and self.agent.state.get("decision"):
                    self.agent.state["decision"] = None  # The escalation model overrules the unexecuted pick.
                choice, model = self._escalate(candidates, escalation)
                layer = ESCALATION
                typed = (choice.get("text") or "").strip().lower()
                if typed and typed not in (self.goal + " " + " ".join(self.hints)).lower() \
                        and typed not in getattr(self, "allow_values", []):
                    # The escalation model has the same rule: it types only values the goal or hints state.
                    raise SessionError(f"The escalation model would type {choice['text']!r}, which the goal does not "
                                       "state. "
                                       "Nothing executed; state the value in quotes.")
            action = next((a for a in self.page["actions"] if a["id"] == choice["choice"]), None)
            avoided = action and any(a in action.get("label", "").lower() for a in getattr(self, "avoid", []))
            if avoided and layer != ESCALATION:
                # The decision engine picked a control the pilot fenced off: let the escalation model choose.
                choice, model = self._escalate(candidates, f"{fast.title()} chose a control the pilot said to avoid")
                layer = ESCALATION
                action = next((a for a in self.page["actions"] if a["id"] == choice["choice"]), None)
                avoided = action and any(a in action.get("label", "").lower() for a in getattr(self, "avoid", []))
            word = commit_word((action or {}).get("label")) if action and action["kind"] == "click" \
                and action.get("role") not in {"radio", "checkbox", "option", "tab"} else None
            asked = (self.goal + " " + " ".join(self.hints)).lower()
            if word and word not in asked and not getattr(self, "allow_commit", False):
                # Committing clicks (Yes, Delete, Submit, Save...) run only when the intent names them.
                raise SessionError(f"The stack wanted to click {action.get('label')!r}, which commits a change the "
                                   "intent did not ask for. Nothing executed; name it in the intent to allow it.")
            if action and getattr(self, "read_only", False) and action["kind"] in {"fill", "select"}:
                raise SessionError(f"This intent is read-only; the stack wanted to change {action.get('label')!r}. "
                                   "Nothing executed.")
            if avoided:
                raise SessionError(f"The stack chose {action.get('label')!r}, which the pilot said to avoid. "
                                   "Nothing executed.")
            label = self.phrase(action, choice["text"]) if action else choice["choice"]
            if str(choice["choice"]).startswith("TAB:"):
                tab = self.tab_list[int(choice["choice"][4:])]
                label = f"Switching to the tab '{tab['title'][:60]}'"
            self.pending = {**choice, "engine": engine, "layer": layer, "model": model, "ref": choice["choice"],
                            "label": label, "escalation": escalation, "decision_engine": fast,
                            "decision_confidence": decision_confidence,
                            "fingerprint": self.page["fingerprint"], **decided,
                            "latency_ms": round((time.perf_counter() - started) * 1000)}
            self.log("suggest", **{k: v for k, v in self.pending.items() if k != "fingerprint"})
            who = "The escalation model" if layer == ESCALATION else fast.title()
            spoken = f"{who} suggests: {label}"
            if escalation and layer == ESCALATION and engine == "stack":
                spoken = f"Escalated, {escalation}. {spoken}"
            self.say(spoken, highlight=(action or {}).get("rect"), speak=False)
            if choice["choice"] == "ADMIN":
                if getattr(self, "pilot_thread", None) is threading.current_thread():
                    # Under a pilot run, the pilot decides whether admin work is really needed.
                    self.pending = {**self.pending, "ref": "BLOCKED", "choice": "BLOCKED"}
                else:
                    self.checkpoint(choice.get("reason") or "The decision layers asked for an administrative action",
                                    source=layer)
            return {"proposal": self.public_pending(), **self.summary()}

    def public_pending(self):
        return {k: v for k, v in self.pending.items() if k != "fingerprint"} if self.pending else None

    def accept(self):
        with self.lock:
            proposal = self.pending
            if not proposal:
                raise SessionError("No pending suggestion; run suggest first")
            self.pending = None
            if str(proposal["ref"]).startswith("TAB:"):
                tab = self.tab_list[int(proposal["ref"][4:])]
                result = self.switch(tab["id"])
                self.history.append({"step": len(self.history) + 1, "kind": "tab", "label": tab["title"][:80],
                                     "url": tab["url"], "by": proposal["layer"]})
                self.log("act", **self.history[-1])
                return result
            if proposal["ref"] in {"DONE", "BLOCKED", "ADMIN"}:
                who = proposal.get("decision_engine") if proposal["layer"] == DECISION else "the escalation model"
                self.say(f"{str(who).capitalize()} reports {proposal['ref']}: {proposal.get('reason', '')}", speak=False)
                return {"status": proposal["ref"].lower(), **self.summary()}
            if proposal["layer"] == DECISION and proposal["ref"] == "wait":
                # A wait changes nothing; run it unguarded and keep the decision engine's history in step.
                self.agent.state["decision"] = None
                result = self.act("wait", narration="Waiting for the page to update", by=proposal["layer"])
                self.agent.state["history"].append({
                    "step": len(self.agent.state["history"]) + 1, "action": "Wait for the page to update",
                    "kind": "wait", "choice": "wait", "text": None, "page_changed": None,
                    "url": self.page["url"], "by": proposal["layer"]})
                return result
            target = next((a for a in self.page["actions"] if a["id"] == proposal["ref"]), None)
            if proposal["layer"] == DECISION and target and target.get("offscreen"):
                self.agent.state["decision"] = None
                result = self.act(proposal["ref"], text=proposal.get("text"), narration=proposal["label"],
                                  by=proposal["layer"])
                self.agent.state["history"].append({
                    "step": len(self.agent.state["history"]) + 1, "action": result.get("label"),
                    "kind": result.get("kind"), "choice": proposal["ref"], "text": proposal.get("text"),
                    "page_changed": result.get("page_changed"), "url": result.get("url_after"),
                    "by": proposal["layer"]})
                return result
            if proposal["layer"] == DECISION:
                agent = self.agent
                origin = self.browser.evaluate("performance.timeOrigin")
                try:
                    agent.command("act", {"fingerprint": proposal["fingerprint"]})
                except (StalePage, ValueError) as error:
                    self.observe()
                    raise SessionError(f"{error} Nothing was executed; suggest again.") from error
                last = agent.state["history"][-1]
                step = {"step": len(self.history) + 1, "label": last["action"], "kind": last["kind"],
                        "text": last.get("text"), "url": last["url"], "by": proposal["layer"],
                        "decision_engine": proposal.get("decision_engine"),
                        "confidence": proposal.get("decision_confidence")}
                self.history.append(step)
                self.log("act", **step)
                self.settle(origin)
                before = proposal["fingerprint"]
                self.observe()
                step["page_changed"] = self.page["fingerprint"] != before
                return {**step, **self.summary()}
            if self.page["fingerprint"] != proposal["fingerprint"]:
                self.observe()
                raise SessionError("The page changed since the suggestion. Nothing was executed; suggest again.")
            result = self.act(proposal["ref"], text=proposal.get("text"), narration=proposal["label"],
                              by=proposal["layer"], escalation=proposal.get("escalation"))
            if self.agent:
                # Keep the decision engine's history aligned so it sees what the escalation model executed.
                self.agent.state["history"].append({
                    "step": len(self.agent.state["history"]) + 1, "action": result.get("label"),
                    "kind": result.get("kind"), "choice": proposal["ref"], "text": proposal.get("text"),
                    "page_changed": result.get("page_changed"), "url": result.get("url_after"),
                    "by": ESCALATION})
            return result

    def reject(self, hint=None):
        with self.lock:
            dropped, self.pending = self.pending, None
            if self.agent and self.agent.state.get("decision"):
                self.agent.state["decision"] = None
            if hint:
                self.add_hint(hint)
                self.say(f"Steering: {hint}", speak=False)
            self.log("reject", dropped=(dropped or {}).get("ref"), hint=hint)
            return {"rejected": (dropped or {}).get("label"), "hints": self.hints, **self.summary()}

    CEILING = int(setting("REVERIE_STEP_CEILING", "25"))
    STALL = 3

    def auto(self, engine="stack", max_steps=None, min_confidence=0.55, until_text=None, until_url=None):
        """Fast loop. Pauses for the orchestrator on low escalation-model confidence, DONE/BLOCKED/ADMIN, an
        until-condition, or a refused step. A pending suggestion stays available after a pause."""
        steps, layers = [], {DECISION: 0, ESCALATION: 0}
        reason = "max_steps"
        stale = 0
        still = 0  # Consecutive executed actions that changed nothing on the page.
        # Keep going while the page responds; a caller's max_steps is a floor, the ceiling is the safety net.
        for _ in range(max(max_steps or 0, self.CEILING)):
            if self.pending_checkpoint():
                reason = "admin"
                break
            try:
                proposal = self.suggest(engine)["proposal"]
            except SessionError as error:
                reason = f"refused: {error}"
                break
            if proposal["ref"] in {"DONE", "BLOCKED", "ADMIN"}:
                reason = proposal["ref"].lower()
                break
            if proposal["layer"] == ESCALATION and proposal["confidence"] < min_confidence:
                reason = "low_confidence"
                break
            try:
                self.accept()
            except SessionError as error:
                # Nothing executed. A page that moved under the decision is worth one fresh proposal.
                if "Nothing was executed" in str(error) and stale < 2:
                    stale += 1
                    continue
                reason = f"refused: {error}"
                break
            stale = 0
            layers[proposal["layer"]] += 1
            last = self.history[-1] if self.history else {}
            still = still + 1 if last.get("page_changed") is False and last.get("kind") != "wait" else 0
            if still >= self.STALL:
                steps.append(f"{proposal['layer']}: {proposal['label']}")
                reason = f"stalled: {self.STALL} actions changed nothing"
                break
            recent = [h for h in self.history[-4:] if h.get("kind") != "wait"]
            if len(recent) >= 3 and len({(h.get("kind"), h.get("label")) for h in recent[-3:]}) == 1:
                reason = "loop: the same action ran three times"
                steps.append(f"{proposal['layer']}: {proposal['label']}")
                break
            steps.append(f"{proposal['layer']}: {proposal['label']}")
            body = self.page["text"].lower()
            if until_text and until_text.lower() in body:
                reason = "until_text"
                break
            if until_url and until_url in self.page["url"]:
                reason = "until_url"
                break
        if reason == "admin":
            self.status = "awaiting-admin"
        elif reason in {"low_confidence", "blocked"} or reason.startswith("refused"):
            self.status = "needs-steer"
        else:
            self.status = "ready"
        self.say(f"Paused: {reason.replace('_', ' ')} after {len(steps)} steps", speak=False)
        self.log("auto", engine=engine, steps=steps, layers=layers, reason=reason)
        result = {"paused": reason, "steps": steps, "layers": layers, **self.summary(), "ran": steps}
        if self.pending:
            result["proposal"] = self.public_pending()
        return result

    def do(self, intent, hints=(), max_steps=6, until_text=None, until_url=None, min_confidence=0.55,
           avoid=(), allow_values=(), read_only=False):
        """The default way to drive a test step: state the intent; the decision engine acts and the escalation model
        steps in when needed.
        Direct act/fill commands stay available for when the stack pauses."""
        with self.lock:
            # A stop condition that already holds would end the intent after one action; ignore it.
            page = self.page or {}
            if until_url and until_url in page.get("url", ""):
                until_url = None
            if until_text and until_text.lower() in page.get("text", "").lower():
                until_text = None
            self.set_goal(intent)
            # Pilot-owned guards for this intent. The fixed floor (observed ids, stated values, no secrets) stays.
            self.avoid = [a.lower() for a in avoid or ()]
            self.read_only = bool(read_only)
            self.allow_values = [v.lower() for v in allow_values or ()]
            from .pilot import lessons_for

            host = (self.page or {}).get("url", "").split("/")[2:3]
            for lesson in lessons_for(set(host)).get(host[0] if host else "", [])[-4:]:
                self.hints.append(f"Site lesson: {lesson}")
            for hint in hints or ():
                self.add_hint(hint)
        return self.auto("stack", max_steps, min_confidence, until_text, until_url)

    # ---- admin checkpoints: the session defers terminal work to the orchestrator ---------------------
    # The daemon never runs shell commands. A checkpoint records what is needed; the orchestrator runs it
    # from its own terminal (reverie exec / resolve) and the result is written back into the session.
    def checkpoint(self, title, command=None, step=None, source="orchestrator"):
        with self.lock:
            if source not in {"orchestrator", "plan"}:
                command = None  # Model- or page-originated requests describe a need; they never carry a command.
            cp = {"id": uuid.uuid4().hex[:6], "title": title.strip()[:300], "command": command, "step": step,
                  "source": source, "status": "pending", "created": time.strftime("%H:%M:%S"), "result": None}
            self.checkpoints.append(cp)
            self.status = "awaiting-admin"
            self.log("checkpoint", **cp)
            self.say(f"Waiting for the orchestrator: {cp['title']}", speak=False)
            return {"checkpoint": cp, **self.summary()}

    def pending_checkpoint(self):
        return next((c for c in self.checkpoints if c["status"] == "pending"), None)

    def resolve_checkpoint(self, checkpoint_id, status, exit_code=None, output=None, note=""):
        with self.lock:
            cp = next((c for c in self.checkpoints if c["id"] == checkpoint_id), None)
            if not cp:
                raise SessionError(f"Unknown checkpoint {checkpoint_id}")
            if cp["status"] != "pending":
                raise SessionError(f"Checkpoint {checkpoint_id} is already {cp['status']}")
            if status not in {"done", "failed", "skipped"}:
                raise SessionError("Status must be done, failed, or skipped")
            cp.update(status=status, resolved=time.strftime("%H:%M:%S"),
                      result={"exit_code": exit_code, "output": (output or "")[-2000:], "note": note})
            self.log("resolve", id=checkpoint_id, status=status, exit_code=exit_code, note=note)
            if not self.pending_checkpoint():
                self.status = "ready"
            for step in (self.test or {}).get("steps", []):
                step.pop("progress", None)  # New facts from the orchestrator restart the no-progress count.
            self.say(f"Checkpoint {status}: {cp['title']}" + (f". {note}" if note else ""), speak=False)
            if cp["step"] and self.test:
                self.mark(cp["step"], "pass" if status == "done" else "fail" if status == "failed" else "skipped",
                          note or (f"exit {exit_code}" if exit_code is not None else ""))
            return {"checkpoint": cp, **self.summary()}

    def wait(self, timeout=900.0):
        """Block until the session needs the orchestrator: an admin checkpoint, a steer, or a person's prompt."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                cp = self.pending_checkpoint()
                if cp:
                    return {"needs": "admin", "checkpoint": cp, **self.summary()}
                runner = getattr(self, "pilot_thread", None)
                if self.status == "needs-steer" and not (runner and runner.is_alive()):
                    return {"needs": "steer", "proposal": self.public_pending(), **self.summary()}
                if self.prompt:
                    return {"needs": "person", **self.summary()}
                runner = getattr(self, "pilot_thread", None)
                if runner is not None and not runner.is_alive() and not getattr(self, "pilot_reported", False):
                    self.pilot_reported = True
                    return {"needs": "review", "pilot_result": getattr(self, "pilot_result", None),
                            "test": self.test, **self.summary()}
            time.sleep(0.3)
        return {"needs": "nothing", **self.summary()}

    def watch_state(self):
        goal_plan = self.agent.state.get("goal_plan") if self.agent else None
        counts = {}
        for h in self.history:
            who = "orchestrator" if h.get("by", "agent") == "agent" else h["by"]
            counts[who] = counts.get(who, 0) + 1
        return {**self.summary(), "name": self.name, "frame": self.frame, "history": scrub(self.history[-60:]),
                "checks": self.checks[-20:], "said": self.narrator.spoken[-40:], "test": self.test,
                "goal": self.goal, "goal_plan": goal_plan, "hints": self.hints[-6:],
                "pending": self.public_pending(), "checkpoints": self.checkpoints[-10:], "layers": counts,
                "tabs": scrub([{k: t[k] for k in ("title", "url", "current")} for t in getattr(self, "open_tabs", [])])}

    # ---- spoken recaps ---------------------------------------------------------------------------------
    ERROR_WORDS = ("application error", "exception", "err-", "an error occurred", "not authorized", "403", "500")

    def recap(self, outcome=None, note=""):
        """One or two first-person sentences about the steps since the last recap, spoken aloud."""
        start = getattr(self, "recap_index", 0)
        steps = [{k: h.get(k) for k in ("kind", "label", "by")} | ({"text": "[typed]"} if h.get("text") else {})
                 for h in self.history[start:]]
        self.recap_index = len(self.history)
        body = (self.page or {}).get("text", "").lower()
        errors = [w for w in self.ERROR_WORDS if w in body]
        context = {"steps": steps[-25:], "outcome": outcome, "orchestrator_note": note,
                   "page_title": (self.page or {}).get("title"), "error_words_on_page": errors,
                   "checks": self.checks[-3:]}
        summary = ""
        if getattr(self, "recap_model", True):
            try:
                from ..model import chat_json

                output, _ = chat_json(RECAP, context)
                summary = str(output.get("summary", "")).strip()[:400]
            except Exception:
                summary = ""
        if not summary:
            summary = (f"I finished {len(steps)} steps"
                       + (f" and the step {'passed' if outcome == 'pass' else outcome}" if outcome else "")
                       + (". I noticed an error on the page." if errors else ". I didn't notice any errors."))
        self.say(summary)
        self.log("recap", summary=summary, steps=len(steps), errors=errors)
        return {"recap": summary, **self.summary()}

    # ---- test plan progress ------------------------------------------------------------------------
    STEP_STATES = ("pending", "running", "pass", "fail", "blocked", "skipped")

    def tidy_tabs(self, keep_current=True):
        """Close every tab except the current one (blank start-up tabs, and tabs an earlier test opened)."""
        closed = 0
        for tab in self.browser.tabs():
            if tab["current"] and keep_current:
                continue
            try:
                cdp("Target.closeTarget", targetId=tab["id"])
                closed += 1
            except RuntimeError:
                pass
        if closed:
            self.log("tidy_tabs", closed=closed)
        return closed

    def plan(self, title, steps, source=None):
        runner = getattr(self, "pilot_thread", None)
        if runner is not None and runner.is_alive() and runner is not threading.current_thread():
            raise SessionError("A pilot is running on the current plan; `pilot stop` first")
        if not steps:
            raise SessionError("A test plan needs at least one step")
        items = []
        for i, text in enumerate(steps):
            admin = text.lower().startswith("[admin]")
            command = re.search(r"`([^`]+)`", text) if admin else None
            clean = re.sub(r"^\[admin\]\s*", "", text, flags=re.I)
            clean = re.sub(r"`[^`]*`", "", clean).strip() if admin else clean.replace("`", "")
            items.append({"n": i + 1, "title": clean, "status": "pending", "note": "", "admin": admin,
                          "command": command.group(1) if command else None})
        self.test = {"title": title or "Test", "source": source, "result": "running", "steps": items}
        self.tidy_tabs()  # Each test starts with only its own working tab.
        self.test_home_tab = self.browser.target
        self.log("plan", title=self.test["title"], steps=steps, source=source)
        self.write_run_summary()
        self.say(f"Starting {self.test['title']}: {len(steps)} steps")
        return {"test": self.test}

    def mark(self, n, status, note="", recap=True):
        if not self.test:
            raise SessionError("Load a test plan first (reverie plan or reverie spec)")
        if status not in self.STEP_STATES:
            raise SessionError(f"Status must be one of {', '.join(self.STEP_STATES)}")
        steps = self.test["steps"]
        if not 1 <= n <= len(steps):
            raise SessionError(f"Step must be 1-{len(steps)}")
        step = steps[n - 1]
        step.update(status=status, note=note)
        if status == "pending":
            # A reset step is retested from scratch: its earlier findings no longer apply.
            if step.pop("findings", None):
                self.log("findings_cleared", step=n, note=note)
            step.pop("ui_flags", None)
        if status == "running":
            step["checks_from"] = len(self.checks)
            self.step_frames = []
        if status == "running" and step.get("admin"):
            self.checkpoint(step["title"], command=step.get("command"), step=n, source="plan")
        states = [s["status"] for s in steps]
        if "fail" in states:
            self.test["result"] = "fail"
        elif "blocked" in states and all(s not in {"pending", "running"} for s in states):
            self.test["result"] = "blocked"
        elif all(s in {"pass", "skipped"} for s in states):
            self.test["result"] = "pass"
        else:
            self.test["result"] = "running"
        frame = self.save_frame("mark") if status != "running" else None
        if status in {"pass", "fail", "blocked"}:
            self.review_ui(step)
        self.log("mark", step=n, status=status, note=note, result=self.test["result"], frame=frame,
                 ui=step.get("ui"))
        self.write_run_summary()
        words = {"running": "Step", "pass": "Passed step", "fail": "Failed step", "blocked": "Blocked at step",
                 "skipped": "Skipped step", "pending": "Reset step"}[status]
        self.say(f"{words} {n}: {step['title']}" + (f". {note}" if note and status != "running" else ""),
                 speak=False)
        if status in {"pass", "fail", "blocked"} and recap:
            self.recap(outcome=status, note=note)
        if self.test["result"] in {"pass", "fail", "blocked"} and status != "running":
            self.say(f"{self.test['title']} result: {self.test['result']}", speak=False)
        return {"test": self.test}

    def review_ui(self, step):
        """Multimodal UI review of the frames this step produced; findings stay on the step and in the trail."""
        from .pilot import ui_review

        files = list(dict.fromkeys(getattr(self, "step_frames", [])))
        if len(files) > 5:  # Spread the sample over the step, always keeping the final screen.
            stride = len(files) / 4
            files = [files[int(i * stride)] for i in range(4)] + [files[-1]]
        review = ui_review(self, step, files)
        if review is None:
            return None
        step["ui"] = review
        self.log("ui_review", step=step["n"], **review)
        worst = next((s for s in ("high", "medium", "low") if any(i["severity"] == s for i in review["issues"])), None)
        self.say(f"UI review, step {step['n']}: " + (f"{len(review['issues'])} issue(s), worst {worst}. "
                 if worst else "no problems. ") + review["summary"], speak=False)
        return review

    def write_run_summary(self, ended=None):
        """Refresh run.json beside the trail so history listings need not parse every trail."""
        test = self.test or {}
        steps = test.get("steps") or []
        write_run_summary(self.trail_dir, {
            "spec_id": spec_id(test.get("source"), test.get("title")),
            "title": test.get("title"),
            "source": test.get("source"),
            "session": self.name,
            "started": getattr(self, "started", None),
            "ended": ended,
            "verdict": test.get("result") if test else None,
            "steps_done": sum(1 for st in steps if st["status"] not in {"pending", "running"}),
            "steps_total": len(steps),
        })

    def summary(self):
        page = self.page or {}
        return {
            "status": self.status,
            "url": scrub(page.get("url")),
            "title": page.get("title"),
            "elements": sum(1 for a in page.get("actions", []) if a["kind"] in {"click", "fill", "select"}),
            "steps": len(self.history),
            "prompt": self.prompt,
            "caption": self.caption,
            "trail": str(self.trail_dir / "trail.jsonl"),
            "download_dir": str(self.download_dir),
        }

    def elements(self, grep=None, limit=80):
        items = [element(a) for a in (self.page or {}).get("actions", [])]
        if grep:
            needles = [n.strip().lower() for n in re.split(r"\\?\|", grep) if n.strip()]  # "a|b" or "a\|b"
            items = [e for e in items if any(n in json.dumps(e).lower() for n in needles)]
        return items[:limit]

    def text(self, limit=4000):
        return (self.page or {}).get("text", "")[:limit]

    # ---- overlay and narration ---------------------------------------------------------------------
    def render(self, highlight=None):
        payload = {"caption": self.caption, "status": self.status, "highlight": highlight, "prompt": self.prompt}
        try:
            response = self.browser.call(
                "Runtime.evaluate", expression=f"{OVERLAY}({json.dumps(payload)})", returnByValue=True
            )
            return response.get("result", {}).get("value")
        except (RuntimeError, TimeoutError):
            return None  # A navigating page drops the overlay; the next observation restores it.

    def say(self, text, highlight=None, wait=False, speak=True):
        """Caption every line; speak only milestones unless REVERIE_NARRATION=verbose."""
        self.caption = text
        self.render(highlight)
        if not speak and setting("REVERIE_NARRATION", "summary") != "verbose":
            self.log("caption", text=text)
            if highlight:
                self.capture()
            return
        if highlight:
            self.capture()  # Show the highlighted target on the watch page before the action runs.
        self.narrator.say(text, wait=wait)
        self.log("say", text=text)

    # ---- resolution --------------------------------------------------------------------------------
    def drain_dialogs(self):
        try:
            found = self.browser.evaluate("(() => { const d = window.__layaDialogs || []; window.__layaDialogs = [];"
                                          " return d; })()") or []
        except (StalePage, RuntimeError):
            found = []
        if not isinstance(found, list):
            found = []
        for dialog in found:
            self.dialogs.append(dialog)
            self.log("dialog", **dialog)
            self.say(f"Browser {dialog['type']}: {dialog['message'][:160]}", speak=False)
        return found

    def reveal(self, action):
        """Scroll an off-screen target into view and return the same element's fresh on-screen action."""
        node = action.get("node")
        if type(node) is not int:
            raise SessionError("That element has no stable identity to scroll to")
        self.browser.call("Runtime.evaluate", returnByValue=True, expression=(
            f"window.__jevFast?.nodes.get({node})?.scrollIntoView({{block: 'center', inline: 'center'}})"))
        time.sleep(0.3)
        self.observe()
        same = [a for a in self.page["actions"] if a.get("node") == node and a["kind"] == action["kind"]
                and a.get("value") == action.get("value")]
        if len(same) != 1 or same[0].get("offscreen"):
            raise SessionError("The element could not be brought into view. Nothing was executed.")
        self.log("reveal", node=node, label=action.get("label"))
        return same[0]

    def find(self, ref=None, label=None, kind=None, option=None, hint=None, value=None, scrolls=12):
        """Resolve a target; when named by label/hint and not on screen, scroll down to look for it."""
        try:
            return self.resolve(ref, label, kind, option, hint, value)
        except SessionError as error:
            if ref or not scrolls or "found 0" not in str(error):
                raise
        try:  # Scan from the top so a target above the current position is not missed.
            self.browser.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.2)
            self.observe()
            return self.resolve(ref, label, kind, option, hint, value)
        except (SessionError, StalePage):
            pass
        for _ in range(scrolls):
            scroll = next((a for a in self.page["actions"] if a["id"] == "scroll_down"), None)
            if not scroll:
                break
            self.browser.act(scroll, self.page)
            time.sleep(0.25)
            self.observe()
            try:
                return self.resolve(ref, label, kind, option, hint, value)
            except SessionError as error:
                if "found 0" not in str(error):
                    raise
        return self.resolve(ref, label, kind, option, hint, value)

    def resolve(self, ref=None, label=None, kind=None, option=None, hint=None, value=None):
        actions = (self.page or {}).get("actions", [])
        ref = ref.lstrip("@") if ref else ref  # agent-browser style refs: @e5 == e5
        if hint is not None or value is not None:
            # Stable targeting: ids shift when a page re-renders; a field's hint (name/id) and value do not.
            matches = [a for a in actions if (hint is None or a.get("hint", "").lower() == hint.lower())
                       and (value is None or str(a.get("value", "")) == value)]
        elif ref:
            matches = [a for a in actions if a["id"] == ref]
        elif label:
            needle = label.lower()
            exact = [a for a in actions if a.get("label", "").lower() == needle]
            matches = exact or [a for a in actions if needle in a.get("label", "").lower()]
        else:
            raise SessionError("Name an element id (e7) or --label")
        if kind:
            matches = [a for a in matches if a["kind"] == kind]
        if option is not None:
            node = {a.get("node") for a in matches}
            wanted = option.lower()
            matches = [
                a for a in actions
                if a["kind"] == "select" and a.get("node") in node
                and (" ".join(a["label"].split(" → ")[-1].split()).lower() == wanted
                     or str(a.get("value", "")).lower() == wanted)
            ]
        if len(matches) != 1:
            names = ", ".join(f"{a['id']}:{a['kind']}:{a.get('label', '')}" for a in matches[:8])
            raise SessionError(f"Expected exactly one matching element, found {len(matches)}. {names}".strip())
        return matches[0]

    # ---- actions -----------------------------------------------------------------------------------
    def phrase(self, action, text=None, secret=False):
        label = action.get("label", "").split(" → ")[0] or action.get("role", "element")
        if action["kind"] == "fill":
            return f"Typing {'a secret value' if secret else repr(text)} into {label}"
        if action["kind"] == "select":
            return f"Choosing {action['label'].split(' → ')[-1]} in {label}"
        if action["kind"] == "scroll":
            return action["label"]
        if action["kind"] == "wait":
            return "Waiting for the page to update"
        return f"Clicking {label}"

    def act(self, ref=None, label=None, kind=None, text=None, option=None, narration=None, redact=False,
            by="orchestrator", escalation=None, hint=None, value=None):
        with self.lock:
            if option is not None:
                kind = None
            action = self.find(ref, label, kind, option, hint, value)
            if action.get("offscreen"):
                action = self.reveal(action)
            if action["kind"] == "wait":
                # Waiting mutates nothing, so it needs no freshness guard; an animating menu must not refuse it.
                self.say(narration or "Waiting for the page to update", speak=False)
                time.sleep(0.6)
                step = {"step": len(self.history) + 1, "id": "wait", "kind": "wait", "label": action["label"],
                        "text": None, "url": self.page["url"], "by": by}
                self.history.append(step)
                self.log("act", **step)
                self.observe()
                return {**step, **self.summary()}
            if action["kind"] == "fill" and text is None:
                raise SessionError(f"{action['id']} is a text field; pass the text to type")
            if action["kind"] != "fill" and text is not None:
                raise SessionError(f"{action['id']} is a {action['kind']} target; it does not take text")
            page = self.page
            self.status = "acting"
            self.say(narration or self.phrase(action, text, secret=redact), highlight=action.get("rect"), speak=False)
            before_frame = self.save_frame(f"step-{len(self.history) + 1:03d}-target")
            if before_frame:
                self.log("frame_before", step=len(self.history) + 1, file=before_frame)
            origin = self.browser.evaluate("performance.timeOrigin")
            tabs_before = {t["id"] for t in self.browser.tabs()}
            try:
                self.browser.act(action, page, text=text)
            except StalePage as error:
                self.status = "ready"
                self.observe()
                raise SessionError(f"{error} Nothing was executed; observe and choose again.") from error
            # Record execution before observing the result. A failed observation must not erase the action.
            step = {"step": len(self.history) + 1, "id": action["id"], "kind": action["kind"],
                    "label": action.get("label"), "text": "[redacted]" if redact and text else text,
                    "url": page["url"], "by": by, "escalation": escalation,
                    "hint": (action.get("hint") or "").split(" · ")[0] or None, "value": action.get("value")}
            self.history.append(step)
            self.log("act", **step)
            dialogs = self.drain_dialogs()
            if dialogs:
                step["dialogs"] = dialogs
            self.settle(origin)
            self.status = "ready"
            before = page["fingerprint"]
            # Follow a link that opened a new tab (target=_blank, window.open); the old tab stays open.
            time.sleep(0.3)
            opened = [t for t in self.browser.tabs() if t["id"] not in tabs_before and t["url"] != "about:blank"]
            if opened:
                self.browser.switch(opened[-1]["id"])
                self.log("follow_tab", target=opened[-1]["id"], url=opened[-1]["url"])
                self.settle()
            self.observe()
            step["page_changed"] = self.page["fingerprint"] != before or bool(opened)
            step["url_after"] = self.page["url"]
            return {**step, **self.summary()}

    def hover(self, ref=None, label=None):
        """Move the pointer over an observed element (opens hover menus). No click, no input."""
        with self.lock:
            action = self.resolve(ref, label, "click")
            rect = action.get("rect")
            if not rect:
                raise SessionError(f"{action['id']} has no position to hover")
            self.say(f"Hovering over {action.get('label', 'element')}", highlight=rect, speak=False)
            x, y = rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2
            self.browser.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
            time.sleep(0.4)
            step = {"step": len(self.history) + 1, "id": action["id"], "kind": "hover",
                    "label": action.get("label"), "text": None, "url": self.page["url"], "by": "orchestrator"}
            self.history.append(step)
            self.log("act", **step)
            self.observe()
            return {**step, **self.summary()}

    def cmd_dialog(self, accept=True, text=None):
        """Answer a native alert/confirm/prompt that is blocking the page."""
        params = {"accept": bool(accept)}
        if text is not None:
            params["promptText"] = text
        self.browser.call("Page.handleJavaScriptDialog", **params)
        self.log("dialog", accept=bool(accept))
        self.say(f"{'Accepted' if accept else 'Dismissed'} the browser dialog", speak=False)
        time.sleep(0.3)
        self.settle()
        self.status = "ready"
        return self.observe()

    def secret(self, value, field=None):
        with self.lock:
            target = self.browser.evaluate(f"{SECRET_TARGET}({json.dumps(field or '')})")
            if not target or target.get("count") != 1 or "x" not in target:
                count = (target or {}).get("count", 0)
                raise SessionError(f"Expected one visible, uncovered password field, found {count}")
            self.status = "acting"
            self.say(f"Entering the {field or 'password'} secret", highlight=target["rect"], speak=False)
            x, y = target["x"], target["y"]
            self.browser.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
            self.browser.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
            self.browser.call("Input.dispatchKeyEvent", type="keyDown", key="a", code="KeyA", modifiers=2,
                              commands=["selectAll"])
            self.browser.call("Input.dispatchKeyEvent", type="keyUp", key="a", code="KeyA", modifiers=2)
            self.browser.call("Input.insertText", text=value)
            step = {"step": len(self.history) + 1, "kind": "secret", "label": field or "password",
                    "text": "[redacted]", "url": self.page["url"], "by": "orchestrator"}
            self.history.append(step)
            self.log("act", **step)
            self.status = "ready"
            self.observe()
            return {**step, **self.summary()}

    def press(self, key):
        if key not in KEYS:
            raise SessionError(f"Key must be one of {', '.join(KEYS)}")
        with self.lock:
            self.status = "acting"
            self.say(f"Pressing {key}", speak=False)
            origin = self.browser.evaluate("performance.timeOrigin")
            spec = KEYS[key]
            self.browser.call("Input.dispatchKeyEvent", type="keyDown", **spec)
            self.browser.call("Input.dispatchKeyEvent", type="keyUp", **{k: v for k, v in spec.items() if k != "text"})
            step = {"step": len(self.history) + 1, "kind": "key", "label": key, "url": self.page["url"], "by": "orchestrator"}
            self.history.append(step)
            self.log("act", **step)
            self.settle(origin)
            self.status = "ready"
            self.observe()
            return {**step, **self.summary()}

    def goto(self, url):
        if not url.startswith(("http://", "https://")):
            raise SessionError("Only http and https URLs")
        with self.lock:
            self.say(f"Opening {url}", speak=False)
            origin = self.browser.evaluate("performance.timeOrigin")
            self.browser.call("Page.navigate", url=url)
            self.settle(origin)
            result = self.observe()
            self.log("goto", url=url, frame=self.save_frame("nav"))
            return result

    def tabs(self):
        return self.browser.tabs()

    def back(self):
        """The browser's Back button: return to the previous page in this tab's history."""
        with self.lock:
            before = self.page["url"]
            origin = self.browser.evaluate("performance.timeOrigin")
            self.browser.evaluate("history.back()")
            self.settle(origin)
            result = self.observe()
            self.log("back", url=self.page["url"], previous=before, frame=self.save_frame("nav"))
            self.say("Going back to the previous page", speak=False)
            return result

    def cmd_dialogs(self, answer="accept", text=None):
        """Set how native confirm/prompt dialogs are answered: accept or dismiss, and the text an accepted
        prompt returns (default: the prompt's own default value)."""
        if answer not in {"accept", "dismiss"}:
            raise SessionError("answer must be accept or dismiss")
        self.browser.dialog_answer = answer
        self.browser.prompt_text = text
        self.observe()
        self.log("dialog_policy", answer=answer, text=text)
        return {"dialogs": answer, "prompt_text": text, **self.summary()}

    def cmd_tidy_tabs(self):
        with self.lock:
            return {"closed": self.tidy_tabs(), **self.summary()}

    CONFIG_KEYS = {"TEXT_MODEL_REASONING", "TEXT_MODEL", "REVERIE_PILOT_MODEL", "TEXT_MODEL_EFFORT", "REVERIE_ESCALATION",
                   "REVERIE_STALL_SECONDS", "REVERIE_UI_REVIEW", "REVERIE_PILOT_PROVIDER",
                   "REVERIE_PILOT_BASE_URL"}

    def cmd_config(self, key, value):
        """Change a model or harness setting in this running daemon (no secrets, whitelisted keys only)."""
        from ..settings import current_name

        key = current_name(key)  # an old LAYA_AGENT_* name sets its REVERIE_* setting
        if key not in self.CONFIG_KEYS:
            raise SessionError(f"key must be one of {', '.join(sorted(self.CONFIG_KEYS))}")
        os.environ[key] = str(value)
        self.log("config", key=key, value=str(value))
        return {"config": {key: value}, **self.summary()}

    def cmd_back(self):
        return self.back()

    def open_tab(self, url, isolated=False):
        """Open a URL in a new tab of this session (any origin). Isolated tabs get a fresh cookie jar, so a
        link can be tested signed out while the signed-in tab stays open."""
        if not url.startswith(("http://", "https://")):
            raise SessionError("Only http and https URLs")
        with self.lock:
            self.browser.open_tab(url, isolated)
            self.say(f"Opening {'a signed-out tab' if isolated else 'a new tab'} for {url.split('/')[2]}", speak=False)
            result = self.observe(settle=True)
            self.log("open_tab", url=url, isolated=isolated, frame=self.save_frame("nav"))
            return result

    def close_tab(self):
        with self.lock:
            others = [t for t in self.browser.tabs() if not t["current"] and t["url"] != "about:blank"]
            if not others:
                raise SessionError("This is the only tab; stop the session instead")
            closing = self.browser.target
            self.browser.switch(others[-1]["id"])
            cdp("Target.closeTarget", targetId=closing)
            result = self.observe(settle=True)
            self.log("close_tab", target=closing, url=self.page["url"], frame=self.save_frame("nav"))
            return result

    def switch(self, target_id=None):
        with self.lock:
            tabs = self.browser.tabs()
            if not target_id:
                others = [t for t in tabs if not t["current"] and t["url"] != "about:blank"]
                if not others:
                    raise SessionError("No other tab is open")
                target_id = others[-1]["id"]
            if target_id not in {t["id"] for t in tabs}:
                raise SessionError("Unknown tab id")
            self.browser.switch(target_id)
            result = self.observe(settle=True)
            self.log("switch", target=target_id, url=self.page["url"], title=self.page.get("title"),
                     frame=self.save_frame("nav"))
            return result

    def check(self, text=None, absent=None, url=None, link=None, href=None):
        with self.lock:
            self.observe()
            # Field values (including read-only inputs) are page content too; the text walker skips them.
            try:
                values = self.browser.evaluate(
                    "[...document.querySelectorAll('input:not([type=password]):not([type=hidden]),textarea,select')]"
                    ".map(e => e.tagName === 'SELECT' ? e.selectedOptions[0]?.text || '' : e.value).join('\\n')") or ""
            except (StalePage, RuntimeError):
                values = ""
            values = values if isinstance(values, str) else ""
            body, current = (self.page["text"] + "\n" + values).lower(), self.page["url"]
            results = []
            if text is not None:
                results.append({"check": f"text contains {text!r}", "pass": text.lower() in body})
            if absent is not None:
                results.append({"check": f"text lacks {absent!r}", "pass": absent.lower() not in body})
            if url is not None:
                results.append({"check": f"url contains {url!r}", "pass": url in current})
            if link is not None:
                # Link targets are read in memory only; the check records whether they match, never the href.
                try:
                    hrefs = self.browser.evaluate(
                        "(t => [...document.querySelectorAll('a[href]')].filter(a => a.innerText.trim().toLowerCase()"
                        f".includes(t)).map(a => a.href))({json.dumps(link.lower())})") or []
                except (StalePage, RuntimeError):
                    hrefs = []
                ok = bool(hrefs) and all((href or "") in h for h in hrefs)
                results.append({"check": f"link {link!r} exists" + (f" and its target contains {href!r}" if href else ""),
                                "pass": ok})
            if not results:
                raise SessionError("Pass --text, --absent, --url, or --link")
            passed = all(r["pass"] for r in results)
            self.checks.append({"results": results, "passed": passed, "url": current})
            self.log("check", results=results, passed=passed, url=current, frame=self.save_frame("check"))
            self.say(("Check passed: " if passed else "Check failed: ") + "; ".join(r["check"] for r in results),
                     speak=False)
            return {"passed": passed, "results": results, "url": current}

    def screenshot(self, path=None):
        with self.lock:
            data = self.browser.call("Page.captureScreenshot", format="png")["data"]
            target = Path(path) if path else self.trail_dir / f"{time.strftime('%H%M%S')}-{len(self.history):03d}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(data))
            self.log("screenshot", path=str(target))
            return {"path": str(target)}

    # ---- waiting for a person ----------------------------------------------------------------------
    def ask(self, question, choices=None, allow_text=True, timeout=900.0):
        """Show a prompt in the headed window and block until someone answers there or via `reply`."""
        with self.lock:
            prompt_id = uuid.uuid4().hex[:8]
            self.prompt = {"id": prompt_id, "question": question, "choices": choices or [], "allow_text": allow_text}
            self.external_reply = None
            self.status = "waiting"
            self.say(question)
            self.log("ask", id=prompt_id, question=question, choices=choices)
        deadline = time.monotonic() + timeout
        answer = None
        while time.monotonic() < deadline:
            with self.lock:
                reply = self.external_reply or self.render()
                if reply and reply.get("id") == prompt_id:
                    answer = {"choice": reply.get("choice"), "text": reply.get("text") or ""}
                    break
            time.sleep(0.25)
        with self.lock:
            self.prompt = None
            self.status = "ready"
            self.render()
            self.log("answer", id=prompt_id, answer=answer, timed_out=answer is None)
            if answer is None:
                raise SessionError("No answer before the timeout")
            self.say(f"Got it: {answer['choice']}" + (f", {answer['text']}" if answer["text"] else ""), speak=False)
            return answer

    def reply(self, choice="Continue", text=""):
        with self.lock:
            if not self.prompt:
                raise SessionError("Nothing is waiting for input")
            self.external_reply = {"id": self.prompt["id"], "choice": choice, "text": text}
            return {"answered": self.prompt["id"]}

    # ---- autonomous decision-engine steps ---------------------------------------------------------------
    def autonomous(self, goal=None, engine=None):
        from ..agent import Agent

        goal = goal or self.goal
        engine = engine or self.fast_engine()
        if not goal:
            raise SessionError("Autonomous steps need a goal (--goal)")
        if self.agent is None or self.agent.state["goal"] != goal or self.agent.state["decision_engine"] != engine:
            try:
                self.agent = Agent(self.page["url"], goal, decision_engine=engine, browser=self.browser)
            except RuntimeError as error:
                raise SessionError(
                    f"The {engine} decision engine is unavailable: {error} "
                    "Drive the session with observe/act instead, or configure laya.cpp or OPENROUTER_API_KEY."
                ) from error
            # A per-command engine (suggest/auto/step --engine) must not change the session's engine,
            # which picks the fast layer for do and the pilot.
        return self.agent

    def step(self, goal=None, engine=None, confirm=False):
        with self.lock:
            if goal:
                self.goal = goal
            agent = self.autonomous(goal, engine)
            state = agent.state
            if state["status"] in {"done", "blocked", "aborted"}:
                return {"status": state["status"], **self.summary()}
            try:
                agent.command("predict")
            except StalePage:
                state["page"] = self.browser.observe(screenshot=False)
                agent.command("predict")
            decision = state["decision"]
            choice = decision["choice"]
            target = next((a for a in state["page"]["actions"] if a["id"] == choice), None)
            words = choice if target is None else self.phrase(target, decision.get("text"))
            who = state["decision_engine"].title()
            self.say(f"{who} chose: {words}", highlight=(target or {}).get("rect"), speak=False)
        if confirm:
            answer = self.ask(f"{who} wants to: {words}", ["Approve", "Skip", "Stop"], allow_text=False)
            if answer["choice"] != "Approve":
                with self.lock:
                    state["decision"] = None
                    state["status"] = "aborted" if answer["choice"] == "Stop" else "ready"
                    return {"status": state["status"], "skipped": words, **self.summary()}
        with self.lock:
            origin = self.browser.evaluate("performance.timeOrigin")
            try:
                agent.command("act", {"fingerprint": state["page"]["fingerprint"]})
            except StalePage as error:
                state["page"] = self.browser.observe(screenshot=False)
                state["status"] = "ready"
                return {"status": "stale", "detail": str(error), **self.summary()}
            if state["history"]:
                last = state["history"][-1]
                self.history.append({"step": len(self.history) + 1, "label": last["action"], "kind": last["kind"],
                                     "text": last.get("text"), "url": last["url"], "by": DECISION,
                                     "decision_engine": state["decision_engine"]})
                self.log("act", **self.history[-1])
            self.settle(origin)
            self.observe()
            calls = [{k: c.get(k) for k in ("model", "latency_ms", "field")} for c in state.get("text_calls", [])]
            if calls and not getattr(self, "_plan_logged", False):
                self._plan_logged = True
                self.log("plan", plan=state.get("goal_plan"), text_calls=calls)
            return {"status": state["status"], "decision": words, "plan": state.get("goal_plan"), **self.summary()}

    def run(self, goal=None, engine=None, max_steps=20, confirm=False):
        results = []
        for _ in range(max_steps):
            result = self.step(goal, engine, confirm)
            results.append(result.get("decision") or result.get("skipped") or result["status"])
            if result["status"] in {"done", "blocked", "aborted"}:
                break
        final = self.agent.state["status"] if self.agent else "ready"
        self.say(f"Run finished: {final}", speak=False)
        return {"status": final, "steps": results, **self.summary()}

    # ---- pilot: a smarter model runs the plan; the orchestrator stays high level ------------------------
    def note(self, text):
        self.notes = getattr(self, "notes", [])
        self.notes.append(text.strip()[:500])
        self.log("note", text=self.notes[-1])
        return {"notes": self.notes, **self.summary()}

    PILOT_STUCK = int(setting("REVERIE_PILOT_STUCK", "12"))

    def pilot(self, max_ops=150, through=None):
        """Run the loaded plan from its first open step. Pauses for admin work, a question, a failed or
        blocked step, a pilot error, or the operation budget."""
        from . import pilot as pilot_module

        if not self.test:
            raise SessionError("Load a test plan first (reverie plan or reverie spec)")
        self.notes = getattr(self, "notes", [])
        log, reason = [], "budget"
        self.status = "piloting"
        self.pilot_stop_requested = False
        for _ in range(max_ops):
            if self.pilot_stop_requested:
                reason = "stopped by the orchestrator"
                break
            if self.pending_checkpoint():
                reason = "admin"
                break
            step = next((s for s in self.test["steps"] if s["status"] in {"running", "pending"}), None)
            if not step:
                reason = "plan complete"
                # Close tabs this test opened (isolated sign-out tabs, followed links); keep its working tab.
                home = getattr(self, "test_home_tab", None)
                if home and home in {t["id"] for t in self.browser.tabs()}:
                    if self.browser.target != home:
                        self.browser.switch(home)
                    self.tidy_tabs()
                for cp in self.checkpoints:
                    if cp["status"] == "pending":
                        cp.update(status="skipped", resolved=time.strftime("%H:%M:%S"),
                                  result={"note": "closed: the plan completed"})
                        self.log("resolve", id=cp["id"], status="skipped", note="closed: the plan completed")
                break
            if through and step["n"] > through:
                reason = f"reached step {step['n']}"
                break
            if step["status"] == "pending":
                self.mark(step["n"], "running")  # An [admin] step raises its checkpoint here.
                if step.get("admin"):
                    reason = "admin"
                    break
            with self.lock:
                self.observe()
            try:
                op, meta = pilot_module.choose(self, step, log)
            except (ValueError, RuntimeError) as error:  # Provider errors (HTTP 4xx/5xx) pause, never crash.
                reason = f"pilot error: {error}"
                break
            self.log("pilot", step=step["n"], model=meta.get("model"), latency_ms=meta.get("latency_ms"), **op)
            self.say(f"Pilot: {op['reason'] or op['op']}", speak=False)
            if op.get("ui"):
                # A user-eye observation from this turn's screenshot; kept on the step and in the trail.
                flags = step.setdefault("ui_flags", [])
                if op["ui"] not in flags:
                    flags.append(op["ui"])
                    self.log("ui_flag", step=step["n"], what=op["ui"], frame=self.save_frame("ui"))
            outcome = self._pilot_run(op, step)
            if op.get("say") and not outcome.startswith("refused"):
                self.say(op["say"])  # The pilot's bottom-line progress update is the only routine speech.
            log.append({"step": step["n"], **{k: v for k, v in op.items() if k != "reason"}, "outcome": outcome})
            self.log("pilot_outcome", step=step["n"], op=op["op"], outcome=outcome)
            if op["op"] in {"admin", "ask"}:
                reason = op["op"]
                break
            if op["op"] == "mark" and op["status"] == "blocked" and outcome.startswith("marked"):
                reason = f"step {step['n']} blocked"
                break  # A failed step does not stop the run: the remaining steps still gather evidence.
            # No progress: the pilot keeps operating on one step without a new passing check.
            progress = step.setdefault("progress", {"ops": 0, "checks": len(self.checks)})
            acted = (outcome.startswith("stack ran:") and not outcome.startswith("stack ran: nothing")) \
                or outcome.startswith(("pilot ", "opened", "switched", "went back", "now at"))
            if op["op"] == "act":
                # The same act again (same element, same text) is a loop, not a long form fill.
                same = [e for e in log[:-1][-6:] if e.get("step") == step["n"] and e.get("op") == "act"
                        and e.get("ref") == op.get("ref") and (e.get("text") or "") == (op.get("text") or "")]
                acted = acted and not same
            if len([c for c in self.checks[progress["checks"]:] if c["passed"]]):
                progress.update(ops=0, checks=len(self.checks))
            elif acted:
                progress["ops"] = max(0, progress["ops"] - 1)  # Real actions are progress (a long form fill).
            else:
                progress["ops"] += 1
            if progress["ops"] >= self.PILOT_STUCK:
                self.checkpoint(f"The pilot made no progress on step {step['n']} after {progress['ops']} operations. "
                                f"Last: {op['op']} {(op.get('intent') or op.get('what') or '')[:120]} -> {outcome[:160]}",
                                source="pilot")
                reason = "stuck"
                break
        self.status = "awaiting-admin" if self.pending_checkpoint() else "ready"
        self.say(f"Pilot paused: {reason}", speak=False)
        return {"paused": reason, "pilot_log": log[-12:], "test": self.test, **self.summary()}

    def _pilot_run(self, op, step):
        kind = op["op"]
        try:
            if kind == "do":
                result = self.do(op["intent"], op["hints"], op.get("max_steps", 6), op.get("until_text"),
                                 op.get("until_url"), avoid=op.get("avoid", ()), allow_values=op.get("allow_values", ()),
                                 read_only=op.get("read_only", False))
                proposal = result.get("proposal") or {}
                pending, why = proposal.get("label"), proposal.get("reason")
                ran = "; ".join(result.get("ran") or []) or "nothing"
                return (f"stack ran: {ran}. Paused: {result['paused']}; now at {result['url']}"
                        + (f"; unexecuted proposal: {pending}" if pending else "")
                        + (f"; stack says: {why}" if why else ""))
            if kind == "act":
                result = self.act(op["ref"], text=op.get("text"), by="pilot")
                return f"pilot {result['kind']} {result.get('label')}; now at {result.get('url_after')}"
            if kind == "check":
                result = self.check(op.get("text"), op.get("absent"), op.get("url"), op.get("link"), op.get("href"))
                return ("passed: " if result["passed"] else "FAILED: ") + "; ".join(
                    f"{r['check']} {'ok' if r['pass'] else 'no'}" for r in result["results"])
            if kind == "tab_new":
                self.open_tab(op["url"], op["isolated"])
                return f"opened {'isolated ' if op['isolated'] else ''}tab at {self.page['url']}"
            if kind == "dialogs":
                self.browser.dialog_answer = op["answer"]
                self.browser.prompt_text = op.get("text")
                self.observe()  # Push the new answer into the page now.
                self.log("dialog_policy", answer=op["answer"], text=op.get("text"))
                entered = f", prompts get {op['text']!r}" if op.get("text") is not None else ""
                return f"native confirm dialogs will now be answered: {op['answer']}{entered}"
            if kind == "back":
                self.back()
                return f"went back; now at {self.page['url']}"
            if kind == "tab":
                from .pilot import tab_list

                self.switch(tab_list(self)[op["index"]]["id"])
                return f"switched to {self.page['url']}"
            if kind == "goto":
                self.goto(op["url"])
                return f"now at {self.page['url']}"
            if kind == "mark":
                checks = self.checks[step.get("checks_from", 0):]
                if op["status"] == "pass" and not (checks and checks[-1]["passed"]):
                    return "refused: run a check that proves this step before marking pass"
                serious = [f for f in step.get("findings", []) if f.get("severity") in {"high", "medium"}]
                if op["status"] == "pass" and serious:
                    return ("refused: this step has findings (" + "; ".join(f["what"] for f in serious)[:200]
                            + "); mark it fail with the finding in the note")
                self.mark(step["n"], op["status"], f"Pilot: {op['note']}", recap=not op.get("say"))
                return f"marked {op['status']}"
            if kind == "finding":
                finding = {k: op.get(k) for k in ("severity", "what", "expected", "actual", "workaround")}
                step.setdefault("findings", []).append(finding)
                self.log("finding", step=step["n"], frame=self.save_frame("finding"), **finding)
                self.say(f"Finding on step {step['n']}: {op['what']}", speak=False)
                return f"finding recorded ({op['severity']}); mark this step fail when its work is done, then continue"
            if kind == "lesson":
                from .pilot import add_lesson

                added = add_lesson(op["host"], op["lesson"], (self.test or {}).get("title"))
                return "lesson saved to the playbook" if added else "lesson already in the playbook"
            if kind == "admin":
                cp = self.checkpoint(op["need"], source="pilot")["checkpoint"]
                return f"checkpoint {cp['id']} raised"
            if kind == "ask":
                cp = self.checkpoint(f"Question: {op['question']}", source="pilot")["checkpoint"]
                return f"question {cp['id']} raised"
        except SessionError as error:
            return f"refused: {error}"
        return "unknown operation"

    def cmd_audio(self, bluetooth=None, wake_seconds=None):
        """Show or change narration audio settings for this session."""
        if bluetooth is not None:
            self.narrator.bluetooth = bool(bluetooth)
        if wake_seconds is not None:
            self.narrator.wake_seconds = max(0.0, min(5.0, float(wake_seconds)))
        self.log("audio", bluetooth=self.narrator.bluetooth, wake_seconds=self.narrator.wake_seconds)
        return {"bluetooth_audio": self.narrator.bluetooth, "wake_seconds": self.narrator.wake_seconds,
                "voice": self.narrator.voice, **self.summary()}

    def cmd_reload_modules(self):
        """Reload modules the server's own reload does not cover (text model client, pilot)."""
        import importlib

        from .. import browser as browser_module
        from .. import model
        from . import narrator, pilot

        importlib.reload(browser_module)  # Module functions (browser_operation) update in place.

        importlib.reload(model)
        importlib.reload(pilot)
        importlib.reload(narrator)
        old = self.narrator
        self.narrator.__class__ = narrator.Narrator
        for attr, value in (("bluetooth", setting("REVERIE_BLUETOOTH_AUDIO", "0").lower()
                             in {"1", "true", "on", "yes"}), ("wake_seconds", 1.2), ("wake_after_idle", 4.0),
                            ("last_audio", 0.0)):
            if not hasattr(old, attr):
                setattr(old, attr, value)
        return {"reloaded": ["model", "pilot", "narrator"], **self.summary()}

    def cmd_pilot(self, max_ops=150, through=None, detach=True):
        """Start the pilot in the background and return at once; monitor with events/wait/progress."""
        if not detach:
            return self.pilot(max_ops, through)
        runner = getattr(self, "pilot_thread", None)
        if runner and runner.is_alive():
            raise SessionError("The pilot is already running; use `pilot stop` or watch it with `events --follow`")

        def work():
            try:
                self.pilot_result = self.pilot(max_ops, through)
            except Exception as error:  # Recorded for the orchestrator; the daemon stays up.
                self.pilot_result = {"paused": f"pilot crashed: {type(error).__name__}: {error}"}
                self.status = "needs-steer"
                self.log("error", error=repr(error))
            self.log("pilot_end", paused=self.pilot_result.get("paused"))

        self.pilot_result = None
        self.pilot_reported = False
        self.pilot_thread = threading.Thread(target=work, daemon=True)
        self.last_activity = time.monotonic()
        self.pilot_thread.start()
        threading.Thread(target=self._watchdog, args=(self.pilot_thread,), daemon=True).start()
        return {"started": True, "from_ref": len(self.__dict__.get("feed", [])), **self.summary()}

    STALL_SECONDS = int(setting("REVERIE_STALL_SECONDS", "240"))

    def _watchdog(self, runner):
        """Heartbeat check: a running pilot that logs nothing for STALL_SECONDS is stalled (a hung model or
        browser call). Record it, raise a checkpoint, and ask the pilot to stop at its next boundary."""
        while runner.is_alive():
            time.sleep(15)
            idle = time.monotonic() - getattr(self, "last_activity", time.monotonic())
            if idle < self.STALL_SECONDS or self.pending_checkpoint():
                continue
            self.log("stalled", idle_seconds=round(idle))
            self.pilot_stop_requested = True
            self.checkpoint(f"The pilot has shown no activity for {round(idle)} s (hung model or browser call). "
                            "It will stop at its next step; inspect `progress`, then `pilot` to resume.",
                            source="pilot")
            runner.join(self.STALL_SECONDS)

    def cmd_pilot_stop(self, timeout=120):
        """Ask the pilot to stop after its current operation, and wait until it has."""
        self.pilot_stop_requested = True
        runner = getattr(self, "pilot_thread", None)
        if runner is not None:
            runner.join(timeout)
        return {"stopped": not (runner and runner.is_alive()), **self.summary()}

    def cmd_events(self, since=None, limit=200):
        feed = self.__dict__.get("feed", [])
        if since is None:  # No cursor: show the latest events, not the first ones.
            since = max(0, len(feed) - 40)
        runner = getattr(self, "pilot_thread", None)
        return {"events": feed[since:since + limit], "next": min(len(feed), since + limit),
                "pilot": "running" if runner and runner.is_alive() else "idle",
                "pilot_result": getattr(self, "pilot_result", None), "test": self.test, **self.summary()}

    def cmd_note(self, text):
        return self.note(text)

    # Commands reachable through the server's generic `cmd_<name>` path, so a running daemon gains them on reload.
    def cmd_open_tab(self, url, isolated=False):
        return self.open_tab(url, isolated)

    def cmd_close_tab(self):
        return self.close_tab()

    def cmd_do(self, intent, hints=None, max_steps=6, until_text=None, until_url=None, min_confidence=0.55):
        return self.do(intent, hints or [], max_steps, until_text, until_url, min_confidence)

    def close(self):
        self.closed = True
        self.log("stop", steps=len(self.history), test=self.test)
        self.write_run_summary(ended=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self.narrator.drain(5)
        self.narrator.close()
        try:
            self.browser.close()
        except Exception:
            pass
