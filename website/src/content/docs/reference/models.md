---
title: Models and providers
description: How Reverie picks the pilot model, the text model and the Laya decision backend.
---

Reverie uses three kinds of model. Each has its own settings. See [Configuration](/reverie/reference/configuration/) for every variable.

| Role | What it does | Set with |
| --- | --- | --- |
| Pilot | Runs a whole test plan: turns each step into intents, checks results, moves between tabs. | `LAYA_AGENT_PILOT_MODEL` |
| Text model | Fills in field values, plans each goal, and powers Mercury, which overrules Laya when it is unsure. | `TEXT_MODEL` and friends |
| Fast layer: Laya or Jev | Makes the fast typed decision for each click or keystroke. | `LAYA_AGENT_ENGINE`, `LAYA_BACKEND` |

## Defaults in the code

| Setting | Default |
| --- | --- |
| `LAYA_AGENT_PILOT_MODEL` | `z-ai/glm-5.3-flash` |
| `TEXT_MODEL` | `deepseek-chat` |
| `TEXT_MODEL_BASE_URL` | `https://api.deepseek.com/v1` |
| `TEXT_MODEL_EFFORT` | `low` |
| `LAYA_BACKEND` | `auto` |
| `LAYA_BASE_URL` | `http://127.0.0.1:8080` |
| `LOCAL_DECISION_MODEL` | `aac6fef/laya-typed-decisions-mlx` |
| `REMOTE_DECISION_MODEL` | `typesafe/jev-1.13` |

`.env.example` sets `TEXT_MODEL_PROVIDER=openrouter` and sets both the pilot and the text model to `z-ai/glm-5.3-flash:nitro`.

## Pilot and text model

Both call an OpenAI-compatible chat API at the base URL plus `/chat/completions`. The text model and the pilot each have their own settings, so they can use different endpoints.

| Setting | Text model | Pilot |
| --- | --- | --- |
| Provider preset | `TEXT_MODEL_PROVIDER` | `LAYA_AGENT_PILOT_PROVIDER` |
| Base URL | `TEXT_MODEL_BASE_URL` | `LAYA_AGENT_PILOT_BASE_URL` |
| API key | `TEXT_MODEL_API_KEY` | `LAYA_AGENT_PILOT_API_KEY` |
| Model id | `TEXT_MODEL` | `LAYA_AGENT_PILOT_MODEL` |

The pilot falls back to the text model's provider, base URL and key for any of these it does not set. The model id does not fall back to `TEXT_MODEL` for the pilot: it defaults to `z-ai/glm-5.3-flash`.

### Providers

A provider preset picks the base URL. Set `TEXT_MODEL_PROVIDER` or `LAYA_AGENT_PILOT_PROVIDER` to one of these names. Any other value is an error.

| Provider | Base URL | Key, when no key variable is set |
| --- | --- | --- |
| `openrouter` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| `opencode-go` | `https://opencode.ai/zen/go/v1` | `OPENCODE_GO_API_KEY`, else the `opencode-go` entry in OpenCode's `auth.json` |
| `deepseek` | `https://api.deepseek.com/v1` | none |

With no provider and no base URL, Reverie uses the `deepseek` base URL. With a base URL but no provider, Reverie matches the host against the presets, so `TEXT_MODEL_BASE_URL=https://openrouter.ai/api/v1` behaves like `openrouter`. An unknown host gets no preset behaviour.

### Which value wins

For the pilot, each setting is the first one that is set in this order:

| Setting | 1st | 2nd | 3rd |
| --- | --- | --- | --- |
| Provider | `LAYA_AGENT_PILOT_PROVIDER` | `TEXT_MODEL_PROVIDER` | the host of the base URL |
| Base URL | `LAYA_AGENT_PILOT_BASE_URL` | `TEXT_MODEL_BASE_URL` | the provider's preset, else DeepSeek |
| API key | `LAYA_AGENT_PILOT_API_KEY` | `TEXT_MODEL_API_KEY` | the provider's own key source |

The text model uses the same order without the first column. An explicit base URL or key always beats a preset.

### Local servers

A base URL on `localhost`, `127.0.0.1` or `::1` needs no key. The code mentions Ollama, LM Studio and `mlx_lm` as servers that speak this API.

### OpenCode Go

For `opencode-go`, Reverie sends a `User-Agent` of `reverie/<version>` and one `x-opencode-session` header per process, which OpenCode Go uses to route and cache by conversation. Set `REVERIE_MODEL_SESSION` to choose that session id.

The key comes from `OPENCODE_GO_API_KEY`. If that is unset, Reverie reads the `opencode-go` entry of OpenCode's `auth.json`. Set `OPENCODE_AUTH_FILE` to read another tool's `auth.json` instead.

### Reasoning effort

The effort is `TEXT_MODEL_EFFORT` (default `low`). What Reverie sends depends on the provider:

| Endpoint | Sent |
| --- | --- |
| `openrouter`, or a provider it does not recognise | `{"reasoning": {"effort": ...}}`. `TEXT_MODEL_REASONING=none` sends `{"reasoning": {"enabled": false}}` instead. |
| `opencode-go` | `reasoning_effort: ...`. `TEXT_MODEL_REASONING=none` sends nothing. |
| `deepseek` | `{"thinking": {"type": "disabled"}}`, always. |

On a local endpoint, `TEXT_MODEL_REASONING=none` sends `reasoning_effort: none`; otherwise nothing is sent.

### Vision for the pilot

The pilot receives a screenshot with a numbered tag on every on-screen control. Set `LAYA_AGENT_PILOT_VISION=0` to turn that off. The pilot model must accept images to use it. A second call reviews each step's frames for broken UI; set `LAYA_AGENT_UI_REVIEW=0` to turn it off.

## Laya decision backend

`LAYA_BACKEND` accepts three values. Anything else is an error.

| Value | Behaviour |
| --- | --- |
| `http` | Talks to a laya.cpp server at `LAYA_BASE_URL`. Checks `/health` at start and posts decisions to `/v1/systemone`. |
| `mlx` | Runs the model in-process on Apple Silicon. Needs the `laya-mlx` extra: `uv sync --extra mlx`. |
| `auto` | The default. Uses `mlx` on an Apple Silicon Mac when `laya_mlx` is installed, otherwise `http`. |

For `http`, `LAYA_HTTP_TIMEOUT` sets the timeout in seconds (default 30) and `LAYA_TLS_CA` points at a CA file for TLS. The `scripts/agent-services.sh` script can start laya.cpp locally; see [Configuration](/reverie/reference/configuration/#local-services-script).

For `mlx`, `LOCAL_DECISION_MODEL` chooses the model to load.

## Decision engines

Under the pilot, a fast layer makes each click and keystroke. Two engines can be that layer. Mercury, the text model, steps in when the fast layer is unsure.

| | Laya | Jev |
| --- | --- | --- |
| Where it runs | Locally, through laya.cpp or MLX | Hosted on OpenRouter's Decisions API (`POST https://openrouter.ai/api/alpha/decisions`) |
| Model | `LOCAL_DECISION_MODEL` for MLX, or whatever the laya.cpp server loads | `typesafe/jev-1.13`; `REMOTE_DECISION_MODEL` overrides it |
| Key | none | `OPENROUTER_API_KEY` |
| Local model server | laya.cpp (or MLX) must be running | not needed |
| Cost and speed | free; depends on your hardware | about 250 ms and about $0.0001 to $0.0004 per decision |
| Choose it with | nothing (the default), or `--engine laya` | `reverie start --engine jev`, or `LAYA_AGENT_ENGINE=jev` |

### How to choose

- Pick Laya when you have a laya.cpp server or an Apple Silicon Mac and want no per-decision cost.
- Pick Jev when you do not want to run a local model. You pay a small fee per decision and need a network connection.

### Session engine and one-off engines

The session's engine is the fast layer under the whole stack. It drives `do`, `auto` and the pilot. Set it with `reverie start --engine jev` or `LAYA_AGENT_ENGINE=jev`. The flag wins over the variable. Any other value of `LAYA_AGENT_ENGINE` is an error.

`suggest`, `auto` and `step` also take `--engine`. With `--engine jev` they use Jev for that one command, without Mercury behind it, and the session's engine stays as it was. `suggest` and `auto` also accept `stack` (the default: the session's fast layer, with Mercury behind it), `mercury` and `laya`; `step` accepts `laya` and `jev`.

### Guards

- **Key.** Jev needs `OPENROUTER_API_KEY`. It also accepts `TEXT_MODEL_API_KEY` when `TEXT_MODEL_BASE_URL` points at OpenRouter. `TEXT_MODEL_PROVIDER=openrouter` alone does not supply the key.
- **Stated values.** Jev picks the element. For a text field, the text model supplies the value before anything runs, so the stated-value guard applies exactly as it does for Laya: only a value the goal or hints state is typed. Without Mercury behind it, Jev refuses an unstated value and nothing executes.
- **Trail.** Each suggestion in the trail carries `decision_model`, `decision_ms` and `decision_cost`, so you can see what each decision cost.

### Mercury

Mercury is the text model, not a separate model id. With the default `stack` engine, the fast layer proposes each step, and Mercury overrules when it is unsure. The same escalation rules apply to Laya and to Jev (low confidence, a looping action, an unstated value, and so on).

Set `LAYA_AGENT_MERCURY=off` to disable Mercury. An unsure step then goes back to the pilot unexecuted. With Mercury off, a fresh hint does not block the fast layer, because the hint is already in its goal. A fast layer that reports `DONE` is reported as `DONE`.

## `.env` snippets

### OpenRouter pilot and text model, local laya.cpp

```ini
TEXT_MODEL_PROVIDER=openrouter
OPENROUTER_API_KEY=your-key
TEXT_MODEL=z-ai/glm-5.3-flash:nitro
LAYA_AGENT_PILOT_MODEL=z-ai/glm-5.3-flash:nitro
TEXT_MODEL_EFFORT=low
LAYA_BACKEND=http
LAYA_BASE_URL=http://127.0.0.1:8080
```

The same key also serves the Jev engine.

### OpenCode Go pilot

The pilot uses OpenCode Go. The text model keeps its own endpoint.

```ini
TEXT_MODEL_PROVIDER=openrouter
OPENROUTER_API_KEY=your-openrouter-key
TEXT_MODEL=z-ai/glm-5.3-flash:nitro
LAYA_AGENT_PILOT_PROVIDER=opencode-go
LAYA_AGENT_PILOT_MODEL=glm-5.3-flash
# OPENCODE_GO_API_KEY=your-key
```

Without `OPENCODE_GO_API_KEY`, Reverie reads the key from OpenCode's `auth.json`.

### Separate pilot endpoint

The pilot uses a gateway of its own. The text model stays on its defaults.

```ini
LAYA_AGENT_PILOT_BASE_URL=https://gateway.example.com/v1
LAYA_AGENT_PILOT_API_KEY=your-gateway-key
LAYA_AGENT_PILOT_MODEL=your-pilot-model-id
TEXT_MODEL_API_KEY=your-text-model-key
```

### Any OpenAI-compatible provider

```ini
TEXT_MODEL_BASE_URL=https://api.example.com/v1
TEXT_MODEL_API_KEY=your-key
TEXT_MODEL=your-text-model-id
LAYA_AGENT_PILOT_MODEL=your-pilot-model-id
LAYA_BACKEND=http
```

### Local text model

```ini
TEXT_MODEL_BASE_URL=http://127.0.0.1:11434/v1
TEXT_MODEL=your-local-model-id
LAYA_AGENT_PILOT_MODEL=your-local-model-id
TEXT_MODEL_REASONING=none
LAYA_AGENT_PILOT_VISION=0
```

Turn vision off unless your local model accepts images.

### Laya on Apple Silicon (MLX)

```bash
uv sync --extra mlx
```

```ini
LAYA_BACKEND=mlx
# LOCAL_DECISION_MODEL=aac6fef/laya-typed-decisions-mlx
```

### Jev as the fast layer

```ini
OPENROUTER_API_KEY=your-key
LAYA_AGENT_ENGINE=jev
# REMOTE_DECISION_MODEL=typesafe/jev-1.13
```

### Without Mercury

```ini
LAYA_AGENT_MERCURY=off
```
