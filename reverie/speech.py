"""Narration provider switch. SPEECH_PROVIDER=kitten (local CPU), kokoro (local ggml), or fish (hosted)."""

import os

from . import fish_audio, kitten, kokoro
from .fish_audio import FishAudioError
from .kitten import KittenError
from .kokoro import KokoroError

PROVIDERS = {"kitten": kitten, "kokoro": kokoro, "fish": fish_audio}
LABELS = {"kitten": "Kitten", "kokoro": "Kokoro", "fish": "Fish Audio"}
MIME = {"kitten": "audio/wav", "kokoro": "audio/wav", "fish": "audio/mpeg"}
SpeechError = (FishAudioError, KittenError, KokoroError)


def provider():
    name = os.environ.get("SPEECH_PROVIDER", "kokoro").strip().lower() or "kokoro"
    if name not in PROVIDERS:
        raise KokoroError(f"Unsupported SPEECH_PROVIDER: {name}. Use kitten, kokoro, or fish.")
    return name


def fixed_voice(name=None):
    """A configured voice pins every utterance to one speaker, whatever the browser asks for."""
    name = name or provider()
    key = {"fish": "FISH_AUDIO_VOICE_ID", "kokoro": "KOKORO_VOICE", "kitten": "KITTEN_VOICE"}[name]
    return os.environ.get(key, "").strip() or None


def settings():
    name = provider()
    return {**PROVIDERS[name].settings(), "provider": name, "label": LABELS[name], "voice": fixed_voice(name)}


def list_voices(query=""):
    return PROVIDERS[provider()].list_voices(query)


def synthesize(text, voice_id):
    name = provider()
    return PROVIDERS[name].synthesize(text, fixed_voice(name) or voice_id), MIME[name]
