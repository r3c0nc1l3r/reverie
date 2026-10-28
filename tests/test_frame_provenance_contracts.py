"""Contracts for current-session visual-review evidence."""

import base64
import io
import os

import pytest
from PIL import Image
from test_control import session

from reverie import model
from reverie.control import pilot


def _image(color):
    output = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(output, format="JPEG")
    return base64.b64encode(output.getvalue()).decode()


def _session(tmp_path):
    from reverie.control.session import Session

    s = session(tmp_path)
    s.page["marker"] = "marker-1"
    s.browser.observe.return_value = s.page
    s.browser.evaluate.return_value = "marker-1"
    s.browser.visual_state.return_value = "state-1"
    s.browser.capture_masked.return_value = _image("white")
    Session.observe(s)
    s.observe = lambda settle=False: Session.observe(s, settle=settle)
    s.plan("Review", ["Inspect the page"])
    return s


def _capture(s, color):
    s.browser.capture_masked.return_value = _image(color)
    s.capture()
    assert s.last_capture_ok
    name = s.save_frame("step")
    assert name
    return name


def _pixel(data):
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGB").getpixel((20, 15))


def test_registered_frame_reuse_requires_unchanged_bytes(tmp_path):
    s = _session(tmp_path)
    name = _capture(s, "white")
    same = s.save_frame("step")
    assert same == name
    stored = tmp_path / "frames" / name
    stored.write_bytes(base64.b64decode(_image("red")))
    replacement = s.save_frame("step")
    assert replacement and replacement != name
    assert _pixel(stored.read_bytes())[0] > 200
    assert min(_pixel((tmp_path / "frames" / replacement).read_bytes())) > 220


@pytest.mark.parametrize("kind", ["unregistered", "tampered", "missing", "symlink", "fifo", "traversal"])
def test_untrusted_final_evidence_refreshes_current_capture(tmp_path, kind):
    s = _session(tmp_path)
    original = _capture(s, "white")
    frames = tmp_path / "frames"
    path = frames / original
    if kind == "tampered":
        path.write_bytes(base64.b64decode(_image("red")))
        candidate = original
    elif kind == "missing":
        path.unlink()
        candidate = original
    elif kind == "unregistered":
        candidate = "foreign.jpg"
        (frames / candidate).write_bytes(base64.b64decode(_image("red")))
    elif kind == "symlink":
        outside = tmp_path / "outside.jpg"
        outside.write_bytes(base64.b64decode(_image("red")))
        candidate = "linked.jpg"
        (frames / candidate).symlink_to(outside)
    elif kind == "fifo":
        candidate = "pipe.jpg"
        os.mkfifo(frames / candidate)
    else:
        candidate = "../outside.jpg"
        (tmp_path / "outside.jpg").write_bytes(base64.b64decode(_image("red")))
    s.browser.capture_masked.return_value = _image("black")
    reviewed = s.review_frames([candidate])
    assert reviewed
    assert max(_pixel(reviewed[-1][1])) < 20
    assert reviewed[-1][0] != candidate


def test_invalid_final_and_failed_capture_never_falls_back_to_earlier_frame(tmp_path, monkeypatch):
    s = _session(tmp_path)
    original = _capture(s, "white")
    foreign = tmp_path / "frames" / "foreign.jpg"
    foreign.write_bytes(base64.b64decode(_image("red")))
    s.browser.capture_masked.side_effect = RuntimeError("synthetic capture failed")
    seen = []
    monkeypatch.setattr(model, "chat_json", lambda *args, **kwargs: (
        seen.append(kwargs) or {"issues": [], "summary": "clear"}, {}))
    assert not s.review_frames([original, foreign.name])
    assert pilot.ui_review(s, s.test["steps"][0], [original, foreign.name]) is None
    assert seen == []


def test_review_issues_reference_included_registered_frames_after_omissions(tmp_path, monkeypatch):
    s = _session(tmp_path)
    first = _capture(s, "white")
    last = _capture(s, "black")
    (tmp_path / "frames" / "foreign.jpg").write_bytes(base64.b64decode(_image("red")))
    seen = []

    def review(system, context, **kwargs):
        seen.extend(kwargs["images"])
        return {"issues": [{"severity": "high", "image": 2, "what": "Synthetic issue"}],
                "summary": "issue"}, {}

    monkeypatch.setattr(model, "chat_json", review)
    result = pilot.ui_review(s, s.test["steps"][0], [first, "foreign.jpg", last])
    assert len(seen) == 2
    assert result["issues"][0]["frame"] == last


def test_save_frame_never_replaces_existing_symlink(tmp_path):
    s = _session(tmp_path)
    name = _capture(s, "white")
    stored = tmp_path / "frames" / name
    stored.unlink()
    outside = tmp_path / "outside.jpg"
    original = base64.b64decode(_image("red"))
    outside.write_bytes(original)
    stored.symlink_to(outside)
    replacement = s.save_frame("step")
    assert replacement and replacement != name
    assert stored.is_symlink()
    assert outside.read_bytes() == original


def test_explicit_screenshot_in_frames_registers_review_evidence(tmp_path):
    s = _session(tmp_path)
    _capture(s, "white")
    path = tmp_path / "frames" / "explicit.jpg"
    s.browser.capture_masked.return_value = _image("black")
    result = s.screenshot(str(path))
    assert result["path"] == str(path)
    s.browser.capture_masked.reset_mock()
    frames = s.review_frames([path.name])
    assert frames and frames[-1][0] == path.name
    assert max(_pixel(frames[-1][1])) < 20
    s.browser.capture_masked.assert_not_called()


@pytest.mark.parametrize("covered", [False, True])
def test_hover_then_click_preserves_navigation_and_protected_hit_guard(tmp_path, covered):
    import errno
    import http.server
    import subprocess
    import sys
    import tempfile
    import threading
    import time
    import uuid
    from pathlib import Path

    from reverie.control.chromium import find_browser

    try:
        find_browser()
    except RuntimeError:
        pytest.skip("no Chromium-family browser installed")
    navigated, bad_click = threading.Event(), threading.Event()
    html = b'''<!doctype html><style>
      body { margin: 0; } .target { position: absolute; left: 20px; top: 20px; width: 120px; height: 40px; }
      @keyframes glow { 0%,100% { opacity: 0.8; } 50% { opacity: 1; } }
      #logout { animation: glow .4s linear infinite; }
      #overlay { z-index: 2; }
    </style>
    <a class="target" id="logout" href="/signed-out">LOGOUT</a>'''
    if covered:
        html += b'<input class="target" id="overlay" type="password" aria-label="Protected">'

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/signed-out":
                (bad_click if covered else navigated).set()
            body = b"Signed out" if self.path == "/signed-out" else html
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    runtime = tempfile.TemporaryDirectory(prefix="rve-", dir="/tmp")
    short = Path(runtime.name)
    for directory in ("xdg", "bh-runtime", "bh-tmp", "config"):
        (short / directory).mkdir(mode=0o700)
    env = {**os.environ, "XDG_RUNTIME_DIR": str(short / "xdg"), "XDG_CONFIG_HOME": str(short / "config"),
           "BH_RUNTIME_DIR": str(short / "bh-runtime"), "BH_TMP_DIR": str(short / "bh-tmp"),
           "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    name = "hover-" + uuid.uuid4().hex[:10]

    def call(*args):
        return subprocess.run([sys.executable, "-m", "reverie.control.cli", "--session", name, *args],
                              cwd=tmp_path, env=env, capture_output=True, text=True, timeout=45)

    try:
        started = call("start", "--headless", "--engine", "laya", "--voice", "off",
                       "--url", f"http://127.0.0.1:{server.server_port}/")
        assert started.returncode == 0, started.stderr
        assert call("goal", "Log out").returncode == 0
        assert call("--json", "observe").returncode == 0
        hovered = call("--json", "hover", "--label", "LOGOUT")
        if covered:
            assert hovered.returncode != 0
            clicked = call("--json", "act", "--label", "LOGOUT")
            assert clicked.returncode != 0
            assert not bad_click.is_set()
        else:
            assert hovered.returncode == 0, hovered.stderr
            clicked = call("--json", "act", "--label", "LOGOUT")
            assert clicked.returncode == 0, clicked.stderr
            assert navigated.wait(3)
    finally:
        call("stop")
        server.shutdown()
        server.server_close()
        deadline = time.monotonic() + 5
        while True:
            try:
                runtime.cleanup()
                break
            except OSError as error:
                if error.errno != errno.ENOTEMPTY or time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)


def test_changed_visual_signature_with_same_marker_cannot_be_blessed_by_recapture(tmp_path, monkeypatch):
    from reverie.control.session import SessionError

    s = _session(tmp_path)
    s.visual_mode = "primary"
    s.mark(1, "running")
    s.checks = [{"passed": True}]
    _capture(s, "white")
    s.browser.capture_masked.reset_mock()
    s.browser.visual_state.return_value = "changed-state"
    seen = []
    monkeypatch.setattr(model, "chat_json", lambda *args, **kwargs: (
        seen.append(kwargs) or {"issues": [], "summary": "clear"}, {}))
    try:
        s.mark(1, "pass", "done")
    except SessionError:
        pass
    assert not seen
    assert s.test["steps"][0].get("status") != "pass"
    s.browser.capture_masked.assert_not_called()


def test_explicit_screenshot_does_not_replace_registered_historical_frame(tmp_path):
    from reverie.control.session import SessionError

    s = _session(tmp_path)
    name = _capture(s, "white")
    historical = tmp_path / "frames" / name
    before = historical.read_bytes()
    s.browser.capture_masked.return_value = _image("black")
    try:
        s.screenshot(str(historical))
    except (SessionError, OSError):
        pass
    assert historical.read_bytes() == before
    assert s.review_frames([name])[-1] == (name, before)


def test_explicit_screenshot_export_outside_frames_may_replace_file(tmp_path):
    s = _session(tmp_path)
    _capture(s, "white")
    export = tmp_path / "export.jpg"
    export.write_bytes(base64.b64decode(_image("white")))
    s.browser.capture_masked.return_value = _image("black")
    result = s.screenshot(str(export))
    assert result["path"] == str(export)
    assert max(_pixel(export.read_bytes())) < 20


def test_failed_frame_write_leaves_no_partial_or_temporary_evidence(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    project = Path(__file__).resolve().parents[1]
    child = '''
import resource
import signal
import sys
from pathlib import Path
from test_frame_provenance_contracts import _capture, _image, _session

s = _session(Path(sys.argv[1]))
first = _capture(s, "white")
frames = Path(sys.argv[1]) / "frames"
original = (frames / first).read_bytes()
before = {p.name for p in frames.iterdir()}
s.browser.capture_masked.return_value = _image("black")
s.capture()
assert s.last_capture_ok
import base64
assert len(base64.b64decode(s.frame)) > 128
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
resource.setrlimit(resource.RLIMIT_FSIZE, (128, hard))
try:
    try:
        result = s.save_frame("step")
        assert result is None
    except OSError:
        pass
finally:
    resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))
assert {p.name for p in frames.iterdir()} == before
assert (frames / first).read_bytes() == original
'''
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(project), str(project / "tests")))}
    result = subprocess.run([sys.executable, "-c", child, str(tmp_path)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind", ["regular", "symlink"])
def test_explicit_screenshot_does_not_replace_any_occupied_frame_name(tmp_path, kind):
    from reverie.control.session import SessionError

    s = _session(tmp_path)
    _capture(s, "white")
    destination = tmp_path / "frames" / "occupied.jpg"
    original = base64.b64decode(_image("red"))
    if kind == "symlink":
        outside = tmp_path / "outside.jpg"
        outside.write_bytes(original)
        destination.symlink_to(outside)
    else:
        destination.write_bytes(original)
    s.browser.capture_masked.return_value = _image("black")
    try:
        s.screenshot(str(destination))
    except (SessionError, OSError):
        pass
    if kind == "symlink":
        assert destination.is_symlink()
        assert outside.read_bytes() == original
    else:
        assert destination.read_bytes() == original


def test_symlinked_frames_directory_never_reads_or_writes_through_it(tmp_path):
    from reverie.control.session import SessionError

    s = _session(tmp_path)
    frames = tmp_path / "frames"
    if frames.exists():
        frames.rmdir()
    outside = tmp_path / "untrusted-directory"
    outside.mkdir()
    frames.symlink_to(outside, target_is_directory=True)
    s.capture()
    try:
        result = s.save_frame("step")
        assert result is None
    except (SessionError, OSError):
        pass
    try:
        assert not s.review_frames(["foreign.jpg"])
    except (SessionError, OSError):
        pass
    assert frames.is_symlink()
    assert list(outside.iterdir()) == []
