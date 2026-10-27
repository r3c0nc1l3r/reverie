"""Contracts for visual review and guarded pointer movement."""

import base64
import io

import pytest
from PIL import Image
from test_control import session

from reverie import model
from reverie.control import pilot


def _frame(color="white"):
    image = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(image, format="JPEG")
    return base64.b64encode(image.getvalue()).decode()


def _review_session(tmp_path):
    s = session(tmp_path)
    s.recap_model = False
    s.frame = _frame()
    s.last_capture_ok = True
    s.page["marker"] = "marker-1"
    s._visual_frame_marker = "marker-1"
    s._visual_frame_state = "signature-1"
    s.browser.evaluate.return_value = "marker-1"
    s.browser.visual_state.return_value = "signature-1"
    s.capture = lambda: None  # Preserve the current capture DTO unless a test changes it.
    s.plan("Review", ["First step", "Second step"])
    return s


def test_unchanged_fresh_frame_is_evidence_for_each_step(tmp_path, monkeypatch):
    monkeypatch.setenv("REVERIE_UI_REVIEW", "on")
    monkeypatch.delenv("LAYA_AGENT_UI_REVIEW", raising=False)
    seen = []
    monkeypatch.setattr(model, "chat_json", lambda system, context, **kw: (
        seen.append(kw["images"]) or {"issues": [], "summary": "clear"}, {}))
    s = _review_session(tmp_path)
    for step in (1, 2):
        s.mark(step, "running")
        s.save_frame("step")
        s.mark(step, "pass", "done")
    assert len(seen) == 2
    assert all(images for images in seen)
    assert all(step.get("ui") is not None for step in s.test["steps"])


def test_failed_capture_does_not_review_previous_step_frame(tmp_path, monkeypatch):
    from reverie.control.session import SessionError

    monkeypatch.setenv("REVERIE_UI_REVIEW", "on")
    monkeypatch.delenv("LAYA_AGENT_UI_REVIEW", raising=False)
    seen = []
    monkeypatch.setattr(model, "chat_json", lambda system, context, **kw: (
        seen.append(kw["images"]) or {"issues": [], "summary": "clear"}, {}))
    s = _review_session(tmp_path)
    s.visual_mode = "primary"
    s.mark(1, "running")
    s.checks = [{"passed": True}]
    s.save_frame("step")
    s.mark(1, "pass", "done")
    s.mark(2, "running")
    s.checks = [{"passed": True}]
    s.last_capture_ok = False
    s.save_frame("step")
    try:
        s.mark(2, "pass", "done")
    except SessionError:
        pass
    assert len(seen) == 1
    assert not s.test["steps"][1].get("ui")
    assert s.test["steps"][1].get("status") != "pass"


def test_changed_dom_after_capture_cannot_be_reviewed_as_fresh(tmp_path, monkeypatch):
    from reverie.control.session import SessionError

    monkeypatch.setenv("REVERIE_UI_REVIEW", "on")
    calls = []
    monkeypatch.setattr(model, "chat_json", lambda system, context, **kw: (
        calls.append(kw["images"]) or {"issues": [], "summary": "clear"}, {}))
    s = _review_session(tmp_path)
    s.visual_mode = "primary"
    s.mark(1, "running")
    s.checks = [{"passed": True}]
    s.save_frame("step")
    s.browser.visual_state.return_value = "signature-after-mutation"
    try:
        s.mark(1, "pass", "done")
    except SessionError:
        pass
    assert calls == []
    assert s.test["steps"][0].get("status") != "pass"


def test_review_refreshes_pixels_when_dom_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("REVERIE_UI_REVIEW", "on")
    seen = []
    monkeypatch.setattr(model, "chat_json", lambda system, context, **kw: (
        seen.extend(kw["images"]) or {"issues": [], "summary": "clear"}, {}))
    s = _review_session(tmp_path)
    new_frame = _frame("black")
    captures = []

    def capture():
        captures.append(True)
        s.frame = new_frame
        s.last_capture_ok = True
        s._visual_frame_marker = "marker-1"
        s._visual_frame_state = "signature-1"

    s.capture = capture
    s.mark(1, "running")
    s.save_frame("step")
    s.mark(1, "pass", "done")
    assert captures
    assert seen
    with Image.open(io.BytesIO(base64.b64decode(seen[-1]))) as reviewed:
        assert max(reviewed.convert("RGB").getpixel((20, 15))) < 20


@pytest.mark.parametrize("changed_field", ["marker", "signature"])
def test_change_during_model_review_cannot_pass_or_accept_result(tmp_path, monkeypatch, changed_field):
    from reverie.control.session import SessionError

    monkeypatch.setenv("REVERIE_UI_REVIEW", "on")
    s = _review_session(tmp_path)
    s.visual_mode = "primary"
    calls = []

    def review(system, context, **kwargs):
        calls.append(kwargs["images"])
        if changed_field == "marker":
            s.browser.evaluate.return_value = "marker-after-review"
        else:
            s.browser.visual_state.return_value = "signature-after-review"
        return {"issues": [], "summary": "clear"}, {}

    monkeypatch.setattr(model, "chat_json", review)
    s.mark(1, "running")
    s.checks = [{"passed": True}]
    s.save_frame("step")
    try:
        s.mark(1, "pass", "done")
    except SessionError:
        pass
    assert calls
    assert s.test["steps"][0].get("status") != "pass"
    assert not s.test["steps"][0].get("ui")


@pytest.mark.parametrize("final_kind", ["missing", "unreadable"])
def test_ui_review_rejects_invalid_final_frame_without_fallback(tmp_path, monkeypatch, final_kind):
    monkeypatch.setenv("REVERIE_UI_REVIEW", "on")
    calls = []
    monkeypatch.setattr(model, "chat_json", lambda *args, **kwargs: (
        calls.append(kwargs) or {"issues": [], "summary": "clear"}, {}))
    s = _review_session(tmp_path)
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "earlier.jpg").write_bytes(base64.b64decode(_frame()))
    if final_kind == "unreadable":
        (frames / "final.jpg").write_bytes(b"not an image")
    result = pilot.ui_review(s, s.test["steps"][0], ["earlier.jpg", "final.jpg"])
    assert result is None
    assert calls == []


@pytest.mark.parametrize("canonical,alias,expected", [
    ("off", "on", False), ("false", "on", False), ("0", "on", False),
    ("no", "on", False), (None, "off", False), ("on", "off", True),
])
def test_review_environment_alias_and_precedence(tmp_path, monkeypatch, canonical, alias, expected):
    if canonical is None:
        monkeypatch.delenv("REVERIE_UI_REVIEW", raising=False)
    else:
        monkeypatch.setenv("REVERIE_UI_REVIEW", canonical)
    monkeypatch.setenv("LAYA_AGENT_UI_REVIEW", alias)
    seen = []
    monkeypatch.setattr(model, "chat_json", lambda system, context, **kw: (
        seen.append(kw["images"]) or {"issues": [], "summary": "clear"}, {}))
    s = _review_session(tmp_path)
    s.mark(1, "running")
    s.save_frame("step")
    s.mark(1, "pass", "done")
    assert bool(seen) is expected


def test_pilot_hover_accepts_only_observed_clickable_ref(tmp_path):
    s = session(tmp_path)
    assert pilot.validate({"op": "hover", "ref": "e3"}, s)["ref"] == "e3"
    for decision in ({"op": "hover", "ref": "unknown"},):
        with pytest.raises(ValueError):
            pilot.validate(decision, s)


def test_pilot_visual_hover_rejects_nonfinite_outside_or_text(tmp_path):
    s = session(tmp_path)
    for decision in (
        {"op": "visual_hover", "x": float("nan"), "y": 1},
        {"op": "visual_hover", "x": 1, "y": float("inf")},
        {"op": "visual_hover", "x": -1, "y": 1},
        {"op": "visual_hover", "x": 200, "y": 1},
        {"op": "visual_hover", "x": 1, "y": 1, "text": "unexpected"},
    ):
        with pytest.raises(ValueError):
            pilot.validate(decision, s, image_size=(200, 100))


def test_headless_hover_moves_pointer_only_on_safe_target_and_refuses_protected_labels(tmp_path):
    import http.server
    import os
    import subprocess
    import sys
    import tempfile
    import threading
    import uuid
    from pathlib import Path

    from reverie.control.chromium import find_browser

    try:
        find_browser()
    except RuntimeError:
        pytest.skip("no Chromium-family browser installed")

    interactions = []
    safe_seen = threading.Event()
    html = b'''<!doctype html><style>
      body { margin: 0; }
      .target { position: absolute; left: 20px; width: 120px; height: 35px; }
      #safe { top: 20px; } #hidden-label { top: 80px; }
      #disabled-label { top: 130px; } #inert-label { top: 180px; }
      .control { position: absolute; left: 500px; }
      label { display: block; width: 100%; height: 100%; }
    </style>
    <button id="safe" class="target">Safe</button>
    <div role="button" class="target" id="hidden-label"><label for="hidden-control">Hidden target</label></div>
    <div role="button" class="target" id="disabled-label"><label for="disabled-control">Disabled target</label></div>
    <div role="button" class="target" id="inert-label"><label for="inert-control">Inert target</label></div>
    <div aria-hidden="true"><input class="control" id="hidden-control"></div>
    <div aria-disabled="true"><input class="control" id="disabled-control"></div>
    <div inert><input class="control" id="inert-control"></div>
    <script>
      for (const el of document.querySelectorAll('.target')) {
        for (const type of ['pointerover', 'click']) {
          el.addEventListener(type, () => fetch('/event?name=' + el.id + '&type=' + type));
        }
      }
    </script>'''

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/event?"):
                interactions.append(self.path)
                if "name=safe&type=pointerover" in self.path:
                    safe_seen.set()
                self.send_response(204)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    runtime_dir = tempfile.TemporaryDirectory(prefix="rvh-", dir="/tmp")
    runtime = Path(runtime_dir.name)
    config = tmp_path / "config"
    config.mkdir()
    bh_runtime = runtime / "bh-runtime"
    bh_tmp = runtime / "bh-tmp"
    bh_runtime.mkdir(mode=0o700)
    bh_tmp.mkdir(mode=0o700)
    env = {**os.environ, "XDG_RUNTIME_DIR": str(runtime), "XDG_CONFIG_HOME": str(config),
           "BH_RUNTIME_DIR": str(bh_runtime), "BH_TMP_DIR": str(bh_tmp),
           "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    name = "hover-" + uuid.uuid4().hex[:10]

    def call(*args):
        return subprocess.run([sys.executable, "-m", "reverie.control.cli", "--session", name, *args],
                              cwd=tmp_path, env=env, capture_output=True, text=True, timeout=45)

    try:
        started = call("start", "--headless", "--engine", "laya", "--voice", "off",
                       "--url", f"http://127.0.0.1:{server.server_port}/")
        assert started.returncode == 0, started.stderr
        assert call("--json", "observe").returncode == 0
        safe = call("--json", "visual-hover", "50", "35")
        assert safe.returncode == 0, safe.stderr
        assert safe_seen.wait(3)
        for y in (95, 145, 195):
            assert call("--json", "observe").returncode == 0
            refused = call("--json", "visual-hover", "50", str(y))
            assert refused.returncode != 0
        assert not any("type=click" in event for event in interactions)
        assert not any("name=hidden-label" in event or "name=disabled-label" in event
                       or "name=inert-label" in event for event in interactions)
    finally:
        call("stop")
        server.shutdown()
        server.server_close()
        runtime_dir.cleanup()
