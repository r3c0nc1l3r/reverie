"""Bounded speech playback with completion tickets for supervised browser pacing."""

import io
import os
import queue
import random
import shutil
import subprocess
import threading
import time
import wave
from dataclasses import dataclass, field

from ..settings import setting


@dataclass
class SpeechTicket:
    id: int
    text: str
    done: threading.Event = field(default_factory=threading.Event)
    state: str = "queued"
    generation: int = 0
    ended: float = 0.0
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None


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
        self.muted = False
        self._queue = queue.Queue()
        self._idle = threading.Event()
        self._idle.set()
        # Bluetooth audio mode (REVERIE_BLUETOOTH_AUDIO=1, `start --bluetooth`, or `audio --bluetooth on`):
        # play REVERIE_AUDIO_WAKE seconds of near-silent audio before speech that follows an idle gap.
        self.bluetooth = setting("REVERIE_BLUETOOTH_AUDIO", "0").lower() in {"1", "true", "on", "yes"}
        self.wake_seconds = float(setting("REVERIE_AUDIO_WAKE", "1.2"))
        self.wake_after_idle = float(setting("REVERIE_AUDIO_WAKE_IDLE", "4"))
        self.last_audio = 0.0
        self._serial = 0
        self._generation = 0
        self._guard = threading.RLock()
        self._current = None
        self._process = None
        self._last_ticket = None
        self.on_event = None
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def say(self, text, wait=False):
        text = " ".join(str(text).split())[:500]
        if not text:
            return
        self.spoken.append(text)
        with self._guard:
            self._serial += 1
            ticket = SpeechTicket(self._serial, text, generation=self._generation)
            self._last_ticket = ticket
        if self.voice == "off" or self.muted:
            ticket.state = "silent"
            ticket.done.set()
            return ticket
        self._idle.clear()
        # A running utterance plus one future beat. Replaced captions remain in the run trail.
        with self._guard:
            while True:
                try:
                    old = self._queue.get_nowait()
                except queue.Empty:
                    break
                if old is not None:
                    old.state = "superseded"
                    old.done.set()
            self._idle.clear()
            self._queue.put(ticket)
        if wait:
            self.drain()
        return ticket

    def drain(self, timeout=30):
        return self._idle.wait(timeout)

    def boundary(self, ticket=None, padding_ms=350, cancelled=None, timeout=90):
        """Wait only for the remainder of this beat; page/model time already elapsed counts."""
        ticket = ticket or self._last_ticket
        if ticket is None or ticket.state in {"silent", "skipped", "superseded"}:
            return True
        deadline = time.monotonic() + timeout
        while not ticket.done.wait(0.05):
            if cancelled and cancelled():
                return False
            if time.monotonic() >= deadline:
                raise RuntimeError("Narration did not finish; retry or skip narration to continue")
        if ticket.error:
            raise RuntimeError(f"Audio unavailable: {ticket.error}. Retry or skip narration to continue")
        if ticket.state != "completed":
            return True
        until = ticket.ended + max(0, padding_ms) / 1000
        while (remaining := until - time.monotonic()) > 0:
            if cancelled and cancelled():
                return False
            time.sleep(min(0.05, remaining))
        return True

    def skip(self):
        with self._guard:
            self._generation += 1
            if self._current:
                self._current.state = "skipped"
                self._current.error = None
                self._current.done.set()
            if self._last_ticket:
                self._last_ticket.state = "skipped"
                self._last_ticket.error = None
                self._last_ticket.done.set()
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item:
                    item.state = "skipped"
                    item.done.set()
            if self._process and self._process.poll() is None:
                self._process.terminate()
        self._idle.set()
        self._notify("skipped", self._last_ticket)

    def state(self, padding_ms=350):
        ticket = self._last_ticket
        state = ticket.state if ticket else "idle"
        remaining = 0
        if ticket and state == "completed":
            remaining = max(0, round((ticket.ended + padding_ms / 1000 - time.monotonic()) * 1000))
            state = "padding" if remaining else "idle"
        return {"state": state, "utterance_id": ticket.id if ticket else None,
                "padding_remaining_ms": remaining, "error": ticket.error if ticket else None,
                "started_at": ticket.started_at if ticket else None,
                "completed_at": ticket.completed_at if ticket else None}

    def _notify(self, state, ticket):
        if self.on_event and ticket:
            try:
                self.on_event({"state": state, "utterance_id": ticket.id, "error": ticket.error,
                               "started_at": ticket.started_at, "completed_at": ticket.completed_at})
            except Exception:
                pass

    def close(self):
        self.skip()
        self._queue.put(None)

    def _worker(self):
        while (ticket := self._queue.get()) is not None:
            with self._guard:
                if ticket.generation != self._generation or ticket.state == "skipped":
                    ticket.state = "skipped"
                    ticket.done.set()
                    if self._queue.empty():
                        self._idle.set()
                    continue
                self._current = ticket
                ticket.state = "preparing"
            self._notify("preparing", ticket)
            try:
                self._speak(ticket.text)
                if ticket.state != "skipped":
                    ticket.state = "completed"
            except Exception as error:
                if ticket.state != "skipped":
                    ticket.error = str(error)[:240]
                    ticket.state = "error"
            ticket.ended = time.monotonic()
            ticket.completed_at = time.time()
            ticket.done.set()
            self._notify(ticket.state, ticket)
            with self._guard:
                self._current = None
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
        if self._current and self._current.state == "skipped":
            return
        if self._current:
            self._current.started_at = time.time()
            self._current.state = "speaking"
            self._notify("speaking", self._current)
        if self.voice in {"kokoro", "kitten"}:
            command = player()
        elif self.voice == "fish":
            command = ["mpv", "--really-quiet", "--no-video", "-"]
        elif self.voice == "espeak":
            binary = shutil.which("espeak-ng") or "espeak"
            command = [binary, "-s", str(self.rate), text]
        elif self.voice == "spd":
            command = ["spd-say", "-w", text]
        else:
            return
        if not command:
            raise RuntimeError("No audio playback program is available")
        with self._guard:
            if self._current and self._current.state == "skipped":
                return
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
            process = self._process
        try:
            process.communicate(audio, timeout=60)
            if process.returncode and not (self._current and self._current.state == "skipped"):
                raise RuntimeError(f"Audio player exited {process.returncode}")
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise RuntimeError("Audio player timed out") from None
        finally:
            self._process = None
