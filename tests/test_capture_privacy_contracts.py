"""Privacy contracts for screenshots taken by a real headless session."""

import errno
import http.server
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest
from PIL import Image

from reverie.control.chromium import find_browser


@pytest.fixture
def privacy_browser(tmp_path):
    try:
        find_browser()
    except RuntimeError:
        pytest.skip("no Chromium-family browser installed")

    html = b'''<!doctype html><style>
      body { margin: 0; background: white; }
      .field, .custom, .frame, #shadow { position: absolute; left: 20px; width: 140px; height: 36px;
        box-sizing: border-box; border: 0; padding: 0; background: rgb(230, 0, 160); }
      #password { top: 20px; } #otp { top: 70px; } #number { top: 120px; }
      #numeric { top: 170px; } #custom { top: 220px; } #foreign { top: 270px; }
      #shadow { top: 320px; } #tracked { top: 370px; } #other { top: 420px; }
      #custom { overflow: hidden; }
    </style>
    <input id="password" class="field" type="password" value="synthetic-password">
    <input id="otp" class="field" autocomplete="one-time-code" value="123456">
    <input id="number" class="field" type="number" aria-label="Security code" value="123456">
    <input id="numeric" class="field" inputmode="numeric" aria-label="Access token" value="987654">
    <div id="custom" class="custom">synthetic custom secret</div>
    <iframe id="foreign" class="frame" src="http://localhost:PORT/foreign"></iframe>
    <!-- CLOSED_SHADOW -->
    <input id="tracked" class="field" aria-label="Private answer">
    <input id="other" class="field" aria-label="Other answer" value="synthetic-other">
    <script>
      document.getElementById('tracked').addEventListener('input', (event) => {
        fetch('/value?value=' + encodeURIComponent(event.target.value));
      });
      setInterval(async () => {
        if (await (await fetch('/should-remove')).text() === 'yes') {
          const target = document.getElementById('tracked');
          if (target) { target.remove(); fetch('/removed'); }
        }
      }, 200);
    </script>'''

    values = []
    removed = threading.Event()
    trigger_removal = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/value?"):
                from urllib.parse import parse_qs, urlsplit
                values.append(parse_qs(urlsplit(self.path).query).get("value", [""])[0])
            if self.path == "/removed":
                removed.set()
            if self.path == "/should-remove":
                content = b"yes" if trigger_removal.is_set() else b"no"
                self.send_response(200)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            content = (b'<body style="margin:0;background:rgb(230,0,160)">synthetic foreign secret</body>'
                       if self.path == "/foreign" else html.replace(b"PORT", str(self.server.server_port).encode()))
            if self.path == "/fields":
                content = b'''<!doctype html><style>
                  body { margin: 0; background: white; }
                  input { position: absolute; left: 20px; width: 180px; height: 40px; box-sizing: border-box;
                    border: 3px solid rgb(0, 220, 220); background: rgb(230, 0, 160); color: black; }
                  input::placeholder { color: black; opacity: 1; }
                  #empty-password { top: 20px; } #empty-otp { top: 80px; }
                  #populated { top: 140px; } #ordinary { top: 200px; } #empty-number { top: 260px; }
                  #zip { top: 320px; } #case { top: 380px; } #status { top: 440px; } #count { top: 500px; }
                </style>
                <input id="empty-password" type="password" placeholder="Enter password">
                <input id="empty-otp" autocomplete="one-time-code" placeholder="Enter code">
                <input id="populated" type="password" value="synthetic-populated-secret">
                <input id="ordinary" value="ordinary value">
                <input id="empty-number" type="number" aria-label="Security code" placeholder="Enter code">
                <input id="zip" inputmode="numeric" aria-label="ZIP code" value="12345">
                <input id="case" aria-label="Case code" value="A713">
                <input id="status" aria-label="Status code" value="200">
                <input id="count" type="number" aria-label="Quantity" value="19">'''
            if self.path == "/closed":
                content = content.replace(b"<!-- CLOSED_SHADOW -->", b"""<div id="shadow"></div><script>
                  document.getElementById('shadow').attachShadow({mode:'closed'}).innerHTML =
                    '<label for="shadow-code" style="position:absolute;left:-9999px">Security code</label>' +
                    '<input id="shadow-code" type="number" value="123456" style="width:100%;height:100%;' +
                    'box-sizing:border-box;border:0;background:rgb(230,0,160)">';
                </script>""")
            if self.path in ("/filtered", "/blur-baseline"):
                content = content.replace(
                    b"#password { top: 20px; }",
                    b"#blur-field { top: 0; left: 0; } .blur-wrapper { position: absolute; left: 20px; "
                    b"top: 20px; width: 140px; height: 36px; filter: blur(25px); }")
                field = b'<input id="password" class="field" type="password" value="synthetic-password">'
                if self.path == "/blur-baseline":
                    field_replacement = b'<input id="blur-field" class="field" type="text" value="ordinary">'
                else:
                    field_replacement = field.replace(b'id="password"', b'id="blur-field"')
                content = content.replace(field, b'<div class="blur-wrapper">' + field_replacement + b'</div>')
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    runtime_dir = tempfile.TemporaryDirectory(prefix="rvp-", dir="/tmp")
    with runtime_dir as short:
        short = Path(short)
        for directory in ("runtime", "bh-runtime", "bh-tmp", "config"):
            (short / directory).mkdir(mode=0o700)
        env = {**os.environ, "XDG_RUNTIME_DIR": str(short / "runtime"),
               "XDG_CONFIG_HOME": str(short / "config"), "BH_RUNTIME_DIR": str(short / "bh-runtime"),
               "BH_TMP_DIR": str(short / "bh-tmp"), "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        env.pop("REVERIE_SECRET_SELECTORS", None)
        name = "privacy-" + uuid.uuid4().hex[:10]

        def call(*args):
            return subprocess.run([sys.executable, "-m", "reverie.control.cli", "--session", name, *args],
                                  cwd=tmp_path, env=env, capture_output=True, text=True, timeout=45)

        def start(selectors=None, path="/"):
            if selectors is not None:
                env["REVERIE_SECRET_SELECTORS"] = selectors
            return call("start", "--headless", "--engine", "laya", "--voice", "off",
                        "--url", f"http://127.0.0.1:{server.server_port}{path}")

        try:
            yield start, call, values, removed, trigger_removal
        finally:
            call("stop")
            server.shutdown()
            server.server_close()
            deadline = time.monotonic() + 5
            while True:
                try:
                    runtime_dir.cleanup()
                    break
                except OSError as error:
                    if error.errno != errno.ENOTEMPTY or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.1)


def _assert_masked(image, y):
    # Sample a text-free corner of the known magenta sensitive rectangle.
    red, green, blue = image.convert("RGB").getpixel((145, y + 25))
    assert not (red > 200 and green < 35 and blue > 125), (red, green, blue)


def test_screenshot_masks_sensitive_fields_and_leaves_nonfield_regions_visible(privacy_browser, tmp_path):
    start, call, _, _, _ = privacy_browser
    started = start('["#custom"]')
    assert started.returncode == 0, started.stderr
    output = tmp_path / "capture.png"
    result = call("--json", "screenshot", str(output))
    assert result.returncode == 0, result.stderr
    with Image.open(output) as image:
        assert image.size[0] > 160 and image.size[1] > 356
        for y in (20, 70, 120, 170):
            _assert_masked(image, y)
        for y in (220, 270, 420):
            red, green, blue = image.convert("RGB").getpixel((145, y + 25))
            assert red > 200 and green < 35 and blue > 125
        assert image.convert("RGB").getpixel((200, 25)) == (255, 255, 255)


def test_trusted_selector_masks_a_populated_field_only(privacy_browser, tmp_path):
    start, call, _, _, _ = privacy_browser
    started = start('["#other"]')
    assert started.returncode == 0, started.stderr
    output = tmp_path / "selected.png"
    result = call("--json", "screenshot", str(output))
    assert result.returncode == 0, result.stderr
    with Image.open(output) as image:
        _assert_masked(image, 420)
        red, green, blue = image.convert("RGB").getpixel((145, 245))
        assert red > 200 and green < 35 and blue > 125
        assert image.convert("RGB").getpixel((200, 25)) == (255, 255, 255)


@pytest.mark.parametrize("selectors", ["not-json", '{"selector":"#custom"}', '["["]'])
def test_invalid_trusted_selectors_are_ignored_without_leaking_metadata(privacy_browser, tmp_path, selectors):
    start, call, _, _, _ = privacy_browser
    started = start(selectors)
    assert started.returncode == 0, started.stderr
    output = tmp_path / "capture.png"
    result = call("--json", "screenshot", str(output))
    assert result.returncode == 0, result.stderr
    assert selectors not in started.stdout + started.stderr + result.stdout + result.stderr
    with Image.open(output) as image:
        _assert_masked(image, 20)
        red, green, blue = image.convert("RGB").getpixel((145, 245))
        assert red > 200 and green < 35 and blue > 125


def test_redacted_fill_masks_target_without_fanout_after_removal(privacy_browser, tmp_path):
    start, call, values, removed, trigger_removal = privacy_browser
    started = start()
    assert started.returncode == 0, started.stderr
    filled = call("--json", "fill", "--label", "Private answer", "--text", "synthetic-private-731", "--redact")
    assert filled.returncode == 0, filled.stderr
    first = tmp_path / "first.png"
    result = call("--json", "screenshot", str(first))
    assert result.returncode == 0, result.stderr
    with Image.open(first) as image:
        _assert_masked(image, 370)
    trigger_removal.set()
    assert removed.wait(8)
    assert "synthetic-private-731" in values
    second = tmp_path / "second.png"
    result = call("--json", "screenshot", str(second))
    assert result.returncode == 0, result.stderr
    with Image.open(second) as image:
        red, green, blue = image.convert("RGB").getpixel((145, 445))
        assert red > 200 and green < 35 and blue > 125
        _assert_masked(image, 20)


def test_blurred_ordinary_field_has_visible_spill_beyond_padding(privacy_browser, tmp_path):
    start, call, _, _, _ = privacy_browser
    started = start(path="/blur-baseline")
    assert started.returncode == 0, started.stderr
    output = tmp_path / "blur-baseline.png"
    result = call("--json", "screenshot", str(output))
    assert result.returncode == 0, result.stderr
    with Image.open(output) as image:
        red, green, blue = image.convert("RGB").getpixel((174, 38))
        assert red - green >= 10 and blue - green >= 10, (red, green, blue)


def test_register_secret_invalidates_cached_images_without_deleting_history(tmp_path):
    from test_control import session

    s = session(tmp_path)
    s.frame = "previous-capture"
    s.step_frames = ["earlier.jpg"]
    frames = tmp_path / "frames"
    frames.mkdir()
    historical = frames / "earlier.jpg"
    historical.write_bytes(b"historical evidence")
    s.register_secret(value="synthetic-private-731")
    assert not s.frame
    assert not s.step_frames
    assert historical.read_bytes() == b"historical evidence"


def test_closed_shadow_labeled_numeric_code_is_local_to_its_field(privacy_browser, tmp_path):
    start, call, _, _, _ = privacy_browser
    started = start(path="/closed")
    assert started.returncode == 0, started.stderr
    output = tmp_path / "closed.png"
    result = call("--json", "screenshot", str(output))
    assert result.returncode == 0, result.stderr
    with Image.open(output) as image:
        _assert_masked(image, 320)
        red, green, blue = image.convert("RGB").getpixel((145, 445))
        assert red > 200 and green < 35 and blue > 125
        assert image.convert("RGB").getpixel((200, 25)) == (255, 255, 255)
        _assert_masked(image, 20)


def test_standalone_browser_tracks_target_for_reformatted_known_secret(tmp_path):
    try:
        find_browser()
    except RuntimeError:
        pytest.skip("no Chromium-family browser installed")

    html = b'''<!doctype html><style>
      body { margin: 0; background: white; }
      input { position: absolute; left: 20px; top: 20px; width: 140px; height: 36px;
              box-sizing: border-box; border: 0; background: rgb(230,0,160); }
    </style><input aria-label="Reference" value="synthetic-registered-731">
    <input aria-label="Ordinary" value="ordinary" style="top:70px">
    <input aria-label="Unrelated" value="unrelated" style="top:120px">
    <script>document.querySelector('input').addEventListener('input', event => {
      event.target.value = 'normalized';
    });</script>'''

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    child = '''
import base64
import io
import logging
import os
import sys
import threading
import time
from pathlib import Path
from reverie.capture import CapturePrivacyError
from reverie.control.chromium import Chromium

chromium = Chromium(Path(sys.argv[2]), headed=False)
browser = None
try:
    os.environ["BU_CDP_URL"] = chromium.cdp_url
    from reverie.agent import Agent
    from reverie.browser import Browser
    browser = Browser(sys.argv[1])
    agent = Agent(sys.argv[1], "Review the page", screenshots=True, observation_mode="image",
                  decision_engine="jev", browser=browser)
    before = agent.snapshot()["page"]["screenshot"]
    assert before
    Path(sys.argv[3] + ".before").write_bytes(base64.b64decode(before))
    entered = threading.Event()
    release = threading.Event()
    snapshot_done = threading.Event()
    registration_errors = []
    snapshot_result = []
    previous_callback = getattr(browser, "on_secret_registered", None)

    def paused_callback():
        entered.set()
        if not release.wait(10):
            raise AssertionError("registration callback was not released")
        if previous_callback:
            previous_callback()

    def register():
        try:
            browser.register_secret(value="synthetic-registered-731")
        except Exception as error:
            registration_errors.append(error)

    def snapshot_while_pending():
        try:
            snapshot_result.append(agent.snapshot()["page"].get("screenshot"))
        except CapturePrivacyError:
            snapshot_result.append(None)
        except Exception as error:
            snapshot_result.append(error)
        finally:
            snapshot_done.set()

    browser.on_secret_registered = paused_callback
    registration_thread = threading.Thread(target=register, daemon=True)
    snapshot_thread = None
    registration_thread.start()
    try:
        assert entered.wait(3), "registration callback did not start"
        snapshot_thread = threading.Thread(target=snapshot_while_pending, daemon=True)
        snapshot_thread.start()
        completed_while_pending = snapshot_done.wait(2)
    finally:
        release.set()
        registration_thread.join(3)
        if snapshot_thread is not None:
            snapshot_thread.join(3)
    assert not registration_thread.is_alive()
    assert not registration_errors, registration_errors
    assert completed_while_pending, "snapshot blocked during registration"
    assert snapshot_result == [None], snapshot_result
    assert browser.secret_matches("synthetic-registered-731")
    assert browser.secret_matches(chr(0xff53) + "ynthetic-registered-731")
    assert not browser.secret_matches("prefix-synthetic-registered-731-suffix")
    assert not browser.secret_matches("SYNTHETIC-REGISTERED-731")
    assert not browser.secret_matches("syntheticregistered731")
    deadline = time.monotonic() + 3
    while True:
        try:
            after = agent.snapshot()["page"].get("screenshot")
            if after:
                break
        except CapturePrivacyError:
            if time.monotonic() >= deadline:
                raise
        if time.monotonic() >= deadline:
            raise AssertionError("agent did not obtain a fresh masked screenshot")
        time.sleep(0.1)
    Path(sys.argv[3] + ".after").write_bytes(base64.b64decode(after))
    browser.close()
    browser = Browser(sys.argv[1])
    browser.register_secret(value="synthetic-registered-731")
    page = browser.observe()
    action = next(a for a in page["actions"] if a.get("kind") == "fill" and "Reference" in a.get("label", ""))
    browser.act(action, page, text="synthetic-registered-731")
    assert browser.evaluate("document.querySelector('input').value") == "normalized"
    browser.observe(screenshot=False)
    deadline = time.monotonic() + 3
    while True:
        try:
            capture = browser.capture_masked(format="png")
            break
        except CapturePrivacyError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)
    Path(sys.argv[3]).write_bytes(base64.b64decode(capture))
    browser.close()
    browser = Browser(sys.argv[1])
    browser.register_secret(value="synthetic-registered-731")
    page = browser.observe()
    action = next(a for a in page["actions"] if a.get("kind") == "fill" and "Ordinary" in a.get("label", ""))
    real_register, real_evaluate = browser.register_secret, browser.evaluate
    faults = []
    log_output = io.StringIO()
    handler = logging.StreamHandler(log_output)
    handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(handler)

    def register_with_identity_failure(*args, **kwargs):
        faults.append(True)
        def fail_identity(*args, **kwargs):
            raise RuntimeError("synthetic-private-identity-error")
        browser.evaluate = fail_identity
        try:
            return real_register(*args, **kwargs)
        finally:
            browser.evaluate = real_evaluate

    browser.register_secret = register_with_identity_failure
    try:
        browser.act(action, page, text="synthetic-registered-731")
    finally:
        logging.getLogger().removeHandler(handler)
    assert faults, "known-secret fill did not register its target"
    assert log_output.getvalue(), "identity failure did not warn"
    assert "synthetic-private-identity-error" not in log_output.getvalue()
    assert "synthetic-registered-731" not in log_output.getvalue()
    assert browser.secret_matches("synthetic-registered-731")
    assert browser.evaluate("document.querySelector('[aria-label=Ordinary]').value") == "synthetic-registered-731"
    browser.observe(screenshot=False)
    fault_capture = browser.capture_masked(format="png")
    Path(sys.argv[3] + ".fault").write_bytes(base64.b64decode(fault_capture))
finally:
    if browser is not None:
        browser.close()
    chromium.close()
'''
    try:
        with tempfile.TemporaryDirectory(prefix="rvp-", dir="/tmp") as short:
            short = Path(short)
            for directory in ("bh-runtime", "bh-tmp", "runtime"):
                (short / directory).mkdir(mode=0o700)
            env = {**os.environ, "BU_NAME": "rvp" + uuid.uuid4().hex[:10],
                   "BH_RUNTIME_DIR": str(short / "bh-runtime"), "BH_TMP_DIR": str(short / "bh-tmp"),
                   "XDG_RUNTIME_DIR": str(short / "runtime"),
                   "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
            env.pop("REVERIE_SECRET_SELECTORS", None)
            output = tmp_path / "standalone.png"
            result = subprocess.run([sys.executable, "-c", child, f"http://127.0.0.1:{server.server_port}/",
                                     str(short / "profile"), str(output)], cwd=tmp_path, env=env,
                                    capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, result.stderr
            with Image.open(str(output) + ".before") as image:
                red, green, blue = image.convert("RGB").getpixel((145, 45))
                assert red > 200 and green < 35 and blue > 125
            with Image.open(str(output) + ".after") as image:
                _assert_masked(image, 20)
            with Image.open(output) as image:
                _assert_masked(image, 20)
                assert image.convert("RGB").getpixel((200, 25)) == (255, 255, 255)
            with Image.open(str(output) + ".fault") as image:
                _assert_masked(image, 70)
                red, green, blue = image.convert("RGB").getpixel((145, 145))
                assert red > 200 and green < 35 and blue > 125
                assert image.convert("RGB").getpixel((200, 25)) == (255, 255, 255)
    finally:
        server.shutdown()
        server.server_close()


def test_empty_fields_keep_placeholder_and_populated_field_has_striped_mask(privacy_browser, tmp_path):
    start, call, _, _, _ = privacy_browser
    started = start(path="/fields")
    assert started.returncode == 0, started.stderr
    output = tmp_path / "fields.png"
    result = call("--json", "screenshot", str(output))
    assert result.returncode == 0, result.stderr
    with Image.open(output) as image:
        rgb = image.convert("RGB")
        for top in (20, 80, 260):
            assert rgb.getpixel((170, top + 20)) == (230, 0, 160)
            assert rgb.getpixel((21, top + 20)) == (0, 220, 220)
            # The placeholder must remain visible against the field background.
            assert any(max(rgb.getpixel((x, y))) < 100
                       for x in range(27, 110) for y in range(top + 8, top + 32))
        assert rgb.getpixel((21, 160)) == (0, 220, 220)
        pixels = [rgb.getpixel((x, y)) for x in range(26, 194) for y in range(146, 174)]
        assert not any(r > 200 and g < 35 and b > 125 for r, g, b in pixels)
        left_colors = {rgb.getpixel((x, y)) for x in range(26, 110) for y in range(146, 174)}
        right_colors = {rgb.getpixel((x, y)) for x in range(110, 194) for y in range(146, 174)}
        assert left_colors <= right_colors  # Text-bearing pixels have the same opaque mask palette.
        assert len(set(pixels)) >= 2
        assert any(rgb.getpixel((x, y)) != rgb.getpixel((x + 1, y))
                   for x in range(110, 189) for y in range(148, 172))
        assert any(rgb.getpixel((x, y)) != rgb.getpixel((x, y + 1))
                   for x in range(110, 190) for y in range(148, 171))
        for top in (200, 320, 380, 440, 500):
            assert rgb.getpixel((170, top + 20)) == (230, 0, 160)


@pytest.mark.parametrize("requested,expected", [("png", "PNG"), ("jpeg", "JPEG")])
def test_capture_uses_lossless_source_and_preserves_requested_output_format(requested, expected):
    import base64
    import io

    from reverie.capture import capture_masked

    source = io.BytesIO()
    Image.new("RGB", (64, 48), (61, 131, 211)).save(source, format="PNG")
    screenshot_calls = []
    geometry = {"width": 64, "height": 48, "rects": [], "documents": []}
    evaluation_results = iter([geometry, geometry])

    def evaluate(_expression):
        return next(evaluation_results, geometry)

    def call(method, **params):
        if method == "DOM.getDocument":
            return {"root": {"nodeId": 1, "children": []}}
        if method == "Page.captureScreenshot":
            screenshot_calls.append(params)
            return {"data": base64.b64encode(source.getvalue()).decode()}
        raise AssertionError(f"unexpected CDP method: {method}")

    encoded = capture_masked(call, evaluate, format=requested, quality=73)
    assert screenshot_calls
    assert all(params.get("format") == "png" and "quality" not in params for params in screenshot_calls)
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as output:
        assert output.format == expected
        assert output.size == (64, 48)


def test_geometry_failure_warns_and_returns_fresh_capture_without_sensitive_diagnostics(caplog):
    import base64
    import io

    from reverie.capture import capture_masked

    images = []
    for color in ((25, 75, 125), (195, 135, 65)):
        output = io.BytesIO()
        Image.new("RGB", (16, 16), color).save(output, format="PNG")
        images.append(base64.b64encode(output.getvalue()).decode())
    captures = iter(images)

    def call(method, **params):
        if method == "DOM.getDocument":
            return {"root": {"nodeId": 1, "children": []}}
        if method == "Page.captureScreenshot":
            return {"data": next(captures)}
        raise AssertionError(f"unexpected CDP method: {method}")

    def evaluate(_expression):
        raise RuntimeError("synthetic-private-selector-731")

    with caplog.at_level("WARNING"):
        first = capture_masked(call, evaluate, format="png")
        second = capture_masked(call, evaluate, format="png")
    for encoded, expected in ((first, (25, 75, 125)), (second, (195, 135, 65))):
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
            assert image.convert("RGB").getpixel((5, 5)) == expected
    assert caplog.records
    assert "synthetic-private-selector-731" not in caplog.text


def test_output_conversion_failure_returns_original_png(monkeypatch):
    import base64
    import io

    from reverie.capture import capture_masked

    source = io.BytesIO()
    Image.new("RGB", (16, 16), (29, 79, 129)).save(source, format="PNG")
    geometry = {"width": 16, "height": 16, "rects": [], "documents": []}

    def call(method, **params):
        if method == "DOM.getDocument":
            return {"root": {"nodeId": 1, "children": []}}
        if method == "Page.captureScreenshot":
            return {"data": base64.b64encode(source.getvalue()).decode()}
        raise AssertionError(f"unexpected CDP method: {method}")

    def fail_save(*args, **kwargs):
        raise OSError("synthetic encoder failure")

    monkeypatch.setattr(Image.Image, "save", fail_save)
    encoded = capture_masked(call, lambda expression: geometry, format="jpeg")
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        assert image.format == "PNG"
        assert image.convert("RGB").getpixel((5, 5)) == (29, 79, 129)


def _encoded_image(fmt):
    import base64
    import io

    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), (21, 71, 121)).save(buffer, format=fmt)
    return base64.b64encode(buffer.getvalue()).decode()


@pytest.mark.parametrize("fmt,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_image_mime_and_hosted_chat_use_actual_image_bytes(monkeypatch, fmt, mime):
    import base64

    from reverie import image_format, model

    encoded = _encoded_image(fmt)
    assert image_format.image_mime(encoded) == mime
    assert image_format.image_mime(base64.b64decode(encoded)) == mime
    uri = f"data:{mime};base64,{encoded}"
    assert image_format.image_data_uri(encoded) == uri
    sent = {}
    monkeypatch.setenv("REVERIE_PILOT_PROVIDER", "opencode-go")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "synthetic-test-key")

    def post(url, key, body, headers=None):
        sent.update(body)
        return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    monkeypatch.setattr(model, "post_json", post)
    output, _ = model.chat_json("system", {}, model="glm-5.3-flash", role="pilot", images=(encoded,))
    assert output == {"ok": True}
    images = [part["image_url"]["url"] for message in sent["messages"]
              if isinstance(message.get("content"), list) for part in message["content"]
              if part.get("type") == "image_url"]
    assert uri in images


def test_codex_receives_png_data_uri_for_png_bytes(tmp_path, monkeypatch):
    import json

    from test_pilot_contracts import _fake_codex_server

    from reverie import codex_provider

    executable, transcript = _fake_codex_server(tmp_path, "success")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("REVERIE_CODEX_COMMAND", str(executable))
    monkeypatch.setenv("REVERIE_CODEX_TIMEOUT", "3")
    encoded = _encoded_image("PNG")
    codex_provider.close()
    codex_provider.resume()
    try:
        decision, _ = codex_provider.chat_json("system", "context", images=(encoded,))
        assert decision == {"op": "wait"}
        turns = [json.loads(line) for line in transcript.read_text().splitlines()]
        inputs = next(message["params"]["input"] for message in turns if message.get("method") == "turn/start")
        assert {"type": "image", "url": f"data:image/png;base64,{encoded}"} in inputs
    finally:
        codex_provider.close()
        codex_provider.resume()


def test_dashboard_frame_content_type_follows_bytes_not_extension(tmp_path):
    import asyncio
    import base64

    from aiohttp.test_utils import TestClient, TestServer

    from reverie.control.dashboard import create_app

    run = tmp_path / ".reverie" / "runs" / "synthetic-run"
    (run / "frames").mkdir(parents=True)
    content = base64.b64decode(_encoded_image("PNG"))
    (run / "frames" / "capture.jpg").write_bytes(content)

    async def exercise():
        app = create_app([run.parent], token="synthetic-token", project_root=tmp_path)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/api/frame", params={"dir": run.name, "file": "capture.jpg"},
                                        headers={"X-Laya-Agent-Token": "synthetic-token"})
            assert response.status == 200
            assert response.content_type == "image/png"
            assert await response.read() == content

    asyncio.run(exercise())


def test_cdp_screenshot_failure_propagates():
    from reverie.capture import capture_masked

    geometry = {"width": 16, "height": 16, "rects": [], "documents": []}

    def call(method, **params):
        if method == "DOM.getDocument":
            return {"root": {"nodeId": 1, "children": []}}
        if method == "Page.captureScreenshot":
            raise RuntimeError("synthetic screenshot transport failure")
        raise AssertionError(f"unexpected CDP method: {method}")

    with pytest.raises(RuntimeError, match="synthetic screenshot transport failure"):
        capture_masked(call, lambda expression: geometry, format="png")


def test_mcp_inspection_reports_actual_mime_for_each_image(tmp_path, monkeypatch):
    from reverie.control.mcp import MCPAdapter

    raw = _encoded_image("PNG")
    crop = _encoded_image("JPEG")

    def rpc(self, browser_session, command, arguments, operation_id, *, epoch=None, observation_id=None):
        return {"raw_frame": raw, "crop": crop}

    monkeypatch.setattr(MCPAdapter, "_rpc", rpc)
    result = MCPAdapter(root=tmp_path).call_tool("worker_inspect", {
        "browser_session": "demo", "operation_id": "op1", "ref": "e1"})
    images = [block for block in result["content"] if block.get("type") == "image"]
    assert {block["data"]: block["mimeType"] for block in images} == {
        raw: "image/png", crop: "image/jpeg"}


def test_jpeg_conversion_failure_retains_painted_png(monkeypatch):
    import base64
    import io

    from reverie.capture import capture_masked

    source = io.BytesIO()
    Image.new("RGB", (48, 48), (230, 0, 160)).save(source, format="PNG")
    geometry = {"width": 48, "height": 48, "rects": [[5, 5, 25, 25, True]], "documents": []}

    def call(method, **params):
        if method == "DOM.getDocument":
            return {"root": {"nodeId": 1, "children": []}}
        if method == "Page.captureScreenshot":
            return {"data": base64.b64encode(source.getvalue()).decode()}
        raise AssertionError(f"unexpected CDP method: {method}")

    original_save = Image.Image.save

    def fail_jpeg(image, fp, format=None, **params):
        if format and format.upper() in ("JPEG", "JPG"):
            raise OSError("synthetic JPEG failure")
        return original_save(image, fp, format=format, **params)

    monkeypatch.setattr(Image.Image, "save", fail_jpeg)
    encoded = capture_masked(call, lambda expression: geometry, format="jpeg")
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        assert image.format == "PNG"
        rgb = image.convert("RGB")
        for x in range(8, 22):
            for y in range(8, 22):
                assert rgb.getpixel((x, y)) != (230, 0, 160)
        assert rgb.getpixel((35, 35)) == (230, 0, 160)


def test_invalid_selector_configuration_warns_without_exposing_value(monkeypatch, caplog):
    from reverie.capture import secret_selectors

    selector = "synthetic-private-invalid-selector-731"
    monkeypatch.setenv("REVERIE_SECRET_SELECTORS", selector)
    with caplog.at_level("WARNING"):
        secret_selectors()
    assert caplog.records
    assert selector not in caplog.text
