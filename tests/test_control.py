"""Offline contracts for agent control. No browser, no speech, no paid APIs."""

import json
import threading
from unittest.mock import Mock

import pytest

from reverie.browser import StalePage, fingerprint
from reverie.control import cli, narrator
from reverie.control.session import OVERLAY, Session, SessionError


def page():
    state = {
        "url": "https://example.test/login",
        "title": "Login",
        "text": "Sign in\nWelcome back",
        "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Username", "role": "textbox", "value": "", "node": 1,
             "rect": {"x": 1, "y": 2, "w": 3, "h": 4}},
            {"id": "e2", "kind": "click", "label": "Open Username", "role": "textbox", "value": "", "node": 1},
            {"id": "e3", "kind": "click", "label": "Submit", "role": "button", "value": "", "node": 2},
            {"id": "e4", "kind": "select", "label": "State → California", "value": "CA", "node": 3,
             "role": "combobox"},
            {"id": "e5", "kind": "select", "label": "State → Texas", "value": "TX", "node": 3, "role": "combobox"},
            {"id": "wait", "kind": "wait", "label": "Wait for the page to update"},
        ],
    }
    state["fingerprint"] = fingerprint(state)
    return state


def session(tmp_path):
    s = Session.__new__(Session)
    s.lock = threading.RLock()
    s.page = page()
    s.history = []
    s.prompt = None
    s.external_reply = None
    s.caption = ""
    s.status = "ready"
    s.checks = []
    s.frame = None
    s.test = None
    s.name = "test"
    s.checkpoints = []
    s.recap_model = False  # tests never call the paid text model
    s.dialogs = []
    s.tab_list = []
    s.fresh_hint = False
    s.laya_min = 0.6
    s.trail_dir = tmp_path
    s.download_dir = tmp_path / "downloads"
    s.narrator = Mock(voice="off")
    s.browser = Mock()
    s.browser.evaluate.return_value = 1.0
    s.browser.tabs.return_value = []
    s.browser.call.return_value = {"result": {"value": None}}
    s.observe = Mock(side_effect=lambda settle=False: s.summary())
    s.settle = Mock()
    return s


def test_resolve_by_id_label_and_option(tmp_path):
    s = session(tmp_path)
    assert s.resolve("e3")["label"] == "Submit"
    assert s.resolve(label="username", kind="fill")["id"] == "e1"
    assert s.resolve(label="State", option="Texas")["value"] == "TX"
    assert s.resolve(label="State", option="CA")["id"] == "e4"


def test_ambiguous_or_missing_targets_are_refused(tmp_path):
    s = session(tmp_path)
    with pytest.raises(SessionError, match="found 2"):
        s.resolve(label="user")
    with pytest.raises(SessionError, match="found 0"):
        s.resolve("e99")
    with pytest.raises(SessionError, match="element id"):
        s.resolve()


def test_act_types_into_an_observed_field_and_logs_before_observing(tmp_path):
    s = session(tmp_path)
    result = s.act("e1", text="validator")
    s.browser.act.assert_called_once()
    action, observed = s.browser.act.call_args.args
    assert action["id"] == "e1" and observed is not None
    assert s.browser.act.call_args.kwargs == {"text": "validator"}
    assert result["kind"] == "fill" and s.history[0]["text"] == "validator"
    trail = [json.loads(line) for line in (tmp_path / "trail.jsonl").read_text().splitlines()]
    assert [r["event"] for r in trail] == ["caption", "act"]
    assert "Typing 'validator' into Username" in trail[0]["text"]


def test_text_rules_are_enforced_before_execution(tmp_path):
    s = session(tmp_path)
    with pytest.raises(SessionError, match="text field"):
        s.act("e1")
    with pytest.raises(SessionError, match="does not take text"):
        s.act("e3", text="x")
    s.browser.act.assert_not_called()


def test_stale_page_is_never_retried(tmp_path):
    s = session(tmp_path)
    s.browser.act.side_effect = StalePage("Page changed")
    with pytest.raises(SessionError, match="Nothing was executed"):
        s.act("e3")
    assert s.browser.act.call_count == 1 and s.history == []


def test_secret_is_redacted_everywhere(tmp_path):
    s = session(tmp_path)
    s.browser.evaluate.return_value = {"count": 1, "x": 5, "y": 6, "rect": {"x": 1, "y": 1, "w": 9, "h": 9}}
    s.secret("hunter2", field="Password")
    inserted = [c for c in s.browser.call.call_args_list if c.args[0] == "Input.insertText"]
    assert inserted[0].kwargs == {"text": "hunter2"}
    assert "hunter2" not in (tmp_path / "trail.jsonl").read_text()
    assert "hunter2" not in json.dumps(s.history)
    assert all("hunter2" not in str(c) for c in s.narrator.say.call_args_list)


def test_secret_requires_exactly_one_visible_password_field(tmp_path):
    s = session(tmp_path)
    s.browser.evaluate.return_value = {"count": 2}
    with pytest.raises(SessionError, match="found 2"):
        s.secret("x")


def test_check_reports_each_assertion(tmp_path):
    s = session(tmp_path)
    result = s.check(text="welcome", absent="error", url="/login")
    assert result["passed"] and len(result["results"]) == 3
    assert not s.check(text="Dashboard")["passed"]


def test_reply_answers_the_pending_prompt(tmp_path):
    s = session(tmp_path)
    with pytest.raises(SessionError):
        s.reply()
    answers = {}
    worker = threading.Thread(target=lambda: answers.update(s.ask("Proceed?", ["Yes", "No"], timeout=5)))
    worker.start()
    while not s.prompt:
        pass
    s.reply("No", "not yet")
    worker.join(5)
    assert answers == {"choice": "No", "text": "not yet"} and s.prompt is None


def test_overlay_is_hidden_from_the_snapshot():
    assert "aria-hidden" in OVERLAY and "attachShadow" in OVERLAY
    assert "document.documentElement" in OVERLAY and "pointer-events: none" in OVERLAY


def test_voice_resolution(monkeypatch):
    monkeypatch.setattr(narrator.shutil, "which", lambda name: None)
    monkeypatch.setattr(narrator, "local_ready", lambda provider="kokoro": False)
    assert narrator.resolve_voice("auto") == "off"
    with pytest.raises(ValueError):
        narrator.resolve_voice("robot")
    quiet = narrator.Narrator("off")
    quiet.say("  hello   world ")
    assert quiet.spoken == ["hello world"]


def test_cli_without_session_exits_4(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--session", "missing", "status"])
    assert exit_info.value.code == 4


def test_auto_voice_prefers_kokoro_then_falls_back(monkeypatch):
    monkeypatch.setattr(narrator.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setenv("SPEECH_PROVIDER", "kokoro")
    monkeypatch.setattr(narrator, "local_ready", lambda provider="kokoro": True)
    assert narrator.resolve_voice("auto") == "kokoro"
    monkeypatch.setenv("SPEECH_PROVIDER", "kitten")
    assert narrator.resolve_voice("auto") == "kitten"
    monkeypatch.setenv("SPEECH_PROVIDER", "kokoro")
    monkeypatch.setattr(narrator, "local_ready", lambda provider="kokoro": False)
    monkeypatch.delenv("FISH_AUDIO_API_TOKEN", raising=False)
    assert narrator.resolve_voice("auto") == "espeak"


def test_speech_provider_switch(monkeypatch):
    from reverie import kokoro, speech

    monkeypatch.setenv("SPEECH_PROVIDER", "kokoro")
    monkeypatch.setattr(kokoro, "synthesize", lambda text, voice: b"RIFF")
    assert speech.synthesize("hi", "af_heart") == (b"RIFF", "audio/wav")
    assert speech.settings()["label"] == "Kokoro"
    monkeypatch.setenv("SPEECH_PROVIDER", "fish")
    assert speech.settings()["label"] == "Fish Audio"
    monkeypatch.setenv("SPEECH_PROVIDER", "robot")
    with pytest.raises(RuntimeError, match="SPEECH_PROVIDER"):
        speech.provider()


def test_kokoro_request_shape(monkeypatch):
    from reverie import kokoro

    sent = {}

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers, json):
            sent.update(url=url, json=json)
            return Mock(status_code=200, content=b"RIFFwav")

    monkeypatch.setenv("KOKORO_BASE_URL", "http://127.0.0.1:9999/")
    monkeypatch.setattr(kokoro.httpx, "Client", Client)
    assert kokoro.synthesize("Clicking Submit", "am_adam") == b"RIFFwav"
    assert sent == {"url": "http://127.0.0.1:9999/v1/audio/speech",
                    "json": {"input": "Clicking Submit", "voice": "kokoro-voice-am_adam", "response_format": "wav"}}
    with pytest.raises(ValueError):
        kokoro.synthesize("x", "../etc")


def test_plan_progress_and_result(tmp_path):
    s = session(tmp_path)
    s.plan("DEMO-01", ["Open the order", "Resend", "Check mail"])
    s.mark(1, "pass")
    s.mark(2, "running")
    assert s.test["result"] == "running" and s.test["steps"][1]["status"] == "running"
    s.mark(2, "pass")
    s.mark(3, "fail", "no message")
    assert s.test["result"] == "fail" and s.test["steps"][2]["note"] == "no message"
    with pytest.raises(SessionError):
        s.mark(9, "pass")
    with pytest.raises(SessionError):
        s.mark(1, "maybe")


def test_parse_plan_section():
    text = "# Plan\n\n## DEMO-01 — Resend\n\n1. Open `ORDERS`.\n2. Select **Resend**.\n\n## DEMO-02\n\n1. Other"
    title, steps = cli.parse_plan(text, "DEMO-01")
    assert title == "DEMO-01 — Resend" and steps == ["Open ORDERS.", "Select Resend."]


def test_mercury_answers_are_validated():
    from reverie.control.steer import validate

    actions = page()["actions"]
    assert validate({"choice": "e1", "text": "alice", "confidence": 0.9}, actions)["text"] == "alice"
    assert validate({"choice": "e3", "text": "ignored", "confidence": "x"}, actions) == {
        "choice": "e3", "text": None, "reason": "", "confidence": 0.0}
    assert validate({"choice": "DONE", "confidence": 1}, actions)["choice"] == "DONE"
    for bad in ({"choice": "#login > button"}, {"choice": "e1", "text": ""}, ["e1"]):
        with pytest.raises(ValueError, match="nothing executed"):
            validate(bad, actions)


def test_suggest_then_accept_runs_only_the_proposal(tmp_path, monkeypatch):
    from reverie.control import steer

    s = session(tmp_path)
    s.goal, s.hints, s.pending, s.agent = "Sign in as 'validator'", [], None, None
    monkeypatch.setattr(steer, "escalation_choose", lambda goal, page, history, hints, **kw: (
        {"choice": "e1", "text": "validator", "reason": "username first", "confidence": 0.9}, {"model": "m"}))
    proposal = s.suggest("mercury", hint="use the username box")["proposal"]
    assert proposal["ref"] == "e1" and s.hints == ["use the username box"]
    s.browser.act.assert_not_called()
    s.accept()
    assert s.browser.act.call_count == 1 and s.history[-1]["by"] == "escalation" and s.pending is None
    with pytest.raises(SessionError, match="No pending"):
        s.accept()


def test_auto_pauses_on_low_confidence(tmp_path, monkeypatch):
    from reverie.control import steer

    s = session(tmp_path)
    s.goal, s.hints, s.pending, s.agent = "Sign in as 'validator' and submit", [], None, None
    monkeypatch.setattr(steer, "escalation_choose", lambda *a, **kw: (
        {"choice": "e3", "text": None, "reason": "unsure", "confidence": 0.2}, {"model": "m"}))
    result = s.auto("mercury", max_steps=3)
    assert result["paused"] == "low_confidence" and result["proposal"]["ref"] == "e3"
    s.browser.act.assert_not_called()


def test_configured_voice_pins_every_utterance(monkeypatch):
    from reverie import fish_audio, speech

    spoken = []
    monkeypatch.setenv("SPEECH_PROVIDER", "fish")
    monkeypatch.setenv("FISH_AUDIO_VOICE_ID", "sarah")
    monkeypatch.setattr(fish_audio, "synthesize", lambda text, voice: spoken.append(voice) or b"mp3")
    speech.synthesize("one", "browser-choice")
    speech.synthesize("two", "")
    assert spoken == ["sarah", "sarah"] and speech.settings()["voice"] == "sarah"


def stack_session(tmp_path, monkeypatch, confidence, choice="e3"):
    from reverie.control import steer

    s = session(tmp_path)
    s.goal, s.hints, s.pending, s.agent, s.engine = "Submit order 8", [], None, None, "laya"
    calls = []
    decision = {"choice": choice, "confidence": confidence, "probabilities": {choice: confidence, "e1": 0.1},
                "operation": "CLICK", "target": "3"}
    monkeypatch.setattr(Session, "_fast_propose", lambda self, engine=None: decision)
    monkeypatch.setattr(steer, "escalation_choose", lambda *a, **kw: calls.append(kw) or (
        {"choice": "e1", "text": "order 8", "reason": "better", "confidence": 0.8}, {"model": "mercury"}))
    return s, calls


def test_stack_keeps_confident_laya_decisions_local(tmp_path, monkeypatch):
    s, calls = stack_session(tmp_path, monkeypatch, 0.93)
    proposal = s.suggest("stack")["proposal"]
    assert proposal["layer"] == "decision" and proposal["decision_engine"] == "laya" and proposal["ref"] == "e3" and calls == []


def test_stack_escalates_unsure_laya_to_mercury_with_candidates(tmp_path, monkeypatch):
    s, calls = stack_session(tmp_path, monkeypatch, 0.3)
    proposal = s.suggest("stack")["proposal"]
    assert proposal["layer"] == "escalation" and proposal["ref"] == "e1"
    assert "confidence 0.30" in proposal["escalation"]
    assert calls[0]["candidates"][0]["id"] == "e3" and calls[0]["escalation"] == proposal["escalation"]


def test_stack_sends_fresh_hints_to_mercury_once(tmp_path, monkeypatch):
    s, calls = stack_session(tmp_path, monkeypatch, 0.95)
    assert s.suggest("stack", hint="use the search box")["proposal"]["layer"] == "escalation"
    s.pending = None
    assert s.suggest("stack")["proposal"]["layer"] == "decision" and len(calls) == 1


def test_model_checkpoints_never_carry_commands(tmp_path):
    s = session(tmp_path)
    cp = s.checkpoint("Reset the fixture", command="rm -rf /", source="mercury")["checkpoint"]
    assert cp["command"] is None and s.status == "awaiting-admin"
    assert s.wait(timeout=1)["needs"] == "admin"


def test_admin_plan_step_raises_checkpoint_and_resolves(tmp_path):
    s = session(tmp_path)
    s.plan("DEMO-02", ["[admin] Reset demo fixtures `acme-qa-ctl qa reset-fixtures demo`", "Cancel the order"])
    assert s.test["steps"][0]["command"] == "acme-qa-ctl qa reset-fixtures demo"
    s.mark(1, "running")
    cp = s.pending_checkpoint()
    assert cp["command"] == "acme-qa-ctl qa reset-fixtures demo" and cp["step"] == 1
    s.resolve_checkpoint(cp["id"], "done", exit_code=0, output="ok")
    assert s.test["steps"][0]["status"] == "pass" and s.status == "ready" and s.pending_checkpoint() is None
    with pytest.raises(SessionError, match="already"):
        s.resolve_checkpoint(cp["id"], "done")


def test_parse_plan_keeps_admin_commands():
    title, steps = cli.parse_plan("## X\n1. [admin] Reset `qa reset-fixtures demo`\n2. Open `HOME`", "X")
    assert steps == ["[admin] Reset `qa reset-fixtures demo`", "Open HOME"]


def test_stack_escalates_when_laya_would_undo_mercury(tmp_path, monkeypatch):
    s, calls = stack_session(tmp_path, monkeypatch, 0.97, choice="e1")
    s.goal = "Search order 8 (not 28)"
    s.history.append({"step": 1, "kind": "fill", "label": "Username", "text": "8", "by": "mercury"})
    monkeypatch.setattr(Session, "_fast_propose", lambda self, engine=None: {
        "choice": "e1", "text": "28", "confidence": 0.97, "probabilities": {"e1": 0.97}})
    proposal = s.suggest("stack")["proposal"]
    assert proposal["layer"] == "escalation" and "undo" in proposal["escalation"]


def test_hints_fold_into_laya_goal(tmp_path):
    s = session(tmp_path)
    s.goal, s.hints, s.agent = "Open order", [], object()
    s.add_hint("Order ID is 8")
    assert s.agent is None and "Order ID is 8" in s.laya_goal() and s.laya_goal().startswith("Open order")


def test_stack_escalates_loops_hidden_behind_waits(tmp_path, monkeypatch):
    s, calls = stack_session(tmp_path, monkeypatch, 1.0, choice="e3")
    for kind, label in (("click", "Submit"), ("wait", "Wait"), ("click", "Submit"), ("wait", "Wait")):
        s.history.append({"kind": kind, "label": label, "by": "laya"})
    proposal = s.suggest("stack")["proposal"]
    assert proposal["layer"] == "escalation" and "looping" in proposal["escalation"]


def test_stack_escalates_confident_pick_that_ignores_goal_wording(tmp_path, monkeypatch):
    s, calls = stack_session(tmp_path, monkeypatch, 0.99, choice="e3")
    s.goal = "Click Resend Order Email for order 8"
    s.page["actions"].insert(0, {"id": "e9", "kind": "click", "label": "Resend Order Email", "node": 9})
    proposal = s.suggest("stack")["proposal"]
    assert proposal["layer"] == "escalation" and "goal wording" in proposal["escalation"]


def test_marking_a_step_speaks_one_recap_not_every_click(tmp_path, monkeypatch):
    monkeypatch.delenv("REVERIE_NARRATION", raising=False)
    s = session(tmp_path)
    s.plan("Login", ["Sign in"])
    s.act("e1", text="validator")
    s.act("e3")
    spoken_before = len(s.narrator.say.call_args_list)
    s.mark(1, "pass")
    spoken = [c.args[0] for c in s.narrator.say.call_args_list[spoken_before:]]
    assert len([t for t in spoken if "finished 2 steps" in t]) == 1
    assert not any("Clicking" in c.args[0] for c in s.narrator.say.call_args_list)


def test_stack_escalates_invented_text(tmp_path, monkeypatch):
    s, calls = stack_session(tmp_path, monkeypatch, 1.0, choice="e1")
    monkeypatch.setattr(Session, "_fast_propose", lambda self, engine=None: {
        "choice": "e1", "text": "clicked", "confidence": 1.0, "probabilities": {"e1": 1.0}})
    assert "does not state" in s.suggest("stack")["proposal"]["escalation"]


def test_stated_values_need_quotes_or_distinctive_tokens(tmp_path):
    s = session(tmp_path)
    s.goal, s.hints = "Click Place Order, type the note 'Synthetic order note', search order 8 for a@b.com", []
    assert s.stated_value("synthetic order note") and s.stated_value("a@b.com") and s.stated_value("8")
    assert not s.stated_value("click") and not s.stated_value("clicked")


def test_mercury_may_switch_tabs_only_within_the_list():
    from reverie.control.steer import validate

    actions = page()["actions"]
    assert validate({"choice": "TAB:1", "confidence": 0.9}, actions, tab_count=2)["choice"] == "TAB:1"
    with pytest.raises(ValueError):
        validate({"choice": "TAB:2", "confidence": 0.9}, actions, tab_count=2)


def test_offscreen_target_is_revealed_before_acting(tmp_path):
    s = session(tmp_path)
    s.page["actions"][2] = {**s.page["actions"][2], "offscreen": True}
    revealed = {**s.page["actions"][2]}
    revealed.pop("offscreen")
    s.reveal = Mock(return_value=revealed)
    s.dialogs = []
    s.act("e3")
    s.reveal.assert_called_once()
    assert s.browser.act.call_args.args[0] is revealed


def test_dashboard_splits_a_trail_into_runs_with_frames(tmp_path):
    from reverie.control import dashboard

    folder = tmp_path / "dispatch-admin-20260924-020100"
    folder.mkdir()
    records = [
        {"event": "act", "step": 1, "kind": "fill", "label": "Email", "by": "laya"},
        {"event": "plan", "title": "OPS-02", "steps": ["Open the work order", "[admin] Reset `fx reset`"],
         "source": "/x/regression/02-fieldops.md"},
        {"event": "act", "step": 2, "kind": "click", "label": "Save", "by": "agent"},
        {"event": "frame", "step": 2, "file": "step-002-0001.jpg"},
        {"event": "dialog", "type": "confirm", "message": "Sure?", "answer": True},
        {"event": "mark", "step": 1, "status": "pass", "note": "ok", "result": "running"},
        {"event": "plan", "title": "OPS-03", "steps": ["One"], "source": "/x/regression/02-fieldops.md"},
        {"event": "mark", "step": 1, "status": "fail", "result": "fail"},
        {"event": "stop"},
    ]
    (folder / "trail.jsonl").write_text("\n".join(json.dumps({"t": "2026-09-24T02:01:00", **r}) for r in records))
    first, second = dashboard.parse_trail(folder / "trail.jsonl")
    assert first["suite"] == "regression" and first["session"] == "dispatch-admin"
    assert first["events"][0]["phase"] == "setup"
    save = next(e for e in first["events"] if e.get("label") == "Save")
    assert save["by"] == "orchestrator" and save["frame"] == "step-002-0001.jpg"
    assert next(e for e in first["events"] if e["type"] == "dialog")["type_"] == "confirm"
    assert first["steps"][1] == {"n": 2, "title": "Reset", "admin": True, "status": "pending", "note": ""}
    assert first["layers"] == {"orchestrator": 1} and first["closed"] and second["result"] == "fail"
    tests = dashboard.index([tmp_path])["suites"][0]["tests"]
    assert [t["result"] for t in tests] == ["incomplete", "fail"]


def test_mercury_may_not_type_a_value_the_goal_lacks(tmp_path, monkeypatch):
    s, _ = stack_session(tmp_path, monkeypatch, 0.2)
    s.goal = "Sign in to the admin site"
    with pytest.raises(SessionError, match="does not state"):
        s.suggest("stack")
    s.browser.act.assert_not_called()


def test_scrub_masks_tokens_in_urls_and_nested_values():
    from reverie.control.session import scrub

    assert scrub({"u": ["https://x/verify?token=ABC.def&y=1"]}) == {"u": ["https://x/verify?token=[redacted]&y=1"]}


def test_pilot_guards_avoid_and_allow_values(tmp_path, monkeypatch):
    s, calls = stack_session(tmp_path, monkeypatch, 0.2)
    s.goal = "Sign in"
    s.allow_values = ["order 8"]
    assert s.suggest("stack")["proposal"]["text"] == "order 8"
    s.avoid = ["username"]  # e1 is the Username field in the fixture page
    with pytest.raises(SessionError, match="avoid"):
        s.suggest("stack")


def test_playbook_lessons_persist_by_host(tmp_path, monkeypatch):
    from reverie.control import pilot

    monkeypatch.setenv("REVERIE_PLAYBOOK", str(tmp_path / "book.json"))
    assert pilot.add_lesson("qa.example", "Never click the logo", "T-1")
    assert not pilot.add_lesson("qa.example", "never click the logo ")
    assert pilot.lessons_for({"qa.example", "other"}) == {"qa.example": ["Never click the logo"]}


def test_parse_spec_reads_steps_notes_and_front_matter():
    text = """---
id: OPS-02
app: fieldops  # comment
---
# OPS-02 — Invoice approval link

## Goal
Links work once.

## Steps
1. Open the work order.
2. [admin] Read the DB. `sql c12`

## Evidence
One row.
"""
    title, steps, notes, meta = cli.parse_spec(text)
    assert title == "OPS-02 — Invoice approval link" and meta == {"id": "OPS-02", "app": "fieldops"}
    assert steps == ["Open the work order.", "[admin] Read the DB. `sql c12`"]
    assert notes == ["Goal: Links work once.", "Evidence: One row."]


def test_replay_slides_follow_steps_and_skip_repeated_frames(tmp_path):
    from reverie.control import dashboard

    folder = tmp_path / "s-20260924-020100"
    folder.mkdir()
    records = [
        {"event": "plan", "title": "T-1", "steps": ["Open", "Check"], "source": "/x/suite/a.md"},
        {"event": "mark", "step": 1, "status": "running"},
        {"event": "frame_before", "step": 1, "file": "b1.jpg"},
        {"event": "act", "step": 1, "kind": "click", "label": "Go", "by": "laya"},
        {"event": "frame", "step": 1, "file": "a1.jpg"},
        {"event": "act", "step": 2, "kind": "click", "label": "Go", "by": "mercury"},
        {"event": "frame", "step": 2, "file": "a1.jpg"},
        {"event": "check", "passed": True, "results": [{"check": "text contains 'ok'", "pass": True}], "frame": "c.jpg"},
        {"event": "say", "text": "Step one is done."},
        {"event": "mark", "step": 1, "status": "pass", "note": "ok", "frame": "c.jpg", "result": "running"},
    ]
    (folder / "trail.jsonl").write_text("\n".join(json.dumps({"t": "2026-09-24T02:01:00", **r}) for r in records))
    deck = dashboard.deck([tmp_path], suite="suite")
    kinds = [(s["kind"], s.get("frame")) for s in deck["slides"]]
    assert kinds == [("title", None), ("step", None), ("target", "b1.jpg"), ("result", "a1.jpg"),
                     ("check", "c.jpg"), ("verdict", "c.jpg")]
    assert deck["slides"][2]["caption"].startswith("Decision engine · Laya will click Go")
    assert deck["slides"][-1]["said"] == "Step one is done."


def test_ui_review_attaches_issues_to_the_marked_step(tmp_path, monkeypatch):
    import base64
    import io

    from PIL import Image

    from reverie import model
    from reverie.control import pilot

    s = session(tmp_path)
    s.recap_model = False
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buffer, format="JPEG")
    s.frame = base64.b64encode(buffer.getvalue()).decode()
    s.plan("T", ["Open the page"])
    s.mark(1, "running")
    s.save_frame("step")
    seen = {}
    monkeypatch.setattr(model, "chat_json", lambda system, context, **kw: seen.update(kw) or (
        {"issues": [{"severity": "high", "image": 1, "what": "Header overlaps the form"}], "summary": "Overlap"}, {}))
    s.mark(1, "pass", "ok")
    assert len(seen["images"]) == 1
    assert s.test["steps"][0]["ui"]["issues"][0]["what"] == "Header overlaps the form"
    assert pilot.ui_review(s, s.test["steps"][0], []) is None


def test_laya_may_type_only_quoted_or_exact_token_values(tmp_path):
    s = session(tmp_path)
    s.goal, s.hints = "Open order 8 and search 'Local Demo'", []
    assert s.stated_value("8") and s.stated_value("local demo")
    assert not s.stated_value("orderid 8") and not s.stated_value("click")


def test_nested_bullets_stay_inside_their_step():
    _, steps = cli.parse_plan("1. Fill the form:\n   - City: 'X'\n   - Zip: '1'\n2. Submit.")
    assert steps == ["Fill the form: City: 'X' Zip: '1'", "Submit."]


def test_pilot_allowed_hosts_ignore_trailing_punctuation(tmp_path):
    from reverie.control import pilot

    s = session(tmp_path)
    s.notes = []
    s.plan("T", ["Open Mailpit (https://mailpit.example.net) in a tab."])
    s.browser.tabs = lambda: []
    assert "mailpit.example.net" in pilot.allowed_hosts(s)


def test_commit_clicks_need_the_intent_to_name_them(tmp_path, monkeypatch):
    from reverie.control.session import commit_word

    assert commit_word("Yes (button)") == "yes" and commit_word("Place Order") == "place order"
    assert commit_word("(Yes) (checkbox)") is None and commit_word("ORDERS") is None
    s, _ = stack_session(tmp_path, monkeypatch, 0.2)  # Mercury picks e1; make e1 a Yes button
    s.page["actions"][0].update(kind="click", label="Yes (button)")
    s.goal = "Open the cancel dialog for order 8"
    with pytest.raises(SessionError, match="commits a change"):
        s.suggest("stack")
    s.goal = "Open the cancel dialog for order 8 and click Yes"
    assert s.suggest("stack")["proposal"]["ref"] == "e1"


def test_pilot_warns_on_repeated_intents():
    from reverie.control import pilot

    step = {"n": 2, "progress": {"ops": 7}}
    log = [{"step": 2, "op": "do", "intent": "Click Place Order"}, {"step": 2, "op": "do", "intent": "click place order!"}]
    notes = pilot.warnings_for(step, log, None)
    assert "more than once" in notes[0] and "without a new passing check" in notes[1]


def test_auto_reports_the_actions_it_ran(tmp_path, monkeypatch):
    s, _ = stack_session(tmp_path, monkeypatch, 0.2)
    s.CEILING = 1
    result = s.auto("stack")
    assert result["ran"] and isinstance(result["ran"], list)


def test_mercury_off_returns_doubtful_steps_to_the_pilot(tmp_path, monkeypatch):
    monkeypatch.setenv("REVERIE_ESCALATION", "off")
    s, calls = stack_session(tmp_path, monkeypatch, 0.2)
    proposal = s.suggest("stack")["proposal"]
    assert proposal["ref"] == "BLOCKED" and "escalation model is off" in proposal["reason"] and not calls


def test_project_root_is_the_nearest_ancestor_with_reverie(tmp_path, monkeypatch):
    from reverie.control import project

    nested = tmp_path / "app" / "src" / "deep"
    nested.mkdir(parents=True)
    assert project.project_root(nested) == nested.resolve()  # No .reverie anywhere: the start directory.
    (tmp_path / "app" / ".reverie").mkdir()
    assert project.project_root(nested) == (tmp_path / "app").resolve()
    monkeypatch.chdir(nested)
    assert project.runs_dir() == (tmp_path / "app" / ".reverie" / "runs").resolve()
    assert project.cache_dir().is_dir() and project.cache_dir().parent.name == ".reverie"
    base = tmp_path / "app" / ".reverie"
    assert "runs/" in (base / ".gitignore").read_text() and "cache/" in (base / ".gitignore").read_text()
    assert (base / "README.md").exists()
    monkeypatch.delenv("REVERIE_PLAYBOOK", raising=False)
    assert project.playbook_path() == base.resolve() / "playbook.json"
    monkeypatch.setenv("REVERIE_PLAYBOOK", str(tmp_path / "book.json"))
    assert project.playbook_path() == tmp_path / "book.json"


def test_new_runs_are_written_under_reverie_runs(tmp_path, monkeypatch):
    from reverie.control import session as session_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")  # Jev, the default engine, checks for a key at start
    monkeypatch.setattr(session_module, "HeadedBrowser", Mock())
    monkeypatch.setattr(session_module, "Narrator", Mock(return_value=Mock(voice="off")))
    monkeypatch.setattr(Session, "observe", lambda self, settle=False: None)
    cdp = Mock()
    monkeypatch.setattr(session_module, "cdp", cdp)
    s = Session("https://example.com", name="rvp")
    session_module.HeadedBrowser.call_args.kwargs["prepare"]()  # runs before the first navigation
    assert s.download_dir == s.trail_dir / "downloads" and s.download_dir.is_dir()
    cdp.assert_called_with("Browser.setDownloadBehavior", behavior="allow", downloadPath=str(s.download_dir),
                           eventsEnabled=False)
    assert s.trail_dir.parent == (tmp_path / ".reverie" / "runs").resolve()
    assert s.trail_dir.name.startswith("rvp-") and (s.trail_dir / "trail.jsonl").is_file()


def test_run_json_summarizes_plan_marks_and_end(tmp_path):
    spec = tmp_path / "demo.md"
    spec.write_text("---\nid: DEMO-01\n---\n# Demo\n\n## Steps\n1. Open\n2. Check\n")
    s = session(tmp_path)
    s.started = "2026-09-28T10:00:00"
    s.plan("Demo", ["Open", "Check"], source=str(spec))
    summary = json.loads((tmp_path / "run.json").read_text())
    assert summary["spec_id"] == "DEMO-01" and summary["title"] == "Demo" and summary["source"] == str(spec)
    assert summary["session"] == "test" and summary["started"] == "2026-09-28T10:00:00"
    assert (summary["steps_done"], summary["steps_total"], summary["verdict"], summary["ended"]) == (0, 2, "running", None)
    s.mark(1, "pass")
    s.mark(2, "fail", "missing")
    summary = json.loads((tmp_path / "run.json").read_text())
    assert summary["steps_done"] == 2 and summary["verdict"] == "fail"
    s.close()
    assert json.loads((tmp_path / "run.json").read_text())["ended"]


def write_run(root, folder, title="LEG-01 Old run"):
    path = root / folder
    path.mkdir(parents=True)
    records = [{"t": "2026-09-01T10:00:00", "event": "plan", "title": title, "steps": ["Open"]},
               {"t": "2026-09-01T10:01:00", "event": "mark", "step": 1, "status": "pass", "result": "pass"},
               {"t": "2026-09-01T10:02:00", "event": "stop"}]
    (path / "trail.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_history_reads_reverie_runs_and_legacy_runs(tmp_path, monkeypatch, capsys):
    from reverie.control import dashboard, project

    monkeypatch.chdir(tmp_path)
    write_run(tmp_path / "artifacts" / "agent-sessions", "old-20260901-100000")
    write_run(tmp_path / ".reverie" / "runs", "new-20260928-100000", title="NEW-01 New run")
    roots = project.run_roots()
    assert roots == [tmp_path / ".reverie" / "runs", tmp_path / "artifacts" / "agent-sessions"]
    assert {r["dir"] for r in dashboard.all_runs(roots)} == {"old-20260901-100000", "new-20260928-100000"}
    cli.main(["runs", "list"])
    out = capsys.readouterr().out
    assert "old-20260901-100000~0" in out and "new-20260928-100000~0" in out
    cli.main(["runs", "hide", "old-20260901-100000~0"])
    assert "old-20260901" not in "".join(r["id"] for r in dashboard.all_runs(project.run_roots()))
    cli.main(["walkthrough", "new-20260928-100000~0"])
    assert "Recorded from run" in capsys.readouterr().out
    cli.main(["runs", "import-legacy"])
    assert (tmp_path / ".reverie" / "runs" / "old-20260901-100000" / "trail.jsonl").is_file()
    assert not (tmp_path / "artifacts" / "agent-sessions" / "old-20260901-100000").exists()
    assert "old-20260901-100000~0" in json.loads((tmp_path / ".reverie" / "runs" / "hidden-runs.json").read_text())


def test_init_creates_reverie_and_is_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli.main(["init"])
    out = capsys.readouterr().out
    base = tmp_path / ".reverie"
    for path in (base / "README.md", base / ".gitignore", base / "runs", base / "specs" / "README.md"):
        assert path.exists()
    assert ".reverie/specs/README.md" in out
    assert "## Steps" in (base / "specs" / "README.md").read_text()
    (base / "README.md").write_text("mine")
    cli.main(["init"])
    assert "nothing to create" in capsys.readouterr().out
    assert (base / "README.md").read_text() == "mine"


def test_download_dir_precedence(monkeypatch, tmp_path):
    from reverie.control import downloads

    assert downloads.resolve(None, {}) is None
    assert downloads.resolve("  ", {"REVERIE_DOWNLOAD_DIR": ""}) is None
    assert downloads.resolve(None, {"REVERIE_DOWNLOAD_DIR": str(tmp_path / "env")}) == (tmp_path / "env")
    assert downloads.resolve(str(tmp_path / "opt"), {"REVERIE_DOWNLOAD_DIR": str(tmp_path / "env")}) == (tmp_path / "opt")
    monkeypatch.setenv("REVERIE_DOWNLOAD_DIR", str(tmp_path / "proc"))
    assert downloads.resolve() == (tmp_path / "proc")
    assert downloads.default_for(tmp_path) == tmp_path / "downloads"


def test_start_passes_download_dir_to_the_daemon(monkeypatch, tmp_path):
    popen = Mock()
    popen.return_value.poll.return_value = None
    monkeypatch.setattr(cli.subprocess, "Popen", popen)
    monkeypatch.setattr(cli, "load", Mock(side_effect=[None, {"port": 1}]))
    monkeypatch.setattr(cli, "call", Mock(return_value={"download_dir": "x"}))
    monkeypatch.setattr(cli, "state_file", lambda name: tmp_path / f"{name}.json")
    args = Mock(session="t", url="about:blank", voice="off", goal=None, engine=None, trail_dir=None,
                profile=None, download_dir="/tmp/dl", headless=True, bluetooth=False)
    cli.start(args)
    command = popen.call_args.args[0]
    assert command[command.index("--download-dir") + 1] == "/tmp/dl"


def test_profile_preferences_set_download_dir_and_keep_other_keys(tmp_path):
    from reverie.control import downloads

    prefs = tmp_path / "Default" / "Preferences"
    prefs.parent.mkdir()
    prefs.write_text(json.dumps({"download": {"default_directory": "/home/u/Downloads"}, "other": 1}))
    downloads.write_profile_preferences(tmp_path, tmp_path / "dl")
    saved = json.loads(prefs.read_text())
    assert saved["download"]["default_directory"] == str(tmp_path / "dl")
    assert saved["download"]["prompt_for_download"] is False
    assert saved["other"] == 1


def test_status_reports_the_download_dir(tmp_path):
    s = session(tmp_path)
    s.download_dir = tmp_path / "downloads"
    assert s.summary()["download_dir"] == str(tmp_path / "downloads")


def test_isolated_tab_gets_the_session_download_dir(monkeypatch):
    from reverie.control import session as session_module

    calls = {"Target.createBrowserContext": {"browserContextId": "ctx"}, "Target.createTarget": {"targetId": "t2"}}
    monkeypatch.setattr(session_module, "cdp", lambda method, **params: calls[method])
    browser = object.__new__(session_module.HeadedBrowser)
    browser.prepare = Mock()
    browser.switch = Mock()
    browser.evaluate = Mock(return_value="https://example.com/")
    browser.open_tab("https://example.com/", isolated=True)
    browser.prepare.assert_called_once_with("ctx")
    browser.switch.assert_called_once_with("t2")


def test_import_from_another_checkout_copies_remaps_and_summarizes(tmp_path, monkeypatch, capsys):
    project_dir, other = tmp_path / "proj", tmp_path / "old-tool" / "artifacts" / "agent-sessions"
    (project_dir / ".reverie").mkdir(parents=True)
    write_run(other, "dispatch-admin-20260924-080431", title="OPS-01 Duplicate work order")
    trail = other / "dispatch-admin-20260924-080431" / "trail.jsonl"
    records = [json.loads(line) for line in trail.read_text().splitlines()]
    records[0]["source"] = "/srv/qa/old-specs/regression/ops-01.md"
    trail.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    monkeypatch.chdir(project_dir)
    cli.main(["runs", "import-legacy", "--from", str(other), "--copy",
              "--map-source", "/srv/qa/old-specs/=/srv/qa/old-specs/.reverie/specs/"])
    assert "copied 1 runs" in capsys.readouterr().out
    imported = project_dir / ".reverie" / "runs" / "dispatch-admin-20260924-080431"
    assert trail.is_file()  # --copy keeps the original
    plan = json.loads((imported / "trail.jsonl").read_text().splitlines()[0])
    assert plan["source"] == "/srv/qa/old-specs/.reverie/specs/regression/ops-01.md"
    summary = json.loads((imported / "run.json").read_text())
    assert summary["spec_id"] == "OPS-01" and summary["verdict"] == "pass"
    assert (summary["session"], summary["steps_done"], summary["steps_total"]) == ("dispatch-admin", 1, 1)
    cli.main(["runs", "import-legacy", "--from", str(other), "--copy"])
    assert "copied 0 runs" in capsys.readouterr().out


def test_env_files_read_project_then_cwd_then_user_config(tmp_path, monkeypatch):
    from reverie.control import project, server

    root, config = tmp_path / "proj", tmp_path / "config"
    nested = root / "sub"
    (root / ".reverie").mkdir(parents=True)
    nested.mkdir()
    (config / "reverie").mkdir(parents=True)
    (root / ".env").write_text("REVERIE_T_A=project\n")
    (nested / ".env").write_text("REVERIE_T_A=cwd\nREVERIE_T_B='cwd'\n")
    (config / "reverie" / ".env").write_text("export REVERIE_T_B=user\nREVERIE_T_C=\"user\"\n# REVERIE_T_D=no\n")
    monkeypatch.chdir(nested)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.delenv("REVERIE_ENV_FILE", raising=False)
    for key in ("REVERIE_T_A", "REVERIE_T_B", "REVERIE_T_C", "REVERIE_T_D"):
        monkeypatch.delenv(key, raising=False)
    assert project.env_files() == [root / ".env", nested / ".env", config / "reverie" / ".env"]
    server.load_environment()
    import os
    assert (os.environ["REVERIE_T_A"], os.environ["REVERIE_T_B"], os.environ["REVERIE_T_C"]) == \
        ("project", "cwd", "user")
    assert "REVERIE_T_D" not in os.environ


def test_an_empty_project_value_does_not_hide_the_user_key(tmp_path, monkeypatch):
    import os

    from reverie.control import server

    (tmp_path / ".reverie").mkdir()
    (tmp_path / ".env").write_text("REVERIE_T_KEY=\n")
    (tmp_path / "config" / "reverie").mkdir(parents=True)
    (tmp_path / "config" / "reverie" / ".env").write_text("REVERIE_T_KEY=from-user\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("REVERIE_ENV_FILE", raising=False)
    monkeypatch.setenv("REVERIE_T_KEY", "")
    monkeypatch.delenv("REVERIE_T_KEY")
    server.load_environment()
    assert os.environ["REVERIE_T_KEY"] == "from-user"


def test_pilot_endpoint_falls_back_to_text_model_and_accepts_its_own(monkeypatch):
    from reverie import model

    for name in ("REVERIE_PILOT_PROVIDER", "REVERIE_PILOT_BASE_URL", "REVERIE_PILOT_API_KEY",
                 "TEXT_MODEL_PROVIDER", "OPENCODE_GO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "text-key")
    assert model.endpoint("pilot") == ("https://openrouter.ai/api/v1", "text-key", "openrouter")
    monkeypatch.setenv("REVERIE_PILOT_BASE_URL", "https://gateway.example.com/v1/")
    monkeypatch.setenv("REVERIE_PILOT_API_KEY", "pilot-key")
    assert model.endpoint("pilot") == ("https://gateway.example.com/v1", "pilot-key", None)
    assert model.endpoint("text") == ("https://openrouter.ai/api/v1", "text-key", "openrouter")
    assert model.reasoning_options("https://gateway.example.com/v1", None, None) == {"reasoning": {"effort": "low"}}


def test_opencode_go_provider_reads_the_opencode_key_and_sends_session_headers(tmp_path, monkeypatch):
    from reverie import model

    for name in ("REVERIE_PILOT_BASE_URL", "REVERIE_PILOT_API_KEY", "OPENCODE_GO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"opencode-go": {"type": "api", "key": "go-key"}}))
    monkeypatch.setenv("OPENCODE_AUTH_FILE", str(auth))
    monkeypatch.setenv("REVERIE_PILOT_PROVIDER", "opencode-go")
    assert model.endpoint("pilot") == ("https://opencode.ai/zen/go/v1", "go-key", "opencode-go")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "env-key")
    assert model.endpoint("pilot")[1] == "env-key"
    headers = model.provider_headers("opencode-go")
    assert headers["User-Agent"].startswith("reverie/") and headers["x-opencode-session"]
    assert model.provider_headers("openrouter") == {}
    assert model.reasoning_options("https://opencode.ai/zen/go/v1", "opencode-go", None) == {"reasoning_effort": "low"}
    sent = {}
    monkeypatch.setattr(model, "post_json", lambda url, key, body, headers=None: sent.update(
        url=url, key=key, headers=headers) or {"choices": [{"message": {"content": "{\"ok\": true}"}}]})
    output, _ = model.chat_json("s", {}, model="glm-5.3-flash", role="pilot")
    assert output == {"ok": True} and sent["url"] == "https://opencode.ai/zen/go/v1/chat/completions"
    assert sent["key"] == "env-key" and "x-opencode-session" in sent["headers"]
    monkeypatch.setenv("REVERIE_PILOT_PROVIDER", "bogus")
    with pytest.raises(ValueError):
        model.endpoint("pilot")


def test_openrouter_provider_uses_openrouter_api_key(monkeypatch):
    from reverie import model

    for name in ("REVERIE_PILOT_PROVIDER", "REVERIE_PILOT_BASE_URL", "REVERIE_PILOT_API_KEY",
                 "TEXT_MODEL_BASE_URL", "TEXT_MODEL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TEXT_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    assert model.endpoint("pilot") == ("https://openrouter.ai/api/v1", "or-key", "openrouter")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "text-key")
    assert model.endpoint("text")[1] == "text-key"


def test_reverie_gitignore_covers_downloads_and_is_upgraded(tmp_path):
    from reverie.control import project

    base = tmp_path / ".reverie"
    base.mkdir()
    (base / ".gitignore").write_text("runs/\ncache/\nmine/\n")
    project.reverie_dir(tmp_path)
    assert (base / ".gitignore").read_text().splitlines() == ["runs/", "cache/", "mine/", "downloads/"]
    project.reverie_dir(tmp_path)
    assert (base / ".gitignore").read_text().count("downloads/") == 1


def test_commit_words_cover_cancel_with_any_object_and_keep_the_old_matches():
    from reverie.control.session import commit_word

    assert commit_word("Cancel Ticket") == "cancel ticket" and commit_word("Cancel Order (button)") == "cancel order"
    assert commit_word("Cancel Work Order") == "cancel work"
    assert commit_word("Cancel") is None and commit_word("Cancel (button)") is None
    assert commit_word("Submit Ticket") == "submit" and commit_word("Submit Work Order") == "submit"
    assert commit_word("Delete Login") == "delete" and commit_word("Save changes") == "save"
    assert commit_word("Edit Details") == "edit details" and commit_word("Place Order") == "place order"
    assert commit_word("Dispatch") is None and commit_word("Work Order") is None


def test_the_check_command_passes_link_and_href_to_the_session():
    from reverie.control.server import COMMANDS

    session = Mock()
    COMMANDS["check"](session, {"link": "Confirm", "href": "token="})
    session.check.assert_called_once_with(None, None, None, "Confirm", "token=")
