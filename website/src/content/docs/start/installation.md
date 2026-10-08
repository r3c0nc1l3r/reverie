---
title: Installation
description: Install Reverie from a clone or a git URL, set up the browser and model services, and check that it runs.
---

Reverie is a Python package. It is not on PyPI, so you install it from its [GitHub repository](https://github.com/r3c0nc1l3r/reverie).

## Requirements

| Need | Why |
|---|---|
| Python 3.12 or newer | The package declares `requires-python = ">=3.12"`. |
| A Chromium-family browser | Reverie opens its own browser window for each session. |
| A model API key | The pilot (the multimodal model that runs your spec) calls an OpenAI-compatible chat API, such as OpenRouter. A local endpoint needs no key. |
| A laya.cpp server | Makes each click and keystroke locally. Only needed for commands that let the stack decide, such as `do`, `suggest`, and the pilot. |

### Browser

Reverie starts a dedicated browser with a fresh profile per session. It never touches your own browser profile. It looks for the first of these on your `PATH`:

`chromium`, `google-chrome-stable`, `google-chrome`, `brave`, `chromium-browser`

To use another browser, set `LAYA_AGENT_BROWSER` to its name or full path:

```bash
export LAYA_AGENT_BROWSER=/path/to/chrome
```

If the variable points to a file that does not exist, or no browser is found, the session fails to start. See [Troubleshooting](/reverie/help/troubleshooting/).

### laya.cpp

Reverie talks to a local laya.cpp server over HTTP. The default address is `http://127.0.0.1:8080`. Change it with `LAYA_BASE_URL`. You build and run laya.cpp yourself; see [Optional services](#optional-services) for a helper script.

### Model API key

Create a key with your provider, for example at [openrouter.ai](https://openrouter.ai), and put it in a `.env` file (see [Configure](#configure)).

## Install

### With uv, from a clone

```bash
git clone https://github.com/r3c0nc1l3r/reverie
cd reverie
uv sync
```

Then run commands with `uv run reverie ...` from the clone.

To run Reverie in a container, see [Run in Docker](/reverie/guides/docker/).

### With uv, as a tool

`uv tool install` puts the `reverie` command on your `PATH`:

```bash
uv tool install git+https://github.com/r3c0nc1l3r/reverie
```

### With pip

Use a virtual environment with Python 3.12 or newer.

```bash
pip install git+https://github.com/r3c0nc1l3r/reverie
```

Or, from a clone, for an editable install:

```bash
git clone https://github.com/r3c0nc1l3r/reverie
cd reverie
pip install -e .
```

Both routes install two commands that do the same thing: `reverie` and `laya-agent`. This documentation uses `reverie`.

### Optional: MLX on Apple Silicon

The `mlx` extra adds `laya-mlx`, which runs the Laya decision model in-process on Apple Silicon instead of through a laya.cpp server.

```bash
uv sync --extra mlx
```

Select it with `LAYA_BACKEND=mlx`. The default, `auto`, uses MLX only on an Apple Silicon Mac where `laya_mlx` is installed. Everywhere else it uses HTTP.

## Configure

Run Reverie from the project you test. Reverie reads settings from your shell environment, then from `.env` files. The first value found wins. See [How `.env` is loaded](/reverie/reference/configuration/#how-env-is-loaded) for the full list.

Copy the example file from the Reverie clone into your project:

```bash
cp /path/to/reverie/.env.example .env
```

Then edit `.env`. A minimal setup for OpenRouter is:

```ini
TEXT_MODEL_PROVIDER=openrouter
OPENROUTER_API_KEY=your-openrouter-key
LAYA_BASE_URL=http://127.0.0.1:8080
```

The pilot and the text model call an OpenAI-compatible endpoint. `TEXT_MODEL_PROVIDER` picks the base URL, and `OPENROUTER_API_KEY` supplies the key. Without a provider or `TEXT_MODEL_BASE_URL`, the endpoint defaults to `https://api.deepseek.com/v1` and the key comes from `TEXT_MODEL_API_KEY`. Comments must be on their own line: everything after `=` is the value.

:::tip
Keep API keys out of your repositories. Put them in `~/.config/reverie/.env` and restrict the file, so every project shares them:

```bash
mkdir -p ~/.config/reverie
printf 'OPENROUTER_API_KEY=your-openrouter-key\n' > ~/.config/reverie/.env
chmod 600 ~/.config/reverie/.env
```

The project's own `.env` then holds only settings, and wins over the user file when both set a variable.
:::

See [Models and providers](/reverie/reference/models/) for other providers, a separate pilot endpoint and local models, and the [configuration reference](/reverie/reference/configuration/) for every variable.

## Optional services

`scripts/agent-services.sh` in the clone starts, stops, and checks the local services: laya.cpp and a local text-to-speech server.

```bash
scripts/agent-services.sh start
scripts/agent-services.sh status
scripts/agent-services.sh stop
```

The script finds laya.cpp through `LAYA_CPP_DIR` and the Kitten Python environment through `KITTEN_PYTHON`. Set `LOCAL_TTS=kokoro` to start Kokoro instead of Kitten. Set `LAYA_PORT` and `KITTEN_PORT` to change ports. Logs and pid files go in `laya-agent/services` under `$XDG_RUNTIME_DIR` (or `~/.cache`). Narration is optional; see [Narration](/reverie/guides/narration/).

## Verify

```bash
reverie --version
```

With a clone and uv, run `uv run reverie --version`. You should see `reverie` followed by a version number. Then continue to the [first run](/reverie/start/first-run/).
