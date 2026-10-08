---
title: Configuration
description: Every environment variable Reverie reads, how `.env` files are loaded, and the services script.
---

Reverie reads its settings from environment variables. You can set them in your shell or in a `.env` file. The CLI is `reverie`; `laya-agent` is an alias for it.

## How `.env` is loaded

Reverie reads settings from the real environment first, then from these `.env` files. The first value found wins.

| Order | File | Use |
| --- | --- | --- |
| 1 | The real environment | Variables you export in your shell. They always win. |
| 2 | `$REVERIE_ENV_FILE` | An explicit file, for example in CI. |
| 3 | `<project root>/.env` | Settings for one project. The project root is the directory that holds `.reverie/`. |
| 4 | `./.env` | The working directory, when it differs from the project root. |
| 5 | `~/.config/reverie/.env` | Your API keys, shared by every project. Use mode 600. |

Files that do not exist are skipped. The user file is in `$XDG_CONFIG_HOME/reverie/.env` when `XDG_CONFIG_HOME` is set.

The session daemon and the dashboard (`reverie ui`) load these files when they start. The `reverie` command itself does not read `.env`. Run Reverie from the project you test. The loader is `load_environment()` in `reverie/control/server.py`.

- A line is `KEY=value`. A leading `export ` is allowed. Lines that start with `#` are skipped.
- Keys and values are trimmed. A value wrapped in matching single or double quotes loses the quotes.
- A comment must be on its own line. Everything after `=` is the value.
- A variable with an empty value is ignored, so `OPENROUTER_API_KEY=` copied from the example does not hide a key from a later file.

Keep your keys in one file that every project shares:

```bash
mkdir -p ~/.config/reverie
touch ~/.config/reverie/.env
chmod 600 ~/.config/reverie/.env
```

:::note
`LAYA_AGENT_SESSION` is read by the `reverie` command, and `LAYA_AGENT_UI_PORT` is read when the dashboard builds its options. Neither comes from `.env`. Set them in your shell, or use the `--session` and `--port` flags.
:::

Start from the example file:

```bash
cp .env.example .env
```

```ini
# Reverie reads settings from the environment, then from these .env files (first wins):
#   $REVERIE_ENV_FILE, <project root>/.env, ./.env, ~/.config/reverie/.env
# Keep API keys in ~/.config/reverie/.env (mode 600) to share them across projects.

# Pilot and text model (OpenRouter)
OPENROUTER_API_KEY=
TEXT_MODEL_PROVIDER=openrouter
TEXT_MODEL=z-ai/glm-5.3-flash:nitro
LAYA_AGENT_PILOT_MODEL=z-ai/glm-5.3-flash:nitro
# The pilot can use its own OpenAI-compatible endpoint; unset values fall back to TEXT_MODEL_*.
# LAYA_AGENT_PILOT_PROVIDER=opencode-go      # openrouter | opencode-go | deepseek (sets the base URL)
# LAYA_AGENT_PILOT_BASE_URL=https://gateway.example.com/v1
# LAYA_AGENT_PILOT_API_KEY=
# OpenCode Go: set LAYA_AGENT_PILOT_PROVIDER=opencode-go and LAYA_AGENT_PILOT_MODEL=glm-5.3-flash. The key comes
# from OPENCODE_GO_API_KEY, else from OpenCode's auth.json (OPENCODE_AUTH_FILE overrides its path, e.g. Pi's).
TEXT_MODEL_EFFORT=low

# Local Laya decisions (laya.cpp)
LAYA_BACKEND=http
LAYA_BASE_URL=http://127.0.0.1:8080

# Behavior
# LAYA_AGENT_ENGINE=jev            # fast decision layer: laya (default, local) or jev (hosted, uses OPENROUTER_API_KEY)
LAYA_AGENT_MERCURY=off
LAYA_AGENT_UI_REVIEW=on
LAYA_AGENT_DIALOGS=accept
LAYA_AGENT_STALL_SECONDS=240
# LAYA_AGENT_PLAYBOOK=/path/to/playbook.json
# Browser downloads folder (default: downloads/ in the run folder; never ~/Downloads)
# REVERIE_DOWNLOAD_DIR=/path/to/downloads

# Narration
SPEECH_PROVIDER=kitten
KITTEN_BASE_URL=http://127.0.0.1:8890
LAYA_AGENT_BLUETOOTH_AUDIO=0
LAYA_AGENT_AUDIO_WAKE=1.2
# FISH_AUDIO_API_TOKEN=
```

The defaults in the tables below are the values the code uses when a variable is unset. They can differ from the example file. For example, the code defaults `SPEECH_PROVIDER` to `kokoro`, while the example sets `kitten`.

To pick models and providers, see [Models and providers](/reverie/reference/models/).

## The `.reverie/` project directory

Reverie keeps run history, stored specs, caches and the pilot playbook in a `.reverie/` directory. The project root is the nearest directory, from the working directory upward, that already holds `.reverie/` (the way git finds `.git`). If none exists, the working directory is the root.

`LAYA_AGENT_PLAYBOOK` moves the playbook file elsewhere. See [Runs and dashboard](/reverie/guides/runs-and-dashboard/) for the layout and how to review runs.

## Pilot and text model

The text model and the pilot each call an OpenAI-compatible chat API. The pilot reads its own `LAYA_AGENT_PILOT_*` settings and falls back to the `TEXT_MODEL_*` value for any it does not set. See [Models and providers](/reverie/reference/models/) for the presets and the fallback rules.

| Variable | Default | What it does |
| --- | --- | --- |
| `TEXT_MODEL_PROVIDER` | unset | Provider preset for the text model: `openrouter`, `opencode-go` or `deepseek`. It sets the base URL and, for two of them, finds the key. |
| `TEXT_MODEL_BASE_URL` | the preset's URL, else `https://api.deepseek.com/v1` | Base URL of an OpenAI-compatible chat API. It wins over the preset. |
| `TEXT_MODEL_API_KEY` | none | API key for that base URL. Not needed for a local endpoint (`localhost`, `127.0.0.1`, `::1`). |
| `TEXT_MODEL` | `deepseek-chat` | Model id for the text model. It fills in field values, plans goals, and drives Mercury. |
| `LAYA_AGENT_PILOT_PROVIDER` | the text model's | Provider preset for the pilot. |
| `LAYA_AGENT_PILOT_BASE_URL` | the text model's | Base URL for the pilot. |
| `LAYA_AGENT_PILOT_API_KEY` | the text model's | API key for the pilot. |
| `LAYA_AGENT_PILOT_MODEL` | `z-ai/glm-5.3-flash` | Model id the pilot uses. |
| `OPENROUTER_API_KEY` | none | Key used when the provider is `openrouter` and no other key is set. Also used by the remote Jev decision engine. |
| `OPENCODE_GO_API_KEY` | none | Key used when the provider is `opencode-go`. If unset, Reverie reads it from OpenCode's `auth.json`. |
| `OPENCODE_AUTH_FILE` | OpenCode's default `auth.json` | Path of the `auth.json` to read the OpenCode Go key from, such as one written by another tool. |
| `REVERIE_MODEL_SESSION` | random per process | Session id sent to OpenCode Go in the `x-opencode-session` header. |
| `TEXT_MODEL_EFFORT` | `low` | Reasoning effort sent to non-local, non-DeepSeek endpoints. |
| `TEXT_MODEL_REASONING` | unset | Set to `none` to turn reasoning off for text-model calls. |
| `LAYA_AGENT_PILOT_VISION` | `1` | Set to `0` to stop sending marked screenshots to the pilot. |
| `LAYA_AGENT_UI_REVIEW` | `1` | Set to `0` to turn off the screenshot review of each step for broken UI. |
| `REMOTE_DECISION_MODEL` | `typesafe/jev-1.13` | Model id for the remote Jev decision engine. |

## Local Laya decisions

| Variable | Default | What it does |
| --- | --- | --- |
| `LAYA_BACKEND` | `auto` | `auto`, `http` or `mlx`. `auto` picks `mlx` on Apple Silicon when `laya_mlx` is installed, else `http`. |
| `LAYA_BASE_URL` | `http://127.0.0.1:8080` | URL of the laya.cpp server (`http` backend). |
| `LAYA_HTTP_TIMEOUT` | `30` | Request timeout in seconds for the `http` backend. Must be above zero. |
| `LAYA_TLS_CA` | unset | Path to a CA file used to verify a TLS endpoint. |
| `LOCAL_DECISION_MODEL` | `aac6fef/laya-typed-decisions-mlx` | Model the `mlx` backend loads. |
| `LAYA_AGENT_ENGINE` | unset (Laya) | The session's fast decision layer: `laya` or `jev`. `reverie start --engine` wins over it. Any other value is an error. Jev needs `OPENROUTER_API_KEY`. See [Decision engines](/reverie/reference/models/#decision-engines). |
| `LAYA_AGENT_LAYA_MIN` | `0.6` | Minimum confidence for the fast layer's choice (Laya or Jev) before the step is escalated. |
| `LAYA_AGENT_MERCURY` | `on` | `off`, `0`, `false` or `no` disables Mercury. A step the fast layer is unsure about then goes back to the pilot unexecuted. |

## Session and browser behaviour

| Variable | Default | What it does |
| --- | --- | --- |
| `LAYA_AGENT_SESSION` | `default` | Session name, used when you do not pass `--session`. |
| `LAYA_AGENT_BROWSER` | auto-detect | Browser executable. Without it Reverie tries `chromium`, `google-chrome-stable`, `google-chrome`, `brave` and `chromium-browser`. |
| `LAYA_AGENT_VIEWPORT` | `1920x1080` | Viewport size as `WIDTHxHEIGHT`. |
| `LAYA_AGENT_DIALOGS` | `accept` | How native alert, confirm and prompt dialogs are answered. `dismiss` cancels them; anything else accepts. |
| `LAYA_AGENT_STEP_CEILING` | `25` | Upper bound on steps in one automatic loop. |
| `LAYA_AGENT_PILOT_STUCK` | `12` | Operations on one plan step with no progress before the pilot raises a checkpoint. |
| `LAYA_AGENT_STALL_SECONDS` | `240` | Seconds without activity before a running pilot counts as stalled. |
| `LAYA_AGENT_PLAYBOOK` | `.reverie/playbook.json` | Path of the per-host lessons file. |
| `REVERIE_ENV_FILE` | unset | An extra `.env` file to read first. See [How `.env` is loaded](#how-env-is-loaded). |
| `BU_NAME` | set by Reverie | Daemon name (`laya-agent-<session>`). The CLI sets it when it spawns a session daemon, and the daemon refuses to start without it. Do not set it yourself. |

## Downloads

| Variable | Default | What it does |
| --- | --- | --- |
| `REVERIE_DOWNLOAD_DIR` | `downloads/` in the run folder | Folder where the session's browser saves downloads. The `--download-dir` option of `reverie start` wins over it. |

Without either, downloads go to `.reverie/runs/<session>-<stamp>/downloads/`. They never go to `~/Downloads`. The folder is created on start. Run `reverie status` to see it in the `download_dir` field. See [Runs and dashboard](/reverie/guides/runs-and-dashboard/#downloads).

## Dashboard

| Variable | Default | What it does |
| --- | --- | --- |
| `LAYA_AGENT_UI_PORT` | `7788` | Port for `reverie ui`. The `--port` flag overrides it. |

## Narration and audio

Narration is covered in [Narration](/reverie/guides/narration/).

| Variable | Default | What it does |
| --- | --- | --- |
| `LAYA_AGENT_NARRATION` | `summary` | `verbose` speaks every caption. Otherwise only milestones are spoken. |
| `LAYA_AGENT_SPEECH_RATE` | `185` | Speech rate for the offline `espeak` and `spd` fallbacks. |
| `LAYA_AGENT_BLUETOOTH_AUDIO` | `0` | `1`, `true`, `on` or `yes` plays a short near-silent sound first so a sleeping Bluetooth speaker wakes. |
| `LAYA_AGENT_AUDIO_WAKE` | `1.2` | Seconds of wake-up audio in Bluetooth mode. |
| `LAYA_AGENT_AUDIO_WAKE_IDLE` | `4` | Seconds of silence after which the wake-up sound plays again. |
| `SPEECH_PROVIDER` | `kokoro` | `kitten`, `kokoro` or `fish`. |
| `KITTEN_BASE_URL` | `http://127.0.0.1:8890` | Kitten server URL. |
| `KITTEN_MODEL` | `kitten-tts-nano-0.8` | Model name reported in the Kitten settings. |
| `KITTEN_VOICE` | `Jasper` | Kitten voice. Choices: Bella, Jasper, Luna, Bruno, Rosie, Hugo, Kiki, Leo. |
| `KOKORO_BASE_URL` | `http://127.0.0.1:8880` | Kokoro server URL. Any server with `POST /v1/audio/speech` works. |
| `KOKORO_MODEL` | `kokoro-82m` | Model name reported in the Kokoro settings. |
| `KOKORO_VOICE` | `af_heart` | Kokoro voice. |
| `KOKORO_VOICES` | empty | Comma-separated extra voices to list in the picker. |
| `KOKORO_VOICE_PREFIX` | `kokoro-voice-` | Prefix added to the voice name in requests. |
| `KOKORO_API_KEY` | none | Bearer token for the Kokoro server, if it needs one. |
| `FISH_AUDIO_API_TOKEN` | none | Fish Audio token. Required for `SPEECH_PROVIDER=fish`. |
| `FISH_AUDIO_VOICE_ID` | none | Fish Audio voice id. Required for Fish narration. |
| `FISH_AUDIO_TTS_MODEL` | `s2.1-pro-free` | One of `s1`, `s2-pro`, `s2.1-pro`, `s2.1-pro-free`, `drama-3-preview`. |
| `FISH_AUDIO_TTS_LATENCY` | `balanced` | One of `low`, `normal`, `balanced`. |

A configured voice (`KITTEN_VOICE`, `KOKORO_VOICE`, `FISH_AUDIO_VOICE_ID`) pins every utterance to that speaker.

## Local services script

`scripts/agent-services.sh` starts the local services behind Reverie: the laya.cpp decision server and one narration server.

```bash
scripts/agent-services.sh start
scripts/agent-services.sh status
scripts/agent-services.sh stop
```

| Subcommand | What it does |
| --- | --- |
| `start` | Starts laya.cpp, then Kitten (default) or Kokoro, and waits for each `/health` check. |
| `stop` | Stops laya, kokoro and kitten. |
| `status` | Shows whether each service is running. This is the default with no argument. |

All servers bind to `127.0.0.1`. The script prefers a Vulkan build and falls back to a CPU build. Logs and pid files go in `$XDG_RUNTIME_DIR/laya-agent/services`, or `~/.cache/laya-agent/services` without it.

| Setting | Default | Meaning |
| --- | --- | --- |
| `LAYA_PORT` | `8080` | laya.cpp port. |
| `LOCAL_TTS` | `kitten` | `kitten` or `kokoro`. Selects which narration server `start` runs. |
| `KITTEN_PORT` | `8890` | Kitten port. |
| `KITTEN_VOICE` | `Jasper` | Kitten voice. |
| `KOKORO_PORT` | `8880` | Kokoro port. |
| `KOKORO_VOICE` | `af_heart` | Kokoro voice. |
| `TOOLS_DIR` | `~/tools` | Folder that holds the checkouts below. Each one can also be set on its own. |
| `LAYA_CPP_DIR` | `$TOOLS_DIR/laya.cpp` | Where laya.cpp is built. |
| `CRISPASR_DIR` | `$TOOLS_DIR/CrispASR` | Where CrispASR (the Kokoro runtime) is built. |
| `KOKORO_MODEL_DIR` | `~/.cache/crispasr` | Kokoro model and voice files. |
| `KITTEN_PYTHON` | `$TOOLS_DIR/kitten-tts/.venv/bin/python` | Python interpreter with `kittentts` installed. |

Kitten runs on CPU. Kokoro uses about 450 MiB of GPU memory on Vulkan.

## Testing variables

| Variable | Default | What it does |
| --- | --- | --- |
| `REVERIE_LIVE_JEV` | unset | Set to `1` to run `tests/test_jev_live.py`, an opt-in check that calls the hosted Jev engine. It spends a little OpenRouter credit and is skipped without `OPENROUTER_API_KEY`. `scripts/jev-smoke.sh` sets it for you. |
