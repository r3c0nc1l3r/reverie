"""Local Kokoro narration through an OpenAI-compatible speech server.

The reference deployment is CrispASR (`crispasr --server --backend kokoro`), a ggml runtime that runs
Kokoro-82M on Vulkan, CUDA, or CPU. Any server exposing POST /v1/audio/speech works.
"""

import os
import re

import httpx

DEFAULT_URL = "http://127.0.0.1:8880"
DEFAULT_VOICE = "af_heart"
VOICE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class KokoroError(RuntimeError):
    """A safe, user-facing Kokoro failure."""


def base_url():
    return os.environ.get("KOKORO_BASE_URL", DEFAULT_URL).rstrip("/")


def default_voice():
    return os.environ.get("KOKORO_VOICE", DEFAULT_VOICE).strip() or DEFAULT_VOICE


def settings():
    return {
        "configured": bool(base_url()),
        "model": os.environ.get("KOKORO_MODEL", "kokoro-82m"),
        "latency": "local",
        "url": base_url(),
        "voice": default_voice(),
    }


def _headers():
    key = os.environ.get("KOKORO_API_KEY", "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _voice_name(raw):
    """CrispASR lists voice files by stem (kokoro-voice-af_heart); callers use the short name (af_heart)."""
    return raw.removeprefix("kokoro-voice-")


def list_voices(query=""):
    query = query.strip().lower()
    if len(query) > 100:
        raise ValueError("Voice search must be 100 characters or fewer")
    names = []
    try:
        with httpx.Client(timeout=5) as client:
            response = client.get(f"{base_url()}/v1/voices", headers=_headers())
        if response.status_code == 200:
            names = [_voice_name(v["name"]) for v in response.json().get("voices", []) if v.get("name")]
    except (httpx.HTTPError, ValueError):
        pass
    configured = [v.strip() for v in os.environ.get("KOKORO_VOICES", "").split(",") if v.strip()]
    names = list(dict.fromkeys(names + configured + [default_voice()]))
    return [
        {"id": name, "title": name, "description": "Local Kokoro voice", "languages": [], "tags": ["kokoro"],
         "cover_image": ""}
        for name in names
        if not query or query in name.lower()
    ]


def synthesize(text, voice_id=None):
    text = text.strip()
    voice = (voice_id or "").strip() or default_voice()
    if not text or len(text) > 1000:
        raise ValueError("Narration text must be 1–1,000 characters")
    if not VOICE.fullmatch(voice):
        raise ValueError("Choose a valid Kokoro voice")
    # CrispASR resolves a bare name against --voice-dir; its files are named kokoro-voice-<name>.gguf.
    prefix = os.environ.get("KOKORO_VOICE_PREFIX", "kokoro-voice-")
    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(
                f"{base_url()}/v1/audio/speech",
                headers=_headers(),
                json={"input": text, "voice": prefix + voice, "response_format": "wav"},
            )
    except httpx.RequestError as error:
        raise KokoroError(f"Could not reach the Kokoro server at {base_url()}") from error
    if response.status_code != 200:
        raise KokoroError(f"Kokoro could not create narration: HTTP {response.status_code} {response.text[:200]}")
    if not response.content:
        raise KokoroError("Kokoro returned empty narration audio")
    return response.content
