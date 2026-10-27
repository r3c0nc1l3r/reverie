"""Serve the synthetic visual smoke lab on loopback."""

import argparse
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class LabHandler(SimpleHTTPRequestHandler):
    """Serve fixture assets and simulate a slow image response."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("directory", str(Path(__file__).resolve().parent))
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if urlsplit(self.path).path == "/icons/delayed.svg":
            time.sleep(2.5)
        return super().do_GET()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), LabHandler) as server:
        print(f"Smoke lab: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
