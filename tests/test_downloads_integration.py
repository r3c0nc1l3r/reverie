"""A real Chromium downloads a file from a local server into the configured folder, not ~/Downloads."""

import http.server
import shutil
import threading
import time
from pathlib import Path

import pytest

from reverie.control import downloads
from reverie.control.chromium import Chromium, find_browser

try:
    find_browser()
except RuntimeError:  # pragma: no cover
    pytest.skip("no Chromium-family browser installed", allow_module_level=True)

BODY = b"%PDF-1.4 reverie download test\n"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", 'attachment; filename="reverie-dl-test.pdf"')
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args):
        pass


@pytest.mark.parametrize("headed", [False])
def test_download_lands_in_the_configured_folder(tmp_path, headed):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    target = tmp_path / "dl"
    profile = tmp_path / "profile"
    home_copy = Path.home() / "Downloads" / "reverie-dl-test.pdf"
    existed = home_copy.exists()
    chromium = Chromium(profile, headed=headed, download_dir=target)
    try:
        import httpx

        ws = httpx.put(f"{chromium.cdp_url}/json/new?http://127.0.0.1:{server.server_port}/file.pdf", timeout=5)
        assert ws.status_code == 200
        deadline = time.monotonic() + 15
        finished = target / "reverie-dl-test.pdf"
        while time.monotonic() < deadline and not (finished.exists() and finished.read_bytes() == BODY):
            time.sleep(0.2)
        assert finished.read_bytes() == BODY
        assert not list(target.glob("*.crdownload"))
        if not existed:
            assert not home_copy.exists()
    finally:
        chromium.close()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    assert downloads.resolve(str(target)) == target
