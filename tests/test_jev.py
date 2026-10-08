"""Offline contracts for the hosted Jev decision engine. The OpenRouter call is always mocked."""

from unittest.mock import Mock

import httpx
import pytest
from test_control import page, session

from reverie import model
from reverie.control import steer
from reverie.control.session import Session, SessionError

ANSWERS = {
    "operation": {"type": "choice", "choice": "CLICK", "confidence": 0.9,
                  "probabilities": {"CLICK": 0.9, "TYPE_TEXT": 0.04, "SELECT": 0.03, "WAIT": 0.01, "DONE": 0.01,
                                    "BLOCKED": 0.01}},
    "click_target": {"type": "choice", "choice": "2", "confidence": 0.8,
                     "probabilities": {"1": 0.2, "2": 0.8}},
}


def jev_response(answers=ANSWERS):
    return {"id": "gen-dec-1", "model": "typesafe/jev-1.13-20260917", "provider": "TypeSafe", "answers": answers,
            "usage": {"input_tokens": 1500, "output_tokens": 90, "cost": 0.00007}}


def state():
    p = page()
    return {k: p[k] for k in ("url", "title", "text", "actions")}


def test_choose_posts_the_decisions_request_and_maps_the_answer(monkeypatch):
    sent = {}
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(model, "post_json", lambda url, key, body: sent.update(url=url, key=key, body=body)
                        or jev_response())
    decision = model.choose(state(), "Click 'Submit'", [])
    assert sent["url"] == "https://openrouter.ai/api/alpha/decisions" and sent["key"] == "test-key"
    body = sent["body"]
    assert body["model"] == "typesafe/jev-1.13" and body["session_id"] == model.SESSION_ID
    assert set(body["questions"]) == {"operation", "click_target", "type_text_target", "select_target"}
    assert all(q["type"] == "choice" and q["instructions"] and q["criteria"] for q in body["questions"].values())
    assert decision["choice"] == "e3" and decision["operation"] == "CLICK" and decision["confidence"] == 0.9
    assert decision["usage"]["cost"] == 0.00007


def test_answers_without_probabilities_or_confidence_are_never_certain():
    ids = {"1": "a", "2": "b"}
    answer = model.validate_choice({"type": "choice", "choice": "2"}, ids)
    assert answer["probabilities"] == {"1": 0.0, "2": 1.0} and answer["confidence"] == 0.0
    with_probabilities = model.validate_choice({"choice": "1", "probabilities": {"1": 0.7, "2": 0.3}}, ids)
    assert with_probabilities["confidence"] == 0.7


def test_invalid_answers_are_refused():
    with pytest.raises(ValueError):
        model.validate_choice({"choice": "3", "confidence": 1.0, "probabilities": {"1": 0.5, "2": 0.5}},
                              {"1": "a", "2": "b"})
    with pytest.raises(ValueError):
        model.validate_choice({"choice": "1", "confidence": 1.0, "probabilities": {"1": 0.2, "2": 0.8}},
                              {"1": "a", "2": "b"})


def test_provider_errors_keep_the_providers_message(monkeypatch):
    response = httpx.Response(402, json={"error": {"code": 402, "message": "Insufficient credits.\n Add more."}})
    monkeypatch.setattr(model.CLIENT, "post", Mock(return_value=response))
    with pytest.raises(RuntimeError, match=r"HTTP 402: Insufficient credits\. Add more\.; no action executed"):
        model.post_json("https://openrouter.ai/api/alpha/decisions", "k", {})


def test_jev_needs_an_openrouter_key(monkeypatch):
    for name in ("OPENROUTER_API_KEY", "TEXT_MODEL_API_KEY", "TEXT_MODEL_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        model.openrouter_key()


def jev_session(tmp_path, monkeypatch, decision, engine="jev"):
    s = session(tmp_path)
    s.goal, s.hints, s.pending, s.agent, s.engine = "Type 'order 8' into Username", [], None, None, engine
    used = []
    agent = Mock()
    agent.state = {"status": "ready", "goal": s.goal, "history": [], "text_calls": [], "decision": decision}
    monkeypatch.setattr(Session, "autonomous", lambda self, goal=None, engine=None: used.append(engine) or agent)
    return s, used


def test_the_stack_uses_jev_when_the_session_engine_is_jev(tmp_path, monkeypatch):
    decision = {"choice": "e3", "confidence": 0.95, "probabilities": {"e3": 0.95}, "operation": "CLICK",
                "target": "2"}
    s, used = jev_session(tmp_path, monkeypatch, decision)
    s.goal = "Click 'Submit'"
    proposal = s.suggest("stack")["proposal"]
    assert used == ["jev"] and proposal["layer"] == "decision" and proposal["decision_engine"] == "jev" and proposal["ref"] == "e3"


def test_unsure_jev_escalates_to_mercury_under_the_stack(tmp_path, monkeypatch):
    decision = {"choice": "e3", "confidence": 0.3, "probabilities": {"e3": 0.3}, "operation": "CLICK"}
    s, used = jev_session(tmp_path, monkeypatch, decision)
    monkeypatch.setattr(steer, "escalation_choose", lambda *a, **kw: (
        {"choice": "e1", "text": "order 8", "reason": "field first", "confidence": 0.8}, {"model": "mercury"}))
    proposal = s.suggest("stack")["proposal"]
    assert proposal["layer"] == "escalation" and proposal["escalation"].startswith("Jev confidence 0.30")


def test_jev_field_values_are_resolved_and_guarded_before_anything_runs(tmp_path, monkeypatch):
    decision = {"choice": "e1", "confidence": 0.9, "probabilities": {"e1": 0.9}, "operation": "TYPE_TEXT"}
    s, _ = jev_session(tmp_path, monkeypatch, decision)
    monkeypatch.setattr(model, "field_text", lambda context: ("order 8", {"model": "text", "latency_ms": 5}))
    proposal = s.suggest("jev")["proposal"]
    assert proposal["text"] == "order 8" and "order 8" in proposal["label"] and decision["text"] == "order 8"

    decision.pop("text")
    monkeypatch.setattr(model, "field_text", lambda context: ("invented", {"model": "text", "latency_ms": 5}))
    with pytest.raises(SessionError, match="does not state"):
        s.suggest("jev")


def test_session_engine_defaults_to_jev(tmp_path):
    s = session(tmp_path)
    assert s.fast_engine() == "jev"
    s.engine = "laya"
    assert s.fast_engine() == "laya"


def bare_session(monkeypatch, tmp_path, **kw):
    from reverie.control import session as session_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(session_module, "HeadedBrowser", Mock())
    monkeypatch.setattr(session_module, "Narrator", Mock(return_value=Mock(voice="off")))
    monkeypatch.setattr(Session, "observe", lambda self, settle=False: None)
    monkeypatch.setattr(session_module, "cdp", Mock())
    return Session("https://example.com", name="engine", **kw)


def no_key(monkeypatch):
    for name in ("OPENROUTER_API_KEY", "TEXT_MODEL_API_KEY", "TEXT_MODEL_BASE_URL", "REVERIE_DECISION_ENGINE"):
        monkeypatch.delenv(name, raising=False)


def test_a_new_session_uses_jev_unless_told_otherwise(tmp_path, monkeypatch):
    no_key(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    assert bare_session(monkeypatch, tmp_path).fast_engine() == "jev"
    monkeypatch.setenv("REVERIE_DECISION_ENGINE", "laya")
    assert bare_session(monkeypatch, tmp_path).fast_engine() == "laya"
    assert bare_session(monkeypatch, tmp_path, engine="jev").fast_engine() == "jev"  # the flag wins


def test_jev_without_a_key_fails_at_start_with_the_fix(tmp_path, monkeypatch):
    no_key(monkeypatch)
    with pytest.raises(SessionError, match=r"OPENROUTER_API_KEY.*REVERIE_DECISION_ENGINE=laya"):
        bare_session(monkeypatch, tmp_path)
    monkeypatch.setenv("REVERIE_DECISION_ENGINE", "laya")  # local Laya needs no key
    assert bare_session(monkeypatch, tmp_path).fast_engine() == "laya"


def test_a_missing_key_mid_run_is_an_error_not_an_escalation(tmp_path, monkeypatch):
    s = session(tmp_path)
    s.goal, s.hints, s.pending, s.agent, s.engine = "Click 'Submit'", [], None, None, None

    def missing(self, engine=None):
        raise model.MissingKey("Jev, the default decision engine, needs an OpenRouter key.")

    monkeypatch.setattr(Session, "_fast_propose", missing)
    with pytest.raises(SessionError, match="needs an OpenRouter key"):
        s.suggest("stack")


def test_a_hint_does_not_block_the_fast_layer_when_mercury_is_off(tmp_path, monkeypatch):
    monkeypatch.setenv("REVERIE_ESCALATION", "off")
    decision = {"choice": "e3", "confidence": 0.99, "probabilities": {"e3": 0.99}, "operation": "CLICK"}
    s, used = jev_session(tmp_path, monkeypatch, decision)
    s.goal = "Click 'Submit'"
    s.add_hint("the Submit button at the bottom")
    proposal = s.suggest("stack")["proposal"]
    assert proposal["layer"] == "decision" and proposal["decision_engine"] == "jev" and proposal["ref"] == "e3" and proposal["escalation"] is None


def test_a_hint_still_goes_to_mercury_when_mercury_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("REVERIE_ESCALATION", "on")
    decision = {"choice": "e3", "confidence": 0.99, "probabilities": {"e3": 0.99}, "operation": "CLICK"}
    s, _ = jev_session(tmp_path, monkeypatch, decision)
    s.goal = "Click 'Submit'"
    s.add_hint("the Submit button at the bottom")
    monkeypatch.setattr(steer, "escalation_choose", lambda *a, **kw: (
        {"choice": "e3", "text": None, "reason": "hinted", "confidence": 0.9}, {"model": "mercury"}))
    assert s.suggest("stack")["proposal"]["escalation"] == "orchestrator hint"


def test_a_bare_pilot_wait_means_the_observed_wait_action(tmp_path):
    from reverie.control import pilot

    s = session(tmp_path)
    op = pilot.validate({"op": "wait", "reason": "Loading bar is still animating"}, s)
    assert op["op"] == "act" and op["ref"] == "wait"


def test_done_stays_done_when_mercury_is_off(tmp_path, monkeypatch):
    monkeypatch.setenv("REVERIE_ESCALATION", "off")
    decision = {"choice": "DONE", "confidence": 0.9, "probabilities": {"DONE": 0.9}, "operation": "DONE"}
    s, _ = jev_session(tmp_path, monkeypatch, decision)
    assert s.suggest("stack")["proposal"]["ref"] == "DONE"
    decision.update(choice="BLOCKED", probabilities={"BLOCKED": 0.9}, operation="BLOCKED")
    assert s.suggest("stack")["proposal"]["ref"] == "BLOCKED"


def test_the_pilot_can_answer_a_prompt_with_a_stated_value(tmp_path):
    from reverie.control import pilot

    s = session(tmp_path)
    s.test = {"steps": [{"title": "Rename the task to 'Oil and adjust the chain'"}]}
    s.notes = []
    op = pilot.validate({"op": "dialogs", "answer": "accept", "text": "Oil and adjust the chain"}, s)
    assert op["answer"] == "accept" and op["text"] == "Oil and adjust the chain"
    assert pilot.validate({"op": "dialogs", "answer": "dismiss"}, s)["text"] is None
    with pytest.raises(ValueError, match="do not state"):
        pilot.validate({"op": "dialogs", "answer": "accept", "text": "something else"}, s)


def test_the_prompt_hook_returns_the_configured_text(monkeypatch):
    from reverie.control import session as session_module

    browser = session_module.HeadedBrowser.__new__(session_module.HeadedBrowser)
    browser.dialog_answer, browser.prompt_text = "accept", "Oil and adjust"
    sent = []
    browser.call = lambda method, **kw: sent.append(kw.get("expression"))
    monkeypatch.setattr(session_module.Browser, "observe", lambda self, **kw: {})
    browser.observe()
    assert 'window.__layaPromptText = "Oil and adjust";' in sent[0]
    assert "window.__layaPromptText ?? d" in sent[0]


def test_pilot_text_on_a_select_option_chooses_the_matching_option(tmp_path):
    from reverie.control import pilot

    s = session(tmp_path)
    s.test, s.notes = {"steps": [{"title": "Choose State 'Texas'"}]}, []
    op = pilot.validate({"op": "act", "ref": "e4", "text": "Texas"}, s)  # e4 is 'State → California'
    assert op["ref"] == "e5" and op["text"] is None
    with pytest.raises(ValueError, match="does not take text"):
        pilot.validate({"op": "act", "ref": "e4", "text": "Ohio"}, s)


def test_a_one_off_engine_does_not_change_the_session_engine(tmp_path, monkeypatch):
    from reverie import agent as agent_module

    s = session(tmp_path)
    s.goal, s.hints, s.agent, s.engine = "Click 'Submit'", [], None, None
    monkeypatch.setattr(agent_module, "Agent", lambda *a, decision_engine=None, **kw: Mock(
        state={"goal": a[1], "decision_engine": decision_engine, "status": "ready"}))
    s.autonomous(s.goal, "laya")
    assert s.fast_engine() == "jev"
