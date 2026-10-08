"""Loopback OpenAI-compatible speech server for Kitten TTS (CPU/ONNX, no GPU memory).

Run it from a separate environment that has kittentts installed, for example (scripts/agent-services.sh
looks for it at $TOOLS_DIR/kitten-tts, default ~/tools/kitten-tts; or set KITTEN_PYTHON):
  uv venv ~/tools/kitten-tts/.venv && uv pip install --python ~/tools/kitten-tts/.venv/bin/python \\
    https://github.com/KittenML/KittenTTS/releases/download/0.8.1/kittentts-0.8.1-py3-none-any.whl soundfile
  ~/tools/kitten-tts/.venv/bin/python scripts/kitten_server.py --port 8890

Endpoints: GET /health, GET /v1/voices, POST /v1/audio/speech {"input": "...", "voice": "Jasper"} -> WAV.
"""

import argparse
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import soundfile
from kittentts import KittenTTS

VOICES = ["Bella", "Jasper", "Luna", "Bruno", "Rosie", "Hugo", "Kiki", "Leo"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="KittenML/kitten-tts-nano-0.8")
    parser.add_argument("--voice", default="Jasper")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8890)
    args = parser.parse_args()
    model = KittenTTS(args.model)
    model.generate("Ready.", voice=args.voice)  # Warm up before reporting healthy.
    lock = threading.Lock()  # ONNX sessions are not guaranteed re-entrant; synthesize one request at a time.

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, mime="application/json"):
            body = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                return self.send(200, {"status": "ok", "backend": "kitten", "model": args.model})
            if self.path in {"/v1/voices", "/voices"}:
                return self.send(200, {"voices": [{"name": v, "format": "builtin"} for v in VOICES]})
            return self.send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/v1/audio/speech":
                return self.send(404, {"error": "not found"})
            try:
                request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                text = str(request.get("input", "")).strip()
                voice = request.get("voice") or args.voice
                if not text or len(text) > 2000:
                    return self.send(400, {"error": "input must be 1-2000 characters"})
                if voice not in VOICES:
                    return self.send(400, {"error": f"voice must be one of {', '.join(VOICES)}"})
                with lock:
                    audio = model.generate(text, voice=voice, speed=float(request.get("speed", 1.0)))
                buffer = io.BytesIO()
                soundfile.write(buffer, audio, 24000, format="WAV")
                return self.send(200, buffer.getvalue(), "audio/wav")
            except Exception as error:
                return self.send(500, {"error": f"{type(error).__name__}: {error}"})

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Kitten TTS {args.model} on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
