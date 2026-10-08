---
title: Troubleshooting and FAQ
description: Fixes for common Reverie errors, an explanation of its safety guards, and answers to frequent questions.
---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | OK. |
| 1 | A `check` failed. |
| 2 | Refused: Reverie declined to do something and executed nothing. |
| 3 | Error. |
| 4 | No session. |

Messages that begin with `refused:` mean a guard stopped an action on purpose. Read the rest of the message; it says what to change.

## Session problems

### `reverie: no session named 'demo'. Run reverie start --url ...` (exit 4)

No session with that name is running. Session commands use `--session NAME`, which defaults to `default` (or the `LAYA_AGENT_SESSION` environment variable). Check that you pass the same name to `start` and to every later command, then start the session:

```bash
reverie --session demo start --url https://example.com
```

If the browser window was closed, the session ended with it. Start it again.

### `reverie: session 'demo' is already running` (exit 2)

A session with that name exists. Use it, stop it with `reverie --session demo stop`, or pick another name.

### `reverie: session 'demo' did not answer`

The session process is not responding on its local port. Stop it and start a new one. Its log is `<name>.log` in the `laya-agent` folder under `$XDG_RUNTIME_DIR` (or `~/.cache`).

### `reverie: session failed to start.`

Reverie prints the end of the session log after this line. Look there for the cause. Common ones follow.

**`No Chromium-family browser found. Set LAYA_AGENT_BROWSER.`** Install Chromium, Chrome, or Brave so one of `chromium`, `google-chrome-stable`, `google-chrome`, `brave`, or `chromium-browser` is on your `PATH`. Or set the browser yourself:

```bash
export LAYA_AGENT_BROWSER=/path/to/chrome
```

**`LAYA_AGENT_BROWSER=... was not found`**. The variable is set but points at nothing. Fix the path or unset the variable.

**`Chromium did not open its debugging port within 20 seconds`**. The browser started but did not become ready. Try again, and check that no policy or sandbox blocks it.

Reverie also gives up with `session did not become ready within 60 seconds` if startup takes longer than a minute.

### The dashboard

`reverie ui` uses port 7788 and moves to any free port when that one is busy, so a busy port is not an error. Use the address that `reverie ui` prints. To prefer another port, set `LAYA_AGENT_UI_PORT`.

If you see `reverie: the dashboard did not start; see ...`, open the log file named in the message.

If the dashboard shows no runs, check that you run it from the project that holds `.reverie/`, or pass `--root`. See [Runs and dashboard](/reverie/guides/runs-and-dashboard/).

## Model and service problems

### `Unable to reach local Laya service at ... Start laya.cpp or change LAYA_BASE_URL.`

Commands that let the stack decide (`do`, `suggest`, `auto`, and the pilot) use a laya.cpp server, unless the session engine is Jev. In the default `stack` mode, Reverie hands the decision to the text model when Laya fails. You then see `escalated: Laya unavailable: ...` in the proposal, or a pilot step that ends blocked with `Laya escalated (...) and Mercury is disabled` when `LAYA_AGENT_MERCURY=off`. With `suggest --engine laya`, the error is `laya could not decide: ...`. Start laya.cpp, for example with `scripts/agent-services.sh start`, and make sure `LAYA_BASE_URL` matches its address (default `http://127.0.0.1:8080`). Reverie checks the server's `/health` endpoint first.

Related messages:

| Message | Meaning |
|---|---|
| `Local Laya service at ... timed out after N seconds. No browser action was executed.` | The server is too slow. Raise `LAYA_HTTP_TIMEOUT` (seconds). |
| `... is unavailable or overloaded (HTTP 503)` | The server is busy. Wait and retry. |
| `Laya service at ... is not ready` | `/health` did not report `ok`. Wait for the model to load. |
| `LAYA_BACKEND must be one of: auto, http, mlx.` | Fix the variable. |
| `LAYA_BACKEND=mlx requires the optional MLX dependencies on Apple Silicon.` | Run `uv sync --extra mlx`, or set `LAYA_BACKEND=http`. |

Direct control (`observe`, `act`, `check`) does not use Laya.

### `The text model needs TEXT_MODEL_API_KEY`

The pilot, recaps, and the text helpers call an OpenAI-compatible model at `TEXT_MODEL_BASE_URL` (default `https://api.deepseek.com/v1`). Set a key for it:

- Default or any other endpoint: set `TEXT_MODEL_API_KEY`.
- OpenRouter: set `TEXT_MODEL_PROVIDER=openrouter` and `OPENROUTER_API_KEY`.
- OpenCode Go: set `TEXT_MODEL_PROVIDER=opencode-go` (or `LAYA_AGENT_PILOT_PROVIDER` for the pilot only) and `OPENCODE_GO_API_KEY`, or sign in with OpenCode so its `auth.json` holds the key.
- A separate pilot endpoint: set `LAYA_AGENT_PILOT_API_KEY`.

A key is not needed when the base URL is `localhost` or `127.0.0.1`. The daemon reads `.env` files when it starts, so check that the key is in a file Reverie reads and is not empty. See [How `.env` is loaded](/reverie/reference/configuration/#how-env-is-loaded) and [Models and providers](/reverie/reference/models/).

`Unknown model provider ...` means a provider variable is not `openrouter`, `opencode-go` or `deepseek`.

In a run, this error shows up as a pause: `pilot error: The text model needs TEXT_MODEL_API_KEY (or LAYA_AGENT_PILOT_API_KEY, or an opencode-go key)...`. Fix the setting and run `pilot` again; it resumes from the first open step.

Other errors in that group, such as `Model provider returned HTTP 429` or `The text model returned no choices`, come from the provider. The pilot pauses with `pilot error: ...` instead of crashing. Wait, or change `LAYA_AGENT_PILOT_MODEL` or `TEXT_MODEL`.

Provider errors include the provider's own message, shortened, for example `Model provider returned HTTP 402: ...; no action executed.` Read that message first. A credit or quota problem shows up there.

### `Jev needs OPENROUTER_API_KEY, or TEXT_MODEL_API_KEY with TEXT_MODEL_BASE_URL set to OpenRouter.`

The Jev engine (`reverie start --engine jev`, `LAYA_AGENT_ENGINE=jev`, or `--engine jev` on `suggest`, `auto` and `step`) calls OpenRouter's Decisions API. Set `OPENROUTER_API_KEY` in a file Reverie reads, and restart the session so the daemon picks it up. `TEXT_MODEL_PROVIDER=openrouter` alone does not supply the key. See [Decision engines](/reverie/reference/models/#decision-engines).

Other Jev messages:

| Message | Meaning |
|---|---|
| `The jev decision engine is unavailable: ...` | The engine could not start, usually for the missing key above. Drive the session with `observe` and `act` instead. |
| `jev could not decide: ...` | The call failed or the answer was unusable. When the provider sent a message, it follows the HTTP status, for example an out-of-credit notice. |
| `Jev would type '...', which the goal does not state. Nothing executed; state the value in quotes.` | The stated-value guard. Quote the value in the intent, hint or step. |
| `LAYA_AGENT_ENGINE must be laya or jev` | Fix the variable. |

### `Mercury is disabled (LAYA_AGENT_MERCURY=off)`

Mercury is the text model that takes over when Laya is unsure. This message appears when you ask for `--engine mercury` while it is turned off. Set `LAYA_AGENT_MERCURY=on` to allow it.

## The pilot stops

The pilot stops, rather than repeating itself, in these cases. Run `reverie --session NAME progress` to see why. The `last pause` line gives the reason.

| Pause reason | What happened | What to do |
|---|---|---|
| `admin` or `ask` | A checkpoint or a question needs you. | Run `checkpoints`, handle it, `resolve <id> done`, then `pilot` again. |
| `stuck` | The pilot made no progress on one step after `LAYA_AGENT_PILOT_STUCK` operations (default 12). A checkpoint is raised. | Look at the browser and the events. Fix the cause or add a `note` or hint, mark the step yourself, then `pilot`. |
| `step N blocked` | The pilot marked step N blocked. | Read its note in `progress`. |
| `pilot error: ...` | A model call failed or returned something invalid. | See the model errors above. |
| `stopped by the orchestrator` | You ran `pilot stop`. | Run `pilot` to resume. |
| `budget` | It used its operation budget. | Run `pilot` again. |

### Stalls turn into a checkpoint

If a running pilot logs no activity for `LAYA_AGENT_STALL_SECONDS` seconds (default 240), a watchdog records the stall, asks the pilot to stop at its next step, and raises a checkpoint: `The pilot has shown no activity for N s (hung model or browser call)`. Check `progress`, handle the checkpoint, and run `pilot` to resume.

### Loops

The stack pauses with a reason like `loop: the same action ran three times` or `stalled: 3 actions changed nothing`. The suggestion guard also refuses `Laya is looping on the same action` and `Laya is repeating a two-step cycle`. Take over with `observe` and `act`, or add a hint.

## A click was refused (exit code 2)

A button named like a commit verb (Yes, OK, Confirm, Delete, Remove, Submit, Save, Approve, Send, Pay, Agree, and similar) only runs when the intent names it. Otherwise you get:

```text
refused: The stack wanted to click 'Delete (button)', which commits a change the intent did not ask for. Nothing executed; name it in the intent to allow it.
```

Say what you mean in the intent, for example `do "Click Delete on the first row"`. The pilot follows the same rule, so mention such buttons in the spec step or its Guidance section. Direct `act` commands are yours, so they are not blocked by this guard.

Other `refused:` messages and their fixes:

| Message | Fix |
|---|---|
| `Mercury would type '...', which the goal does not state.` | Put the value in the intent, or in a spec `note`. Reverie types only stated values. |
| `Pilot would type '...', which the plan and notes do not state` | Add the value to the spec's Fixtures or to a `note`. |
| `This intent is read-only; the stack wanted to change '...'` | The pilot marked the intent read-only. Use `act` yourself if you do want the change. |
| `The stack chose '...', which the pilot said to avoid.` | Change the intent or act directly. |
| `The page changed since the suggestion. Nothing was executed; suggest again.` | Run `suggest` again. |
| `No pending suggestion; run suggest first` | Run `suggest` before `accept`. |
| `Set a goal first` | Run `goal "..."` before `suggest`. |
| `Expected exactly one matching element, found N.` | Use an element id from `observe`, or a more exact `--label`. |
| `e7 is a text field; pass the text to type` | Add `--text`. |
| `e7 is a click target; it does not take text` | Remove `--text`. |
| `Only http and https URLs` | `goto` and `tab new` accept only web addresses. |
| `Pilot may only go to hosts already open or named in the plan or notes` | Name the host in the spec. |
| `refused: unknown checkpoint ID` | Check the id with `checkpoints`. |
| `Checkpoint ... is already done` | It was resolved already. |

Reverie also masks tokens and codes in trails and model context, and the session never runs shell commands itself. A checkpoint's command runs only when you run `reverie exec <id>` and confirm.

## Dialogs

Native `alert`, `confirm`, and `prompt` boxes would block the browser, so Reverie answers them itself. The default is to accept. Set `LAYA_AGENT_DIALOGS=dismiss` to dismiss instead. The pilot can switch the answer during a run, and can set the text an accepted `prompt` returns (it must be a value the plan or notes state). Without that, a prompt returns its default value. The dialog text and the answer given are recorded in the trail. To answer a dialog that is already blocking the page, run `reverie --session NAME dialog accept` or `dialog dismiss`.

## FAQ

### Is `laya-agent` the same as `reverie`?

Yes. Both console commands run the same program. Use whichever you like.

### Where are runs stored?

In `.reverie/runs/` in your project. Reverie uses the nearest `.reverie/` in the current folder or a parent, and the current folder if there is none. Older runs in `artifacts/agent-sessions/` are still shown until you run `reverie runs import-legacy`. See [Runs and dashboard](/reverie/guides/runs-and-dashboard/).

### Where do browser downloads go?

To `.reverie/runs/<session>-<stamp>/downloads/`, never `~/Downloads`. Choose another folder with `reverie start --download-dir /path/to/downloads` or `REVERIE_DOWNLOAD_DIR`. Run `reverie status` to see the folder in `download_dir`. See [Runs and dashboard](/reverie/guides/runs-and-dashboard/#downloads).

### Can I run without a visible browser window?

Yes. Start the session with `--headless`. No window opens, and the session streams frames to its watch page. Run `reverie --session NAME watch` to open it.

### Do I have to use narration?

No. Start with `--voice off`. Captions still appear. See [Narration](/reverie/guides/narration/).

### Does Reverie use my own browser profile?

No. Each session starts a dedicated browser with its own profile. Use `--profile DIR` to choose where that profile lives.

### Can several sessions run at once?

Yes. Each `--session` name has its own browser, and one dashboard shows them all.

### A run shows as `incomplete` or `running` but nothing is going on.

The session ended before the plan finished. Run `reverie runs prune` to hide broken and failed runs. Their evidence stays on disk.

### Where do I report a bug?

See [Contributing](/reverie/project/contributing/).
