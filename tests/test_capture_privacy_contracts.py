"""Privacy contracts for screenshots taken by a real headless session."""

import http.server
import os
import subprocess
import sys
import tempfile
import threading
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
                </style>
                <input id="empty-password" type="password" placeholder="Enter password">
                <input id="empty-otp" autocomplete="one-time-code" placeholder="Enter code">
                <input id="populated" type="password" value="synthetic-populated-secret">
                <input id="ordinary" value="ordinary value">
                <input id="empty-number" type="number" aria-label="Security code" placeholder="Enter code">'''
            if self.path == "/closed":
                content = content.replace(b"<!-- CLOSED_SHADOW -->", b"""<div id="shadow"></div><script>
                  document.getElementById('shadow').attachShadow({mode:'closed'}).innerHTML =
                    '<div style="width:100%;height:100%;background:rgb(230,0,160)">secret</div>';
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
    with tempfile.TemporaryDirectory(prefix="rvp-", dir="/tmp") as short:
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


def _assert_masked(image, y):
    # Sample a text-free corner of the known magenta sensitive rectangle.
    red, green, blue = image.convert("RGB").getpixel((145, y + 25))
    assert not (red > 200 and green < 35 and blue > 125), (red, green, blue)


def test_screenshot_masks_sensitive_fields_custom_region_and_cross_origin_frame(privacy_browser, tmp_path):
    start, call, _, _, _ = privacy_browser
    started = start('["#custom"]')
    assert started.returncode == 0, started.stderr
    output = tmp_path / "capture.png"
    result = call("--json", "screenshot", str(output))
    assert result.returncode == 0, result.stderr
    with Image.open(output) as image:
        assert image.size[0] > 160 and image.size[1] > 356
        for y in (20, 70, 120, 170, 220, 270):
            _assert_masked(image, y)
        assert image.convert("RGB").getpixel((200, 25)) == (255, 255, 255)
        red, green, blue = image.convert("RGB").getpixel((145, 445))
        assert red > 200 and green < 35 and blue > 125


@pytest.mark.parametrize("selectors", ["not-json", '{"selector":"#custom"}', '["["]'])
def test_invalid_trusted_selectors_withhold_screenshot(privacy_browser, tmp_path, selectors):
    start, call, _, _, _ = privacy_browser
    started = start(selectors)
    output = tmp_path / "capture.png"
    if started.returncode == 0:
        result = call("--json", "screenshot", str(output))
        assert result.returncode != 0 or not output.exists()
        assert selectors not in result.stdout + result.stderr
    else:
        assert selectors not in started.stdout + started.stderr
    assert not output.exists()


def test_redacted_fill_masks_current_and_replacement_fields(privacy_browser, tmp_path):
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
        _assert_masked(image, 420)


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


def test_filtered_password_ancestor_cannot_leak_outside_field(privacy_browser, tmp_path):
    start, call, _, _, _ = privacy_browser
    started = start(path="/filtered")
    assert started.returncode == 0, started.stderr
    output = tmp_path / "filtered.png"
    result = call("--json", "screenshot", str(output))
    if result.returncode != 0:
        assert not output.exists()
        return
    with Image.open(output) as image:
        # The blur extends beyond the field and the usual 12px padding.
        red, green, blue = image.convert("RGB").getpixel((174, 38))
        assert red - green < 10 or blue - green < 10, (red, green, blue)


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


def test_closed_shadow_content_is_masked_or_capture_is_withheld(privacy_browser, tmp_path):
    start, call, _, _, _ = privacy_browser
    started = start(path="/closed")
    assert started.returncode == 0, started.stderr
    output = tmp_path / "closed.png"
    result = call("--json", "screenshot", str(output))
    if result.returncode != 0:
        assert not output.exists()
        return
    with Image.open(output) as image:
        _assert_masked(image, 320)


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
            assert rgb.getpixel((190, top + 20)) == (230, 0, 160)
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
        assert rgb.getpixel((190, 220)) == (230, 0, 160)  # An unprotected control stays visible.


@pytest.mark.parametrize("requested,expected", [("png", "PNG"), ("jpeg", "JPEG")])
def test_capture_uses_lossless_source_and_preserves_requested_output_format(requested, expected):
    import base64
    import io

    from reverie.capture import capture_masked

    source = io.BytesIO()
    Image.new("RGB", (64, 48), (61, 131, 211)).save(source, format="PNG")
    screenshot_calls = []
    geometry = {"width": 64, "height": 48, "rects": [], "documents": []}
    evaluation_results = iter([True, geometry, geometry, True])

    def evaluate(_expression):
        return next(evaluation_results, True)

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
