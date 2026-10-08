"""Small server-side client for Fish Audio voices and text-to-speech."""

import os
import re
import ssl

import httpx

API_ROOT = "https://api.fish.audio"
VOICE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
TTS_MODELS = {"s1", "s2-pro", "s2.1-pro", "s2.1-pro-free", "drama-3-preview"}
LATENCY_MODES = {"low", "normal", "balanced"}


class FishAudioError(RuntimeError):
    """A safe, user-facing Fish Audio failure."""


def settings():
    model = os.environ.get("FISH_AUDIO_TTS_MODEL", "s2.1-pro-free").strip()
    latency = os.environ.get("FISH_AUDIO_TTS_LATENCY", "balanced").strip()
    if model not in TTS_MODELS:
        raise FishAudioError(f"Unsupported FISH_AUDIO_TTS_MODEL: {model}")
    if latency not in LATENCY_MODES:
        raise FishAudioError(f"Unsupported FISH_AUDIO_TTS_LATENCY: {latency}")
    return {
        "configured": bool(os.environ.get("FISH_AUDIO_API_TOKEN", "").strip()),
        "model": model,
        "latency": latency,
    }


def _headers():
    token = os.environ.get("FISH_AUDIO_API_TOKEN", "").strip()
    if not token:
        raise FishAudioError("Fish Audio is not configured. Set FISH_AUDIO_API_TOKEN.")
    return {"Authorization": f"Bearer {token}"}


def _client(timeout):
    # Use the OS trust store. On some Linux distributions certifi omits roots that
    # are present in the system bundle used by browsers and curl.
    return httpx.Client(verify=ssl.create_default_context(), timeout=timeout)


def _error(response):
    try:
        payload = response.json()
        message = payload.get("message") or payload.get("detail") or payload.get("reason")
    except (ValueError, TypeError):
        message = None
    return str(message or f"HTTP {response.status_code}")[:300]


def list_voices(query=""):
    query = query.strip()
    if len(query) > 100:
        raise ValueError("Voice search must be 100 characters or fewer")
    params = {"page_size": 30, "page_number": 1, "sort_by": "task_count"}
    if query:
        params["title"] = query
    try:
        with _client(15) as client:
            response = client.get(f"{API_ROOT}/model", headers=_headers(), params=params)
    except httpx.RequestError as error:
        raise FishAudioError("Could not reach Fish Audio while loading voices") from error
    if response.status_code != 200:
        raise FishAudioError(f"Fish Audio could not load voices: {_error(response)}")
    items = response.json().get("items", [])
    return [
        {
            "id": item["_id"],
            "title": item.get("title") or "Untitled voice",
            "description": item.get("description") or "",
            "languages": item.get("languages") or [],
            "tags": item.get("tags") or [],
            "cover_image": item.get("cover_image") or "",
        }
        for item in items
        if item.get("_id") and item.get("type") == "tts" and item.get("state") == "trained"
    ]


def synthesize(text, voice_id):
    text = text.strip()
    voice_id = voice_id.strip()
    if not text or len(text) > 1000:
        raise ValueError("Narration text must be 1–1,000 characters")
    if not VOICE_ID.fullmatch(voice_id):
        raise ValueError("Choose a valid Fish Audio voice")
    config = settings()
    try:
        with _client(60) as client:
            response = client.post(
                f"{API_ROOT}/v1/tts",
                headers={**_headers(), "model": config["model"]},
                json={
                    "text": text,
                    "reference_id": voice_id,
                    "format": "mp3",
                    "latency": config["latency"],
                },
            )
    except httpx.RequestError as error:
        raise FishAudioError("Could not reach Fish Audio for narration") from error
    if response.status_code != 200:
        raise FishAudioError(f"Fish Audio could not create narration: {_error(response)}")
    if not response.content:
        raise FishAudioError("Fish Audio returned empty narration audio")
    return response.content
