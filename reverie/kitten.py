"""Local Kitten TTS narration (CPU/ONNX, no GPU memory) through scripts/kitten_server.py."""

import os

import httpx

DEFAULT_URL = "http://127.0.0.1:8890"
DEFAULT_VOICE = "Jasper"
VOICES = ("Bella", "Jasper", "Luna", "Bruno", "Rosie", "Hugo", "Kiki", "Leo")


class KittenError(RuntimeError):
    """A safe, user-facing Kitten failure."""


def base_url():
    return os.environ.get("KITTEN_BASE_URL", DEFAULT_URL).rstrip("/")


def default_voice():
    return os.environ.get("KITTEN_VOICE", DEFAULT_VOICE).strip() or DEFAULT_VOICE


def settings():
    return {"configured": bool(base_url()), "model": os.environ.get("KITTEN_MODEL", "kitten-tts-nano-0.8"),
            "latency": "local", "url": base_url(), "voice": default_voice()}


def list_voices(query=""):
    query = query.strip().lower()
    return [{"id": v, "title": v, "description": "Local Kitten voice", "languages": ["en"], "tags": ["kitten"],
             "cover_image": ""} for v in VOICES if not query or query in v.lower()]


def synthesize(text, voice_id=None):
    text = text.strip()
    voice = (voice_id or "").strip() or default_voice()
    if not text or len(text) > 1000:
        raise ValueError("Narration text must be 1–1,000 characters")
    if voice not in VOICES:
        raise ValueError("Choose a valid Kitten voice")
    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(f"{base_url()}/v1/audio/speech", json={"input": text, "voice": voice})
    except httpx.RequestError as error:
        raise KittenError(f"Could not reach the Kitten server at {base_url()}") from error
    if response.status_code != 200 or not response.content:
        raise KittenError(f"Kitten could not create narration: HTTP {response.status_code} {response.text[:200]}")
    return response.content
