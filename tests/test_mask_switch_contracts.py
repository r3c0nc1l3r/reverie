"""Startup mask-switch contracts across session capture and visual review."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("setting,masked", [
    (None, True), ("0", False), ("  FaLsE  ", False), (" Off ", False),
    (" NO ", False), ("unrecognized", True),
])
def test_session_and_ui_review_receive_startup_mask_setting(tmp_path, setting, masked):
    project = Path(__file__).resolve().parents[1]
    child = '''
import base64
import io
from pathlib import Path
import sys
from PIL import Image, ImageDraw
from reverie import model
from reverie.capture import capture_masked
from reverie.control import pilot
from test_frame_provenance_contracts import _session

source = io.BytesIO()
image = Image.new("RGB", (40, 30), "white")
ImageDraw.Draw(image).rectangle((5, 5, 34, 24), fill=(230, 0, 160))
image.save(source, format="PNG")
data = base64.b64encode(source.getvalue()).decode()
geometry = {"width": 40, "height": 30, "rects": [[5, 5, 35, 25, True]], "documents": []}

def call(method, **kwargs):
    if method == "DOM.getDocument":
        return {"root": {"nodeId": 1, "children": []}}
    if method == "Page.captureScreenshot":
        return {"data": data}
    raise AssertionError(method)

s = _session(Path(sys.argv[1]))
s.browser.capture_masked.side_effect = lambda **kwargs: capture_masked(call, lambda expression: geometry, **kwargs)
s.capture()
assert s.last_capture_ok
name = s.save_frame("step")
assert name
seen = []
model.chat_json = lambda system, context, **kwargs: (
    seen.extend(kwargs["images"]) or {"issues": [], "summary": "clear"}, {})
result = pilot.ui_review(s, s.test["steps"][0], [name])
assert result is not None and seen
for encoded in (s.frame, seen[-1]):
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as captured:
        red, green, blue = captured.convert("RGB").getpixel((20, 15))
        magenta = red > 190 and green < 50 and blue > 110
        assert magenta is (sys.argv[2] == "off"), (red, green, blue)
'''
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(project), str(project / "tests"))),
           "REVERIE_UI_REVIEW": "on"}
    env.pop("REVERIE_MASK_SECRETS", None)
    env.pop("REVERIE_SECRET_SELECTORS", None)
    if setting is not None:
        env["REVERIE_MASK_SECRETS"] = setting
    result = subprocess.run([sys.executable, "-c", child, str(tmp_path), "on" if masked else "off"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
