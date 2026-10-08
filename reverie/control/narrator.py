"""Spoken narration that never blocks the browser. Speech runs in order on one background thread."""

import io
import os
import queue
import random
import shutil
import subprocess
import threading
import time
import wave

from ..settings import setting

VOICES = ("auto", "kitten", "kokoro", "fish", "espeak", "spd", "off")
PLAYERS = (["pw-play", "-"], ["paplay"], ["mpv", "--really-quiet", "--no-video", "-"])


def resolve_voice(requested="auto"):
    if requested not in VOICES:
        raise ValueError(f"Voice must be one of {', '.join(VOICES)}")
    if requested != "auto":
        return requested
    # SPEECH_PROVIDER picks the hosted/local neural voice; espeak and spd are offline fallbacks.
    preferred = os.environ.get("SPEECH_PROVIDER", "kokoro").strip().lower()
    if preferred in {"kokoro", "kitten"} and local_ready(preferred) and player():
        return preferred
    fish_ready = all(os.environ.get(key, "").strip() for key in ("FISH_AUDIO_API_TOKEN", "FISH_AUDIO_VOICE_ID"))
    if fish_ready and shutil.which("mpv"):
        return "fish"
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        return "espeak"
    if shutil.which("spd-say"):
        return "spd"
    return "off"


def local_ready(provider="kokoro"):
    import httpx

    from .. import kitten, kokoro

    base = {"kokoro": kokoro, "kitten": kitten}[provider].base_url()
    try:
        return httpx.get(f"{base}/health", timeout=2).status_code < 500
    except httpx.HTTPError:
        return False


def kokoro_ready():
    return local_ready("kokoro")


def wake_audio(seconds):
    """Near-silent 16-bit noise. Bluetooth sinks sleep when idle and drop the start of the next sound; digital
    zeros may not wake every device, so this plays a tiny dither (about -66 dBFS) instead."""
    rate = 24000
    frames = bytearray()
    rng = random.Random(7)
    for _ in range(int(rate * seconds)):
        frames += rng.randint(-16, 16).to_bytes(2, "little", signed=True)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(frames))
    return buffer.getvalue()


def player():
    return next((command for command in PLAYERS if shutil.which(command[0])), None)


class Narrator:
    def __init__(self, voice="auto", rate=None):
        self.voice = resolve_voice(voice)
        self.rate = rate or int(setting("REVERIE_SPEECH_RATE", "185"))
        self.spoken = []
        self._queue = queue.Queue()
        self._idle = threading.Event()
        self._idle.set()
        # Bluetooth audio mode (REVERIE_BLUETOOTH_AUDIO=1, `start --bluetooth`, or `audio --bluetooth on`):
        # play REVERIE_AUDIO_WAKE seconds of near-silent audio before speech that follows an idle gap.
        self.bluetooth = setting("REVERIE_BLUETOOTH_AUDIO", "0").lower() in {"1", "true", "on", "yes"}
        self.wake_seconds = float(setting("REVERIE_AUDIO_WAKE", "1.2"))
        self.wake_after_idle = float(setting("REVERIE_AUDIO_WAKE_IDLE", "4"))
        self.last_audio = 0.0
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def say(self, text, wait=False):
        text = " ".join(str(text).split())[:500]
        if not text:
            return
        self.spoken.append(text)
        if self.voice == "off":
            return
        self._idle.clear()
        self._queue.put(text)
        if wait:
            self.drain()

    def drain(self, timeout=30):
        self._idle.wait(timeout)

    def close(self):
        self._queue.put(None)

    def _worker(self):
        while (text := self._queue.get()) is not None:
            try:
                self._speak(text)
            except Exception:
                pass  # Narration is best effort; it must never stop a browser run.
            if self._queue.empty():
                self._idle.set()

    def _wake(self):
        if not self.bluetooth or self.wake_seconds <= 0 or time.monotonic() - self.last_audio < self.wake_after_idle:
            return
        command = ["mpv", "--really-quiet", "--no-video", "-"] if self.voice == "fish" else player()
        if command:
            subprocess.run(command, input=wake_audio(self.wake_seconds), timeout=15, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _speak(self, text):
        audio = None
        if self.voice in {"kokoro", "kitten", "fish"}:
            # Synthesize first, then wake the headphones right before playback so they do not doze again.
            if self.voice == "fish":
                from ..fish_audio import synthesize

                audio = synthesize(text, os.environ["FISH_AUDIO_VOICE_ID"])
            else:
                from .. import kitten, kokoro

                audio = {"kokoro": kokoro, "kitten": kitten}[self.voice].synthesize(text)
        self._wake()
        try:
            self._play(text, audio)
        finally:
            self.last_audio = time.monotonic()

    def _play(self, text, audio):
        if self.voice in {"kokoro", "kitten"}:
            subprocess.run(player(), input=audio, timeout=60, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif self.voice == "fish":
            subprocess.run(["mpv", "--really-quiet", "--no-video", "-"], input=audio, timeout=60, check=False)
        elif self.voice == "espeak":
            binary = shutil.which("espeak-ng") or "espeak"
            subprocess.run([binary, "-s", str(self.rate), text], timeout=60, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif self.voice == "spd":
            subprocess.run(["spd-say", "-w", text], timeout=60, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
