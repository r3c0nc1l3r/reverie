---
title: Models and providers
description: How Reverie picks the decision engine (Jev or Laya), the escalation model, the pilot model and the providers.
---

Reverie uses three kinds of model. Each has its own settings. One OpenRouter key covers the default setup. See [Configuration](/reverie/reference/configuration/) for every variable.

| Role | What it does | Set with |
| --- | --- | --- |
| Pilot | Runs a whole test plan: turns each step into intents, checks results, moves between tabs. | `REVERIE_PILOT_MODEL` |
| Text model | Fills in field values, plans each goal, and is the escalation model (Mercury by default), which overrules the decision engine when it is unsure. | `TEXT_MODEL` and friends |
| Decision engine: Jev or Laya | Makes the fast typed decision for each click or keystroke. Jev is hosted and the default; Laya is local. | `REVERIE_DECISION_ENGINE`, `LAYA_BACKEND` |

## Defaults in the code

| Setting | Default |
| --- | --- |
| `REVERIE_PILOT_MODEL` | `z-ai/glm-5.3-flash` |
| `TEXT_MODEL` | `deepseek-chat` |
| `TEXT_MODEL_BASE_URL` | `https://api.deepseek.com/v1` |
| `TEXT_MODEL_EFFORT` | `low` |
| `REVERIE_DECISION_ENGINE` | `jev` |
| `REVERIE_ESCALATION` | `on` |
| `REVERIE_DECISION_MIN_CONFIDENCE` | `0.6` |
| `LAYA_BACKEND` | `auto` |
| `LAYA_BASE_URL` | `http://127.0.0.1:8080` |
| `LOCAL_DECISION_MODEL` | `aac6fef/laya-typed-decisions-mlx` |
| `REMOTE_DECISION_MODEL` | `typesafe/jev-1.13` |

`.env.example` sets `TEXT_MODEL_PROVIDER=openrouter` and sets both the pilot and the text model to `z-ai/glm-5.3-flash:nitro`. It also sets `REVERIE_ESCALATION=off`; the code default is on.

## Pilot and text model

Both call an OpenAI-compatible chat API at the base URL plus `/chat/completions`. The text model and the pilot each have their own settings, so they can use different endpoints.

| Setting | Text model | Pilot |
| --- | --- | --- |
| Provider preset | `TEXT_MODEL_PROVIDER` | `REVERIE_PILOT_PROVIDER` |
| Base URL | `TEXT_MODEL_BASE_URL` | `REVERIE_PILOT_BASE_URL` |
| API key | `TEXT_MODEL_API_KEY` | `REVERIE_PILOT_API_KEY` |
| Model id | `TEXT_MODEL` | `REVERIE_PILOT_MODEL` |

The pilot falls back to the text model's provider, base URL and key for any of these it does not set. The model id does not fall back to `TEXT_MODEL` for the pilot: it defaults to `z-ai/glm-5.3-flash`.

### Providers

A provider preset picks the base URL. Set `TEXT_MODEL_PROVIDER` or `REVERIE_PILOT_PROVIDER` to one of these names. Any other value is an error.

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
| Provider | `REVERIE_PILOT_PROVIDER` | `TEXT_MODEL_PROVIDER` | the host of the base URL |
| Base URL | `REVERIE_PILOT_BASE_URL` | `TEXT_MODEL_BASE_URL` | the provider's preset, else DeepSeek |
| API key | `REVERIE_PILOT_API_KEY` | `TEXT_MODEL_API_KEY` | the provider's own key source |

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

The pilot receives a screenshot with a numbered tag on every on-screen control. Set `REVERIE_PILOT_VISION=0` to turn that off. The pilot model must accept images to use it. A second call reviews each step's frames for broken UI; set `REVERIE_UI_REVIEW=0` to turn it off.

## Decision engines

Layer 1, the decision engine, makes each click and keystroke under the pilot. Layer 2, the escalation model, steps in when the decision engine is unsure. Two engines can be layer 1.

| Engine | Where it runs | Needs | How to choose it |
| --- | --- | --- | --- |
| Jev (default) | Hosted on OpenRouter's Decisions API (`POST https://openrouter.ai/api/alpha/decisions`), model `typesafe/jev-1.13`; `REMOTE_DECISION_MODEL` overrides it | `OPENROUTER_API_KEY`; no local server | Nothing, or `reverie start --engine jev` |
| Laya | Locally, through laya.cpp (`LAYA_BASE_URL`) or MLX (`LAYA_BACKEND=mlx`; `LOCAL_DECISION_MODEL` is the MLX model) | A local model server or an Apple Silicon Mac; no key | `reverie start --engine laya`, or `REVERIE_DECISION_ENGINE=laya` |

Jev costs about $0.0001 to $0.0004 and takes about 250 ms per decision. Laya is free; speed depends on your hardware.

### How to choose

- Stay on Jev when you already have an OpenRouter key and do not want to run a model server. You pay a small fee per decision and need a network connection.
- Pick Laya when you want to decide locally and offline, with no per-decision cost, and you have a laya.cpp server or an Apple Silicon Mac.

### Session engine and one-off engines

The session's engine drives `do`, `auto` and the pilot. Set it with `reverie start --engine laya` or `REVERIE_DECISION_ENGINE=laya`. The flag wins over the variable. Any other value of `REVERIE_DECISION_ENGINE` is an error. The older name `LAYA_AGENT_ENGINE` still works.

`suggest`, `auto` and `step` also take `--engine`. With `--engine jev` or `--engine laya` they use that engine alone for that one command, and the session's engine stays as it was. `suggest` and `auto` also accept `stack` (the default: the decision engine proposes, the escalation model overrules) and `escalation` (the escalation model alone; the old value `mercury` still works). `step` and `run` accept `laya` and `jev`.

### When the key is missing

Jev is the default, so a session needs a key unless you choose Laya. Without `OPENROUTER_API_KEY`, the session refuses to start. It says to set `OPENROUTER_API_KEY` (or `TEXT_MODEL_API_KEY` with `TEXT_MODEL_BASE_URL` on OpenRouter), or to use the local Laya engine with `REVERIE_DECISION_ENGINE=laya` or `reverie start --engine laya`. Reverie does not fall back to Laya on its own.

`TEXT_MODEL_PROVIDER=openrouter` alone does not supply the key.

### Guards

- **Stated values.** Jev picks the element. For a text field, the text model supplies the value before anything runs, so the stated-value guard applies to every engine: only a value the goal or hints state is typed. With the escalation model off, Jev refuses an unstated value and nothing executes.
- **Trail.** Each suggestion in the trail carries `decision_model`, `decision_ms` and `decision_cost`, so you can see what each decision cost. See [Runs and dashboard](/reverie/guides/runs-and-dashboard/).

### Laya backends

`LAYA_BACKEND` accepts three values. Anything else is an error. It applies only when the engine is Laya.

| Value | Behaviour |
| --- | --- |
| `http` | Talks to a laya.cpp server at `LAYA_BASE_URL`. Checks `/health` at start and posts decisions to `/v1/systemone`. |
| `mlx` | Runs the model in-process on Apple Silicon. Needs the `laya-mlx` extra: `uv sync --extra mlx`. |
| `auto` | The default. Uses `mlx` on an Apple Silicon Mac when `laya_mlx` is installed, otherwise `http`. |

For `http`, `LAYA_HTTP_TIMEOUT` sets the timeout in seconds (default 30) and `LAYA_TLS_CA` points at a CA file for TLS. The `scripts/agent-services.sh` script can start laya.cpp locally; see [Configuration](/reverie/reference/configuration/#local-services-script). For `mlx`, `LOCAL_DECISION_MODEL` chooses the model to load.

## Escalation model

The escalation model (layer 2) is the text model, called Mercury by default. It is not a separate model id: it uses `TEXT_MODEL` and the other `TEXT_MODEL_*` settings. With the default `stack` engine, the decision engine proposes each step, and the escalation model overrules when the engine is unsure: low confidence (below `REVERIE_DECISION_MIN_CONFIDENCE`, default `0.6`), a looping action, an unstated value, and so on. The same rules apply to Jev and to Laya.

Set `REVERIE_ESCALATION=off` to turn it off. An unsure step then goes back to the pilot unexecuted. With it off, a fresh hint does not block the decision engine, because the hint is already in its goal. A decision engine that reports `DONE` is reported as `DONE`. The older name `LAYA_AGENT_MERCURY` still works.

## `.env` snippets

### OpenRouter for everything (the default)

```ini
TEXT_MODEL_PROVIDER=openrouter
OPENROUTER_API_KEY=your-key
TEXT_MODEL=z-ai/glm-5.3-flash:nitro
REVERIE_PILOT_MODEL=z-ai/glm-5.3-flash:nitro
TEXT_MODEL_EFFORT=low
```

The same key also serves the Jev decision engine.

### OpenCode Go pilot

The pilot uses OpenCode Go. The text model keeps its own endpoint.

```ini
TEXT_MODEL_PROVIDER=openrouter
OPENROUTER_API_KEY=your-openrouter-key
TEXT_MODEL=z-ai/glm-5.3-flash:nitro
REVERIE_PILOT_PROVIDER=opencode-go
REVERIE_PILOT_MODEL=glm-5.3-flash
# OPENCODE_GO_API_KEY=your-key
```

Without `OPENCODE_GO_API_KEY`, Reverie reads the key from OpenCode's `auth.json`.

### Separate pilot endpoint

The pilot uses a gateway of its own. The text model stays on its defaults.

```ini
REVERIE_PILOT_BASE_URL=https://gateway.example.com/v1
REVERIE_PILOT_API_KEY=your-gateway-key
REVERIE_PILOT_MODEL=your-pilot-model-id
TEXT_MODEL_API_KEY=your-text-model-key
```

### Any OpenAI-compatible provider

```ini
TEXT_MODEL_BASE_URL=https://api.example.com/v1
TEXT_MODEL_API_KEY=your-key
TEXT_MODEL=your-text-model-id
REVERIE_PILOT_MODEL=your-pilot-model-id
# Jev still needs OPENROUTER_API_KEY; to avoid it, decide locally:
REVERIE_DECISION_ENGINE=laya
LAYA_BACKEND=http
LAYA_BASE_URL=http://127.0.0.1:8080
```

### Local text model

```ini
REVERIE_DECISION_ENGINE=laya
TEXT_MODEL_BASE_URL=http://127.0.0.1:11434/v1
TEXT_MODEL=your-local-model-id
REVERIE_PILOT_MODEL=your-local-model-id
TEXT_MODEL_REASONING=none
REVERIE_PILOT_VISION=0
```

Turn vision off unless your local model accepts images.

### Local Laya through laya.cpp

```ini
REVERIE_DECISION_ENGINE=laya
LAYA_BACKEND=http
LAYA_BASE_URL=http://127.0.0.1:8080
```

### Laya on Apple Silicon (MLX)

```bash
uv sync --extra mlx
```

```ini
REVERIE_DECISION_ENGINE=laya
LAYA_BACKEND=mlx
# LOCAL_DECISION_MODEL=aac6fef/laya-typed-decisions-mlx
```

### Jev as the decision engine (the default)

```ini
OPENROUTER_API_KEY=your-key
# REVERIE_DECISION_ENGINE=jev
# REMOTE_DECISION_MODEL=typesafe/jev-1.13
```

### Without the escalation model

```ini
REVERIE_ESCALATION=off
```
