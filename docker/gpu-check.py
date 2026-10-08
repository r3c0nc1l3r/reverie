"""Open chrome://gpu in the container's Chromium, print the feature status, and save a screenshot.

    docker exec reverie-default reverie-gpu-check [--out DIR] [--headed]

Exit 0 when Compositing, Rasterization and WebGL are hardware accelerated (or when REVERIE_GPU=off), 1 otherwise.
Uses the websockets package from Reverie's own environment; no Playwright needed at run time.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from websockets.sync.client import connect

JS = """(() => { const out = []; const walk = (n) => { if (n.shadowRoot) walk(n.shadowRoot);
  for (const c of n.childNodes) { if (c.nodeType === 3) { const t = c.textContent.trim(); if (t) out.push(t); }
  else if (c.nodeType === 1 && c.tagName !== 'STYLE') walk(c); } }; walk(document.body); return out.join('\\n'); })()"""
WANT = ("Compositing", "Rasterization", "WebGL", "Canvas")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/downloads", help="Directory for gpu.txt and gpu.png")
    ap.add_argument("--headed", action="store_true", help="Use the display instead of --headless=new")
    args = ap.parse_args()
    port = 9400 + os.getpid() % 500
    profile = tempfile.mkdtemp(prefix="gpucheck-")
    cmd = [os.environ.get("REVERIE_BROWSER", "reverie-chromium"), f"--remote-debugging-port={port}",
           f"--user-data-dir={profile}", "--no-first-run", "--window-size=1300,2600", "about:blank"]
    if not args.headed:
        cmd.insert(1, "--headless=new")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{base}/json/version", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        req = urllib.request.Request(f"{base}/json/new?chrome://gpu", method="PUT")
        target = json.load(urllib.request.urlopen(req, timeout=10))
        with connect(target["webSocketDebuggerUrl"], max_size=64 * 2**20) as ws:
            n = [0]

            def call(method, **params):
                n[0] += 1
                ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == n[0]:
                        return msg.get("result", {})

            call("Emulation.setDeviceMetricsOverride", width=1300, height=2600, deviceScaleFactor=1, mobile=False)
            time.sleep(6)  # chrome://gpu fills in asynchronously
            text = call("Runtime.evaluate", expression=JS, returnByValue=True)["result"]["value"]
            shot = call("Page.captureScreenshot", format="png")["data"]
        os.makedirs(args.out, exist_ok=True)
        open(os.path.join(args.out, "gpu.txt"), "w").write(text)
        open(os.path.join(args.out, "gpu.png"), "wb").write(base64.b64decode(shot))
    finally:
        proc.terminate()
    lines = text.split("\n")
    status = {lines[i].rstrip(":"): lines[i + 1] for i in range(len(lines) - 1) if lines[i].endswith(":")
              and lines[i].rstrip(":") in {"Canvas", "Compositing", "Rasterization", "Video Decode", "WebGL", "OpenGL",
                                           "Vulkan", "Video Encode", "WebGPU"}}
    for key, value in status.items():
        print(f"{key:15} {value}")
    renderer = next((line for line in lines if line.startswith("ANGLE (")), None)
    if renderer:
        print("renderer       ", renderer[:160])
    print(f"saved {args.out}/gpu.txt and gpu.png")
    if os.environ.get("REVERIE_GPU") == "off":
        return 0
    ok = all(status.get(k, "").startswith("Hardware accelerated") for k in WANT)
    print("GPU acceleration:", "OK" if ok else "NOT active (software rendering)")
    return 0 if ok else 1


sys.exit(main())
