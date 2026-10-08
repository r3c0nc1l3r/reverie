---
title: Running specs
description: Drive a spec from the terminal as the orchestrator, from starting a session to handling checkpoints and reading the verdict.
---

The orchestrator is the person, script or coding agent at the terminal. It starts a session, loads a spec, starts the pilot, and handles anything the pilot cannot do itself. This page walks through that loop. The command is `reverie` (`laya-agent` is an alias). Every command takes `--session NAME`; the default is `default`, or the value of `LAYA_AGENT_SESSION`.

## The basic loop

```bash
uv run reverie --session demo start --url https://the-internet.herokuapp.com
uv run reverie --session demo spec examples/specs/demo-controls.md
uv run reverie --session demo pilot
uv run reverie --session demo events -f
uv run reverie --session demo progress
uv run reverie --session demo stop
```

### 1. Start a session

`reverie start --url URL` opens a Chromium window and a background daemon for the session. It prints the session's status when ready, and fails with exit code 2 if a session with that name already runs.

| Option | Meaning |
| --- | --- |
| `--url URL` | Required. The page to open first. |
| `--voice` | Narration voice: `auto` (default), `kitten`, `kokoro`, `fish`, `espeak`, `spd`, `off`. |
| `--headless` | No window; the watch page streams frames instead. |
| `--ui` | Also open the run dashboard in your browser. |
| `--goal TEXT` | A starting goal for the autonomous `step` and `run` commands. |
| `--engine laya\|jev` | The fast decision layer for the session (default Laya, or `LAYA_AGENT_ENGINE`). It drives `do`, `auto`, `step`, `run` and the pilot. See [Decision engines](/reverie/reference/models/#decision-engines). |
| `--profile DIR` | Use this Chromium profile directory instead of an isolated per-session one. |
| `--trail-dir DIR` | Where to write the run folder (default: `.reverie/runs`). |
| `--bluetooth` | Wake sleeping Bluetooth headphones before each spoken line. |

See [Narration](/reverie/guides/narration/) for the audio options.

### 2. Load the spec

```bash
uv run reverie --session demo spec .reverie/specs/login.md
```

The steps become the plan, and the Goal, Fixtures, Evidence, Guidance and Walkthrough sections are sent to the pilot as notes. The output reports how many notes were loaded. See [Writing specs](/reverie/guides/writing-specs/). To load a plan from a larger test-plan document, use `reverie plan --file FILE --section ID` instead.

### 3. Note fixture facts

Anything the spec does not say, such as an id created for this run, goes in as a note:

```bash
uv run reverie --session demo note "Use CASE-123 and the customer user@example.com"
```

Notes are for facts only. Never put passwords, codes or tokens in a note.

### 4. Start the pilot

```bash
uv run reverie --session demo pilot
```

The pilot starts in the background and the command returns at once, printing the command to follow it. Options:

| Option | Meaning |
| --- | --- |
| `--max N` | Maximum pilot operations in this run (default 30). |
| `--through N` | Run up to and including step N, then pause. |
| `--foreground` | Block until the pilot pauses, instead of returning. |

The pilot starts at the first step that is `pending` or `running`. Running `pilot` again after a pause resumes from there. `pilot stop` asks it to halt after its current operation.

### 5. Follow along

```bash
uv run reverie --session demo events -f
```

`events` prints one line per event with a reference number (`#12`). Without `--since` it shows the latest 40. With `-f` (`--follow`) it keeps polling until the pilot goes idle or `--timeout` seconds pass (default 1800). It ends with a line such as `next: --since 57  pilot: idle  paused: admin`, and `--since 57` lets you pick up from there.

`reverie progress` is the one-screen view: the plan with each step's status and note, findings, any waiting checkpoint, and the last eight events.

`reverie wait` blocks until the session needs you (default `--timeout` 900 seconds) and prints what it needs:

| `needs:` | Meaning |
| --- | --- |
| `admin` | A checkpoint is pending. |
| `steer` | The stack paused and wants direction (when the pilot is not running). |
| `person` | A prompt is waiting for a person's answer in the window. |
| `review` | The pilot has finished or paused; read the result. |
| `nothing` | The timeout passed with nothing to do. |

To watch in a browser, `reverie watch` opens the session's watch page, and `reverie ui` opens the run dashboard. See [Runs and the dashboard](/reverie/guides/runs-and-dashboard/).

## Why the pilot pauses

The pilot stops and reports a reason. `events` and `progress` show it as `paused`.

| Reason | What to do |
| --- | --- |
| `plan complete` | Read the verdict, then `stop`. |
| `admin` | A checkpoint is waiting; handle it (below). |
| `ask` | The pilot has a question, raised as a checkpoint. |
| `step N blocked` | The environment stopped the step. Fix it, then `mark N pending` and restart the pilot, or move on. |
| `stuck` | Too many operations on one step with no passing check; a checkpoint explains. |
| `stopped by the orchestrator` | You ran `pilot stop`, or the stall watchdog did. |
| `budget` | `--max` operations used. Run `pilot` again. |
| `reached step N` | You used `--through`. |
| `pilot error: ...` | The model call failed. Check your keys and models in [Configuration](/reverie/reference/configuration/), then run `pilot` again. |

## Handle checkpoints

```bash
uv run reverie --session demo checkpoints
```

This lists each checkpoint with an id, status (`pending`, `done`, `failed`, `skipped`), source, title and any command. Checkpoints with a `command` came from an `[admin]` step or from you.

There are two ways to resolve one.

**Run its command.** `exec` shows the command, asks for confirmation, runs it in your terminal, and records the exit code and output:

```bash
uv run reverie --session demo exec a1b2c3
uv run reverie --session demo exec a1b2c3 --yes --timeout 120
```

`--yes` skips the confirmation. `--timeout` defaults to 600 seconds. Exit code 0 resolves it as `done`, anything else as `failed`. Without `--yes` and without a terminal, `exec` refuses.

**Do the work yourself, then record it.** For example, read a mail API, then:

```bash
uv run reverie --session demo resolve a1b2c3 done --note "Confirmation link ends in /confirm/abc; the email arrived"
```

`resolve ID STATUS` takes `done`, `failed` or `skipped`, plus `--note` and `--exit-code`. Put the facts the pilot needs in the note, because the pilot reads it as evidence. Do not put tokens or passwords in it. When the checkpoint belongs to a step, resolving it marks that step.

Then restart the pilot:

```bash
uv run reverie --session demo pilot
```

You can also raise a checkpoint yourself with `reverie checkpoint "title" [--command CMD] [--step N]`. A command is never run by the session; only `exec` in your terminal runs it. When the pilot finishes the plan, any checkpoint still pending is closed as `skipped`.

## Passwords and dialogs

Sign-ins that need a secret are admin work. Click into the form (or let the pilot reach the page), then type the password into the one visible password field without it appearing in a command line, the trail or narration:

```bash
printf '%s' "$APP_PASSWORD" | uv run reverie --session demo secret
uv run reverie --session demo secret --env APP_PASSWORD --field "Password"
```

`secret` reads the value from `--env VAR`, from stdin, or from a hidden prompt on a terminal. It refuses an empty value and refuses unless exactly one visible password field is found. `--field` picks one by label or name.

Native alerts, confirms and prompts are accepted automatically. A prompt returns its default value. The pilot can switch to dismiss for a step, and its `dialogs` operation can also set the text an accepted prompt returns. That text must be a value the plan or notes state, like any typed value. Answer a dialog that is blocking the page yourself with `reverie dialog accept|dismiss [--text PROMPT_TEXT]`.

## Mark steps by hand

```bash
uv run reverie --session demo mark 2 pass --note "Verified by hand"
```

Statuses are `pending`, `running`, `pass`, `fail`, `blocked`, `skipped`. Use `pending` to reset a step to be retested; that also clears its earlier findings.

## Other ways to drive

The pilot is the main mode. The lower layers are available directly, which is useful when the pilot is stuck or you want one precise action.

| Mode | Commands |
| --- | --- |
| One intent | `do "INTENT"` runs the stack on one goal. Options: `--hint` (repeatable), `--max N` (default 6), `--until-text`, `--until-url`. Quote any value to type: `do "Enter '300' in the rate field"`. |
| One proposal at a time | `suggest [--hint TEXT] [--engine stack\|mercury\|laya\|jev] [--goal TEXT]` shows one proposed action and runs nothing. `accept` runs it. `reject [--hint TEXT]` drops it and adds a steering hint. |
| Fast loop | `auto [--max N] [--min-confidence 0.55] [--until-text T] [--until-url U] [--goal G] [--engine ...]` repeats suggest and accept until the stack pauses. |
| Direct control | `observe [--grep TEXT] [--limit N] [--text CHARS] [--settle]` lists elements with ids. Then `act`, `click`, `fill`, `select`, each taking an id like `e7` or `--label`/`--hint`. `fill` and `act` take `--text` (and `--redact` to keep the value out of logs), `select` and `act` take `--option`. Also `hover`, `press Enter\|Tab\|Escape`, `goto URL`, `back`. |
| Tabs | `tabs`, `tab new URL [--isolated]`, `tab close`, `switch [TARGET]`, `tidy-tabs`. |
| Checks | `check [--text T] [--absent T] [--url FRAGMENT]` asserts what is on the page. |
| Autonomous | `step` and `run [--max-steps N]` use the engine with `--goal`. |
| Narration and people | `say TEXT`, `ask QUESTION [--choices A,B]`, `reply [CHOICE] [--text T]`, `recap`. |

`do` and `auto` pause for the same reasons: low confidence, the stack saying it is done or blocked, a loop, a stall, a refused action (a commit button the intent did not name, or a value it did not state), or your until-condition. See the guards in [Concepts](/reverie/start/concepts/).

Other helpers: `status`, `goal TEXT`, `history`, `screenshot [PATH]`, `watch`, `ui`, `runs list|prune|hide|import-legacy`.

## Finish

```bash
uv run reverie --session demo stop
```

`stop` closes the browser and the daemon, and finalizes the run. The evidence stays in `.reverie/runs/`. Closing the browser window also ends the session.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success. |
| 1 | `check` failed. |
| 2 | Refused: the request was invalid for the current state (for example an unknown checkpoint, a session already running, an empty secret), or the command line was malformed. |
| 3 | Error: the session did not answer, failed to start, or hit an internal error. |
| 4 | No session with that name is running. |

## Driving Reverie from a coding agent

Reverie is built to be driven by a coding agent in a terminal, one command at a time.

- **Machine-readable output.** `--json` prints the raw JSON response. It can go anywhere on the line: `reverie --session demo progress --json` works. `events` and `progress` always print their text form.
- **Block instead of poll.** `reverie --session demo wait` returns when something needs you, and `needs:` says what.
- **A typical agent loop.** Start the session, load the spec, start the pilot, then repeat: `wait`. If `needs` is `admin`, read the checkpoint, do the work (or `exec` it), `resolve` it with a factual note, and run `pilot` again. If `review`, run `progress` and read the verdict.
- **Keep secrets out of the loop.** Pass them with `secret --env` or stdin, never as arguments, and never in notes.
- **Read the evidence.** `progress` lists steps, statuses, notes and findings. The full record is `.reverie/runs/<run>/trail.jsonl`.
- **Exit codes** let a script branch on `check` (1), refusal (2) and a missing session (4).

For install and first-run setup, see [First run](/reverie/start/first-run/). All commands and options are in the [CLI reference](/reverie/reference/cli/).
