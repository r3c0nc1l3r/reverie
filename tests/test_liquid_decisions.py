"""Contracts for hosted visual decisions."""

import base64
import io
import json

import pytest
from PIL import Image

from reverie import agent, model


def screenshot(width=24, height=16):
    output = io.BytesIO()
    Image.new("RGBA", (width, height), (20, 40, 60, 128)).save(output, "PNG")
    return base64.b64encode(output.getvalue()).decode()


def page(**updates):
    value = {
        "url": "https://example.test/",
        "title": "Example",
        "text": "Continue",
        "w": 1120,
        "h": 780,
        "actions": [
            {"id": "e1", "kind": "click", "node": 7, "role": "button", "label": "Continue",
             "value": "", "rect": {"x": 10, "y": 20, "w": 100, "h": 30}},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
        "screenshot": screenshot(),
        "fingerprint": "fp",
    }
    value.update(updates)
    return value


def response(operation="DONE"):
    probabilities = {"CLICK": 0.0, "WAIT": 0.0, "DONE": 1.0, "BLOCKED": 0.0}
    return {"answers": {"operation": {"choice": operation, "confidence": 1.0,
                                        "probabilities": probabilities}}, "model": "liquid/d1-ultra"}


def capture_request(monkeypatch, result=None):
    sent = {}

    def post(url, key, body):
        sent.update(url=url, key=key, body=body)
        return result or response()

    monkeypatch.setattr(model, "openrouter_key", lambda: "test-key")
    monkeypatch.setattr(model, "post_json", post)
    return sent


def test_engine_models_and_image_defaults(monkeypatch):
    monkeypatch.delenv("REVERIE_DECISION_IMAGES", raising=False)
    monkeypatch.setenv("REMOTE_DECISION_MODEL", "typesafe/custom")
    monkeypatch.setenv("REVERIE_LIQUID_MODEL", "liquid/d1")
    assert model.remote_decision_model() == "typesafe/custom"
    assert model.liquid_decision_model() == "liquid/d1"
    assert model.decision_images("jev") is False
    assert model.decision_images("liquid") is True


@pytest.mark.parametrize(("setting", "expected"), [("on", True), ("0", False), ("YES", True), ("false", False)])
def test_image_override_is_strict(monkeypatch, setting, expected):
    monkeypatch.setenv("REVERIE_DECISION_IMAGES", setting)
    assert model.decision_images("jev") is expected
    assert model.decision_images("liquid") is expected
    monkeypatch.setenv("REVERIE_DECISION_IMAGES", "sometimes")
    with pytest.raises(ValueError, match="REVERIE_DECISION_IMAGES"):
        model.decision_images("liquid")


def test_liquid_request_has_jpeg_image_viewport_and_geometry(monkeypatch):
    sent = capture_request(monkeypatch)
    result = model.choose(page(), "Finish", [], engine="liquid")
    body = sent["body"]
    assert body["model"] == "liquid/d1-ultra"
    assert body["session_id"] == model.SESSION_ID
    assert isinstance(body["state"], list) and len(body["state"]) == 2
    structured = json.loads(body["state"][0])
    assert structured["page"]["viewport"] == {"width": 1120, "height": 780}
    assert structured["elements"][0]["rect"] == {"x": 10, "y": 20, "w": 100, "h": 30}
    url = body["state"][1]["image_url"]["url"]
    assert body["state"][1]["type"] == "image_url"
    assert url.startswith("data:image/jpeg;base64,")
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        assert image.format == "JPEG" and image.mode == "RGB"
    assert result["choice"] == "DONE"


@pytest.mark.parametrize("updates", [{"screenshot": None}, {"screenshot_stale": True}, {"screenshot": "not base64"}])
def test_liquid_rejects_missing_stale_or_malformed_image(monkeypatch, updates):
    sent = capture_request(monkeypatch)
    with pytest.raises(ValueError, match="screenshot|Screenshot"):
        model.choose(page(**updates), "Finish", [], engine="liquid")
    assert not sent


def test_default_jev_payload_remains_text_only(monkeypatch):
    sent = capture_request(monkeypatch)
    model.choose(page(screenshot=None), "Finish", [])
    state = sent["body"]["state"]
    assert sent["body"]["model"] == model.DEFAULT_REMOTE_DECISION_MODEL
    assert state == {
        "page": {"url": "https://example.test/", "title": "Example", "text": "Continue"},
        "elements": [{"role": "button", "value": "", "index": "1", "label": "Continue",
                      "operations": ["CLICK"]}],
        "recent_actions": [],
    }


def test_missing_rectangle_does_not_shift_later_target_geometry(monkeypatch):
    state = page()
    state["actions"][0].pop("rect")
    state["actions"].insert(1, {"id": "e2", "kind": "click", "node": 8, "label": "Cancel",
                                "rect": {"x": 200, "y": 10, "w": 50, "h": 30}})
    sent = capture_request(monkeypatch)
    model.choose(state, "Finish", [], engine="liquid")
    elements = json.loads(sent["body"]["state"][0])["elements"]
    assert "rect" not in elements[0]
    assert elements[1]["rect"]["x"] == 200


def test_malformed_probabilities_fail_closed():
    with pytest.raises(ValueError, match="Invalid TypeSafe response"):
        model.validate_choice({"choice": "a", "confidence": 1, "probabilities": []}, {"a"})


def test_liquid_keeps_strict_answer_validation(monkeypatch):
    bad = response()
    bad["answers"]["operation"]["choice"] = "FREE_FORM_SELECTOR"
    capture_request(monkeypatch, bad)
    with pytest.raises(ValueError, match="Invalid TypeSafe response"):
        model.choose(page(), "Finish", [], engine="liquid")


class FakeBrowser:
    def __init__(self):
        self.observe_calls = []
        self.page = page()

    def observe(self, **kwargs):
        self.observe_calls.append(kwargs)
        return self.page

    def fresh(self, _page, _action=None):
        return True


def test_agent_liquid_requires_images_and_forwards_engine_only_for_liquid(monkeypatch):
    calls = []
    monkeypatch.delenv("REVERIE_DECISION_IMAGES", raising=False)
    monkeypatch.setattr(agent, "choose", lambda *args, **kwargs: calls.append(kwargs) or {
        "choice": "DONE", "probabilities": {"DONE": 1.0}, "confidence": 1.0, "latency_ms": 0,
        "operation": "DONE", "target": None, "usage": {},
    })
    browser = FakeBrowser()
    run = agent.Agent("unused", "Finish", decision_engine="liquid", observation_mode="dom", browser=browser)
    assert run.observation_mode == "image"
    assert run.screenshots is True and run.screenshot_fallback is False
    assert browser.observe_calls == [{"screenshot": True, "screenshot_fallback": False}]
    run.command("predict")
    assert calls == [{"engine": "liquid"}]

    calls.clear()
    jev = agent.Agent("unused", "Finish", decision_engine="jev", browser=FakeBrowser())
    jev.command("predict")
    assert calls == [{}]


def test_new_settings_take_priority_over_compatibility_aliases(monkeypatch):
    monkeypatch.setenv("LIQUID_DECISION_MODEL", "liquid/legacy")
    monkeypatch.setenv("REMOTE_DECISION_IMAGES", "off")
    monkeypatch.delenv("REVERIE_LIQUID_MODEL", raising=False)
    monkeypatch.delenv("REVERIE_DECISION_IMAGES", raising=False)
    assert model.liquid_decision_model() == "liquid/legacy"
    assert model.decision_images("liquid") is False
    monkeypatch.setenv("REVERIE_LIQUID_MODEL", "liquid/current")
    monkeypatch.setenv("REVERIE_DECISION_IMAGES", "on")
    assert model.liquid_decision_model() == "liquid/current"
    assert model.decision_images("jev") is True
