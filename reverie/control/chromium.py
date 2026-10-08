"""A dedicated Chromium window for one control session. The user's own browser profile is never touched."""

import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx

from ..settings import setting
from . import downloads

CANDIDATES = ("chromium", "google-chrome-stable", "google-chrome", "brave", "chromium-browser")


def find_browser():
    configured = setting("REVERIE_BROWSER", "").strip()
    if configured:
        path = shutil.which(configured) or configured
        if not Path(path).exists():
            raise RuntimeError(f"REVERIE_BROWSER={configured} was not found")
        return path
    for name in CANDIDATES:
        if path := shutil.which(name):
            return path
    raise RuntimeError("No Chromium-family browser found. Set REVERIE_BROWSER.")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Chromium:
    def __init__(self, profile_dir, *, headed=True, width=1940, height=1200, download_dir=None):
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        if download_dir:
            Path(download_dir).mkdir(parents=True, exist_ok=True)
            downloads.write_profile_preferences(self.profile_dir, download_dir)
        self.port = free_port()
        self.executable = find_browser()
        args = [
            self.executable,
            f"--remote-debugging-port={self.port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={self.profile_dir}",
            f"--window-size={width},{height}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate,MediaRouter",
            "--password-store=basic",
        ]
        if not headed:
            args.append("--headless=new")
        args.append("about:blank")
        self.process = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"{self.executable} exited during startup (code {self.process.returncode})")
            try:
                if httpx.get(f"{self.cdp_url}/json/version", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        self.close()
        raise RuntimeError("Chromium did not open its debugging port within 20 seconds")

    @property
    def cdp_url(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
