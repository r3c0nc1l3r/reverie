---
title: Narration
description: Spoken progress updates, the speech providers Reverie supports, and how to turn them on, off, and tune them.
---

Reverie can speak short progress updates while a spec runs. Every action also gets a text caption in the browser window, so narration is optional. If audio fails, the run goes on.

By default, only milestones are spoken: the pilot's progress updates, the start of a test, and session start and close. Set `REVERIE_NARRATION=verbose` to speak every caption as well.

## Voices

`start` takes a `--voice` option.

| Voice | What it is |
|---|---|
| `auto` (default) | Picks the first working option from the list below. |
| `kitten` | Local Kitten TTS server. Runs on CPU. |
| `kokoro` | Local Kokoro server with an OpenAI-compatible `/v1/audio/speech` endpoint. |
| `fish` | Fish Audio, a hosted service. |
| `espeak` | The `espeak-ng` or `espeak` program on your machine. |
| `spd` | `spd-say` from Speech Dispatcher. |
| `off` | No speech. Captions still appear. |

With `auto`, Reverie tries these in order:

1. The local provider named by `SPEECH_PROVIDER` (`kitten` or `kokoro`), if its server answers on `/health` and an audio player is installed (`pw-play`, `paplay`, or `mpv`).
2. Fish Audio, if `FISH_AUDIO_API_TOKEN` and `FISH_AUDIO_VOICE_ID` are set and `mpv` is installed.
3. `espeak-ng` or `espeak`.
4. `spd-say`.
5. Off.

If `SPEECH_PROVIDER` is unset, the code uses `kokoro`. The `.env.example` file sets `SPEECH_PROVIDER=kitten`.

To start a session without narration:

```bash
reverie --session demo start --url https://example.com --voice off
```

### Provider settings

| Variable | Default | Provider |
|---|---|---|
| `SPEECH_PROVIDER` | `kokoro` | Chooses `kitten`, `kokoro`, or `fish` for `auto` and for dashboard playback. |
| `KITTEN_BASE_URL` | `http://127.0.0.1:8890` | Kitten server address. |
| `KITTEN_VOICE` | `Jasper` | Kitten voice. Choices: Bella, Jasper, Luna, Bruno, Rosie, Hugo, Kiki, Leo. |
| `KOKORO_BASE_URL` | `http://127.0.0.1:8880` | Kokoro server address. |
| `KOKORO_VOICE` | `af_heart` | Kokoro voice. |
| `FISH_AUDIO_API_TOKEN` | none | Fish Audio token. |
| `FISH_AUDIO_VOICE_ID` | none | Fish Audio voice. |
| `REVERIE_SPEECH_RATE` | `185` | Words per minute for `espeak`. |

See the [configuration reference](/reverie/reference/configuration/) for the full list.

## Speak a line yourself

```bash
reverie --session demo say "Starting the checkout test"
reverie --session demo say --wait "Waiting for you"
```

`say` shows a caption and speaks the text. With `--wait`, the command returns after the speech ends. Text is limited to 500 characters for each line.

## Bluetooth headphones

Bluetooth headphones often sleep when idle and cut off the start of the next sound. Bluetooth mode plays a short, near-silent sound before speech that follows a pause, to wake them.

```bash
reverie --session demo start --url https://example.com --bluetooth
reverie --session demo audio --bluetooth on --wake 1.2
reverie --session demo audio
```

| Option | Does |
|---|---|
| `audio --bluetooth on\|off` | Turns Bluetooth mode on or off for a running session. |
| `audio --wake SECONDS` | Sets the length of the wake-up sound. The session limits it to 0 through 5 seconds. |
| `audio` alone | Prints the current mode, wake time, and voice. |

You can set the same options with environment variables:

| Variable | Default | Does |
|---|---|---|
| `REVERIE_BLUETOOTH_AUDIO` | `0` | `1`, `true`, `on`, or `yes` turns Bluetooth mode on. |
| `REVERIE_AUDIO_WAKE` | `1.2` | Seconds of wake-up sound. |
| `REVERIE_AUDIO_WAKE_IDLE` | `4` | Seconds of silence before Reverie plays the wake-up sound again. |

## Narration in the dashboard

The dashboard and replay pages play the narration recorded with each frame. They ask the dashboard server to synthesize the text with the provider in `SPEECH_PROVIDER`, and cache the audio in `.reverie/cache/speech/`. Press `N` to turn playback on or off. See [Runs and dashboard](/reverie/guides/runs-and-dashboard/).

## The local Kitten server

`scripts/kitten_server.py` is a small local server for [Kitten TTS](https://github.com/KittenML/KittenTTS). It runs on CPU and uses no GPU memory. It listens on `127.0.0.1` only.

It needs the `kittentts` and `soundfile` packages. Install them in a separate Python environment, not in the Reverie environment, and run the script with that environment's Python:

```bash
/path/to/kitten-env/bin/python scripts/kitten_server.py --port 8890
```

| Option | Default |
|---|---|
| `--model` | `KittenML/kitten-tts-nano-0.8` |
| `--voice` | `Jasper` |
| `--host` | `127.0.0.1` |
| `--port` | `8890` |

The server answers these endpoints:

- `GET /health`
- `GET /v1/voices`
- `POST /v1/audio/speech` with `{"input": "...", "voice": "Jasper"}`, which returns WAV audio.

Instead of running it by hand, `scripts/agent-services.sh start` starts it for you when `KITTEN_PYTHON` points at the environment's Python. See [Installation](/reverie/start/installation/#optional-services).
