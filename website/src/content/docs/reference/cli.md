---
title: CLI reference
description: Every reverie command, its options and defaults, and the exit codes.
---

`reverie` drives a browser session one command at a time. `laya-agent` is an alias for the same program. The examples use `uv run reverie`, as in the README.

## Global options

Global options go before the command name. `--json` also works anywhere on the line.

| Option | Default | Description |
| --- | --- | --- |
| `--session NAME` | `$LAYA_AGENT_SESSION`, else `default` | The session to talk to. Every command except `init`, `runs`, `walkthrough`, `ui` and `start` (which creates the session) needs a running session with this name. |
| `--json` | off | Print the raw JSON result instead of the formatted text. |
| `--version` | | Print the version (`reverie 0.1.0`) and exit. |
| `-h`, `--help` | | Show help for `reverie` or for any command. |

### How the session name is chosen

1. `--session NAME`, if you pass it.
2. Otherwise the `LAYA_AGENT_SESSION` environment variable.
3. Otherwise `default`.

Use a different name for each browser session you run at the same time.

```bash
uv run reverie --session demo start --url https://example.com
export LAYA_AGENT_SESSION=demo   # or set it once for the shell
uv run reverie status
```

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The command succeeded. |
| `1` | `check` failed: an assertion did not hold. |
| `2` | The command was refused. Examples: the session is already running, the session answered with a conflict, an unknown run or checkpoint id, `exec` was not confirmed, `tab new` has no URL, or `secret` got an empty value. |
| `3` | An error. The session did not start, did not answer, or returned an error. |
| `4` | No session with that name is running. Run `reverie start --url ...` first. |

Refusals print `refused: ...` and errors print `error: ...` or `reverie: ...` on stderr.

## Project and runs

### `init`

Create `.reverie/` (a README, `.gitignore`, `runs/` and `specs/`) in the current directory. If it already exists, nothing is created.

```text
reverie init
```

### `runs`

List, hide, or import recorded runs. Runs are read from `.reverie/runs` (plus the legacy `artifacts/agent-sessions` folder) unless you pass `--root`.

```text
reverie runs {list,prune,hide,import-legacy} [ids ...] [--root ROOT]
             [--from DIR] [--copy] [--map-source OLD=NEW]
```

| Action | What it does |
| --- | --- |
| `list` | Print each run's id, result and title. |
| `prune` | Hide broken or failed finished runs. Their trails stay on disk. |
| `hide RUN_ID ...` | Hide the given runs. |
| `import-legacy` | Bring runs into `.reverie/runs`: by default move them from `artifacts/agent-sessions`; with `--from`, import them from another directory. Write a `run.json` summary for each run that lacks one. |

| Option | Default | Description |
| --- | --- | --- |
| `--root ROOT` | `.reverie/runs` and the legacy folder | Read runs from this directory. Repeatable. |
| `--from DIR` | `artifacts/agent-sessions` | `import-legacy` only. The runs directory to import, such as another checkout's `artifacts/agent-sessions`. |
| `--copy` | off | `import-legacy` only. Copy the runs and keep the originals. Without it, the runs are moved. |
| `--map-source OLD=NEW` | none | `import-legacy` only. Rewrite spec path prefixes in the imported trails, from `OLD` to `NEW`. Repeatable. |

`import-legacy` skips a run whose folder already exists in `.reverie/runs`, and merges the source's hidden list. It prints `moved N runs` or `copied N runs`, then each folder. See [Runs and dashboard](/reverie/guides/runs-and-dashboard/#import-runs-from-another-checkout).

```bash
reverie runs import-legacy --from /path/to/other-checkout/artifacts/agent-sessions --copy \
    --map-source /path/to/other-checkout/specs/=/path/to/project/.reverie/specs/
```

### `walkthrough`

Print click-by-click Markdown for a run. With `--write`, put it into a spec.

```text
reverie walkthrough [--write SPEC] [--root ROOT] run
```

| Argument or option | Default | Description |
| --- | --- | --- |
| `run` | required | Run id (see `runs list`). |
| `--write SPEC` | off | Replace or add the `## Walkthrough` section of this spec file. |
| `--root ROOT` | `.reverie/runs` and the legacy folder | Read runs from this directory. Repeatable. |

## Session lifecycle

### `start`

Open a headed, narrated browser session in the background. The command waits up to 60 seconds for it to be ready, then prints its status. It exits with code `2` if the session name is already running.

```text
reverie start --url URL [--voice VOICE] [--goal GOAL] [--engine {laya,jev}]
              [--trail-dir TRAIL_DIR] [--profile PROFILE] [--download-dir DOWNLOAD_DIR]
              [--headless] [--ui] [--bluetooth]
```

| Option | Default | Description |
| --- | --- | --- |
| `--url URL` | required | The page to open. |
| `--voice VOICE` | `auto` | Narration voice. One of `auto`, `kitten`, `kokoro`, `fish`, `espeak`, `spd`, `off`. |
| `--goal GOAL` | none | Goal for autonomous `step` and `run`. |
| `--engine {laya,jev}` | `$LAYA_AGENT_ENGINE`, else Laya | The session's fast decision layer. It drives `do`, `auto`, `step`, `run` and the pilot. Jev needs `OPENROUTER_API_KEY`. See [Decision engines](/reverie/reference/models/#decision-engines). |
| `--trail-dir TRAIL_DIR` | none | Directory for the session's trail. |
| `--profile PROFILE` | per-session, isolated | Chromium profile directory. |
| `--download-dir DOWNLOAD_DIR` | `$REVERIE_DOWNLOAD_DIR`, else `downloads/` in the run folder | Save browser downloads here. It never defaults to `~/Downloads`. |
| `--headless` | off | No window. The watch page streams frames instead. |
| `--ui` | off | Also open the run dashboard in your default browser. |
| `--bluetooth` | off | Bluetooth audio mode: wake sleeping headphones before each spoken line. |

```bash
uv run reverie --session demo start --url https://the-internet.herokuapp.com/login --headless
```

### `status`

Show the session's status, URL and title, and the folder where its browser saves downloads.

```text
reverie status
```

The output includes a `download_dir:` line. With `--json`, the same value is the `download_dir` field.

### `stop`

Stop the session.

```text
reverie stop
```

### `reload`

Reload the session's code in place. This is a developer aid. It keeps the browser and your login.

```text
reverie reload
```

### `audio`

Show or set narration audio. With no options it shows the current settings.

```text
reverie audio [--bluetooth {on,off}] [--wake WAKE]
```

| Option | Default | Description |
| --- | --- | --- |
| `--bluetooth {on,off}` | unchanged | Turn Bluetooth audio mode on or off. |
| `--wake WAKE` | unchanged | Seconds of wake-up audio in Bluetooth mode. |

## Plans and specs

### `spec`

Load a stored spec. Its `## Steps` become the plan. Its Goal, Fixtures, Evidence, Guidance and Walkthrough sections go to the pilot as notes. A spec without a `## Steps` section is rejected. See [Writing specs](/reverie/guides/writing-specs/).

```text
reverie spec file
```

### `plan`

Load a test plan from a Markdown file, from `--step` options, or both. Numbered and bulleted lines become steps.

```text
reverie plan [--title TITLE] [--file FILE] [--section SECTION] [--step STEP]
```

| Option | Default | Description |
| --- | --- | --- |
| `--title TITLE` | the file's first heading | Plan title. |
| `--file FILE` | none | Read steps from this Markdown file. |
| `--section SECTION` | whole file | Read only under the heading that starts with this text, for example `LOGIN-01`. The section ends at the next heading of the same or a higher level. |
| `--step STEP` | none | Add one step. Repeatable. |

:::note
Steps given with `--step` are placed first, then steps read from `--file`.
:::

```bash
uv run reverie plan --file plan.md --section LOGIN-01
uv run reverie plan --title "Smoke" --step "Open the login page" --step "Sign in"
```

### `mark`

Set a plan step's status.

```text
reverie mark [--note NOTE] step {pending,running,pass,fail,blocked,skipped}
```

| Argument or option | Default | Description |
| --- | --- | --- |
| `step` | required | Step number. |
| `status` | required | One of `pending`, `running`, `pass`, `fail`, `blocked`, `skipped`. |
| `--note NOTE` | empty | A note saved with the status. |

```bash
uv run reverie mark 2 pass --note "Banner shown"
```

### `note`

Give the pilot a fixture fact such as a record id, an email address or a URL. Do not put secrets in notes.

```text
reverie note text
```

### `goal`

Set the current sub-goal for the fast model.

```text
reverie goal goal
```

## Driving the pilot

The pilot works through the loaded plan in the background. See [Running specs](/reverie/guides/running-specs/).

### `pilot`

Start the pilot on the loaded plan, or stop it. The action defaults to `start`. The pilot runs in the background, and the command prints how to follow it with `events`.

```text
reverie pilot [{start,stop}] [--foreground] [--max MAX] [--through THROUGH]
```

| Option | Default | Description |
| --- | --- | --- |
| `start` or `stop` | `start` | `stop` halts a running pilot. |
| `--foreground` | off | Block until the pilot pauses. |
| `--max MAX` | `30` | The most operations the pilot may run. |
| `--through THROUGH` | none | Stop before this step number + 1, so the pilot ends after step N. |

```bash
uv run reverie --session demo spec .reverie/specs/login.md
uv run reverie --session demo pilot
uv run reverie --session demo events -f
```

### `events`

Show session events. Each line starts with a stable reference such as `#12`. The command prints a closing line with the next `--since` value and the pilot state.

```text
reverie events [--since SINCE] [--follow] [--timeout TIMEOUT]
```

| Option | Default | Description |
| --- | --- | --- |
| `--since SINCE` | latest 40 events | Start after this reference. |
| `--follow`, `-f` | off | Keep streaming until the pilot is idle and no new events arrive, or the timeout is reached. |
| `--timeout TIMEOUT` | `1800` | Seconds to follow before giving up. |

### `progress`

Print a one-screen summary: status, pilot state, plan steps with their findings, waiting checkpoints and the last events.

```text
reverie progress
```

### `do`

The default driver. The stack carries out one intent and pauses when it needs you. Quote any value to type.

```text
reverie do [--hint HINT] [--max MAX] [--until-text TEXT] [--until-url URL] intent
```

| Argument or option | Default | Description |
| --- | --- | --- |
| `intent` | required | What to accomplish on the page. |
| `--hint HINT` | none | Steering for the fast model, such as field names or which button. Repeatable. |
| `--max MAX` | `6` | The most steps to take. |
| `--until-text TEXT` | none | Stop when this text appears. |
| `--until-url URL` | none | Stop when this URL condition is met. |

```bash
uv run reverie --session demo do "Sign in as the demo user" --hint "use the Login button"
```

## Checkpoints and orchestrator

A checkpoint is a request for terminal work that the session never runs by itself. The orchestrator (you, or the agent driving `reverie`) reviews and runs it.

### `checkpoint`

Raise an admin checkpoint for the orchestrator.

```text
reverie checkpoint [--command COMMAND] [--step STEP] title
```

| Argument or option | Default | Description |
| --- | --- | --- |
| `title` | required | What the checkpoint is for. |
| `--command COMMAND` | none | The terminal command the orchestrator should run. |
| `--step STEP` | none | The plan step this checkpoint completes. |

### `checkpoints`

List admin checkpoints, with their status and command.

```text
reverie checkpoints
```

### `wait`

Block until the session needs the orchestrator: an admin checkpoint, a steer request, or a person.

```text
reverie wait [--timeout TIMEOUT]
```

| Option | Default | Description |
| --- | --- | --- |
| `--timeout TIMEOUT` | `900` | Seconds to wait. |

### `exec`

Run a pending checkpoint's command in this terminal and record the result. It prints the command and asks `Run it? [y/N]` first. It refuses (exit `2`) if the checkpoint is unknown, is not pending, has no command, or is not confirmed.

```text
reverie exec [--yes] [--timeout TIMEOUT] id
```

| Argument or option | Default | Description |
| --- | --- | --- |
| `id` | required | Checkpoint id. |
| `--yes` | off | Run without the interactive confirmation. |
| `--timeout TIMEOUT` | `600` | Seconds before the command is stopped. A timeout is recorded as exit `124`. |

The checkpoint is resolved as `done` on exit code 0, otherwise `failed`.

### `resolve`

Record the outcome of a checkpoint you handled yourself.

```text
reverie resolve [--note NOTE] [--exit-code EXIT_CODE] id {done,failed,skipped}
```

| Argument or option | Default | Description |
| --- | --- | --- |
| `id` | required | Checkpoint id. |
| `status` | required | One of `done`, `failed`, `skipped`. |
| `--note NOTE` | empty | A note saved with the outcome. |
| `--exit-code EXIT_CODE` | none | The exit code of what you ran. |

## Step-by-step driving

Use these when you want to approve each move yourself.

### `suggest`

The fast model proposes one step. Nothing runs until `accept`.

```text
reverie suggest [--engine {stack,mercury,laya,jev}] [--hint HINT] [--goal GOAL]
```

| Option | Default | Description |
| --- | --- | --- |
| `--engine` | `stack` | `stack`: the session's fast layer (Laya, or Jev when the session uses it) proposes and Mercury overrules when it is unsure. Other choices: `mercury`, `laya`, `jev`. With `jev`, Jev decides this one command without Mercury. |
| `--hint HINT` | none | Steer the model, for example `use the search box, not the menu`. |
| `--goal GOAL` | none | Goal for this suggestion. |

### `accept`

Execute the pending suggestion.

```text
reverie accept
```

### `reject`

Drop the pending suggestion. You can add a steering hint for the next one.

```text
reverie reject [--hint HINT]
```

### `auto`

A fast loop. It pauses on low confidence, on DONE, BLOCKED or ADMIN, or when an until-condition is met.

```text
reverie auto [--engine ENGINE] [--max MAX] [--min-confidence CONF]
             [--until-text TEXT] [--until-url URL] [--goal GOAL]
```

| Option | Default | Description |
| --- | --- | --- |
| `--engine` | `stack` | One of `stack`, `mercury`, `laya`, `jev`. With `jev`, Jev decides without Mercury. |
| `--max MAX` | `8` | The most steps to take. |
| `--min-confidence CONF` | `0.55` | Pause when confidence drops below this. |
| `--until-text TEXT` | none | Stop when this text appears. |
| `--until-url URL` | none | Stop when this URL condition is met. |
| `--goal GOAL` | none | Set the sub-goal before the loop starts. |

### `step` and `run`

Autonomous Laya/Jev driving. `step` takes one step. `run` loops.

```text
reverie step [--goal GOAL] [--engine {laya,jev}] [--confirm]
reverie run  [--goal GOAL] [--engine {laya,jev}] [--confirm] [--max-steps MAX_STEPS]
```

| Option | Default | Description |
| --- | --- | --- |
| `--goal GOAL` | none | The goal. |
| `--engine {laya,jev}` | the session's engine | The engine to use for this command. |
| `--confirm` | off | Ask in the window before each action. |
| `--max-steps MAX_STEPS` | `20` | `run` only. The most steps to take. |

### `history`

Show the steps taken so far.

```text
reverie history
```

## Direct control of elements

First list the elements with `observe`, then act on them by id. See [Concepts](/reverie/start/concepts/).

### `observe` (alias `snapshot`)

List observed elements. The ids work as refs such as `e5`.

```text
reverie observe [--grep GREP] [--limit LIMIT] [--text CHARS] [--settle]
```

| Option | Default | Description |
| --- | --- | --- |
| `--grep GREP` | none | Only show elements matching this text. |
| `--limit LIMIT` | `80` | The most elements to show. |
| `--text CHARS` | `0` | Also print this many characters of visible page text. |
| `--settle` | off | Let the page settle before observing. |

### `act`, `click`, `fill`, `select`

Run an action on an observed element. `click`, `fill` and `select` fix the kind of action. `act` does not fix the kind, so you choose with `--text` or `--option`.

```text
reverie act    [ref] [--label LABEL] [--hint HINT] [--value VALUE] [--text TEXT] [--redact] [--option OPTION] [--say SAY]
reverie click  [ref] [--label LABEL] [--hint HINT] [--value VALUE] [--say SAY]
reverie fill   [ref] [--label LABEL] [--hint HINT] [--value VALUE] [--text TEXT] [--redact] [--say SAY]
reverie select [ref] [--label LABEL] [--hint HINT] [--value VALUE] [--option OPTION] [--say SAY]
```

| Option | Applies to | Default | Description |
| --- | --- | --- | --- |
| `ref` | all | none | Element id from `observe`, for example `e7`. |
| `--label LABEL` | all | none | Match by label instead of id. The label must be unique. |
| `--hint HINT` | all | none | Match by field hint (name or id). Stable across re-renders. |
| `--value VALUE` | all | none | With `--hint`, match the element whose value is this (for radio buttons). |
| `--text TEXT` | `act`, `fill` | none | Text to type. |
| `--redact` | `act`, `fill` | off | Keep the typed value out of narration and logs. |
| `--option OPTION` | `act`, `select` | none | Option label or value for a select. |
| `--say SAY` | all | default phrase | Narrate this instead of the default phrase. |

```bash
uv run reverie --session demo observe --grep username
uv run reverie --session demo fill e4 --text "tomsmith"
uv run reverie --session demo click --label "Login"
```

### `hover`

Move the pointer over an element. Use it to open hover menus.

```text
reverie hover [--label LABEL] [ref]
```

### `dialog`

Accept or dismiss a native alert, confirm or prompt dialog.

```text
reverie dialog [--text TEXT] {accept,dismiss}
```

| Option | Default | Description |
| --- | --- | --- |
| `--text TEXT` | none | Text to enter into a prompt dialog. |

### `secret`

Type a secret into the one visible password field. The value comes from the variable named by `--env`, or else from a hidden prompt (on a terminal) or from standard input. An empty value is refused.

```text
reverie secret [--field FIELD] [--env ENV]
```

| Option | Default | Description |
| --- | --- | --- |
| `--field FIELD` | none | Label or name substring to pick the password field. |
| `--env ENV` | none | Read the value from this environment variable. |

```bash
DEMO_PASSWORD='...' uv run reverie --session demo secret --env DEMO_PASSWORD
```

### `press`

Press a key.

```text
reverie press {Enter,Tab,Escape}
```

## Tabs and navigation

### `goto`

Open a URL in the current tab.

```text
reverie goto url
```

### `back`

Press the browser Back button.

```text
reverie back
```

### `tabs`

List the open tabs. The current tab is marked with `*`.

```text
reverie tabs
```

### `tab`

Open a new tab or close the current one.

```text
reverie tab {new,close} [url] [--isolated]
```

| Argument or option | Default | Description |
| --- | --- | --- |
| `new` or `close` | required | The action. `new` needs a URL. |
| `url` | none | The URL for `new`. |
| `--isolated` | off | Use a fresh cookie jar, to test a link signed out. |

### `switch`

Switch to another tab.

```text
reverie switch [target]
```

`target` is optional. Without it, reverie switches to the newest other tab.

### `tidy-tabs`

Close every tab except the current one.

```text
reverie tidy-tabs
```

## Checks, notes and conversation

### `check`

Assert visible text or the URL. It exits with code `1` if the check fails.

```text
reverie check [--text TEXT] [--absent ABSENT] [--url URL] [--link LINK] [--href HREF]
```

| Option | Default | Description |
| --- | --- | --- |
| `--text TEXT` | none | Text that must be visible. |
| `--absent ABSENT` | none | Text that must not be visible. |
| `--url URL` | none | The URL must match this. |
| `--link LINK` | none | Visible link text. |
| `--href HREF` | none | With `--link`, check the link's target without printing it. |

```bash
uv run reverie --session demo check --text "You logged into a secure area!"
```

### `say`

Narrate text as a caption and speech.

```text
reverie say [--wait] text
```

| Option | Default | Description |
| --- | --- | --- |
| `--wait` | off | Wait until the line has been spoken. |

### `recap`

Speak a medium-level summary of the steps since the last recap.

```text
reverie recap [--note NOTE]
```

| Option | Default | Description |
| --- | --- | --- |
| `--note NOTE` | empty | A note to include. |

### `ask`

Show a question in the window and wait for a person to answer it.

```text
reverie ask [--choices CHOICES] [--no-text] [--timeout TIMEOUT] question
```

| Option | Default | Description |
| --- | --- | --- |
| `--choices CHOICES` | `Continue` | Comma-separated buttons. |
| `--no-text` | off | Do not offer a free-text box. |
| `--timeout TIMEOUT` | `900` | Seconds to wait for an answer. |

### `reply`

Answer the pending prompt from the terminal.

```text
reverie reply [--text TEXT] [choice]
```

| Argument or option | Default | Description |
| --- | --- | --- |
| `choice` | `Continue` | The button to press. |
| `--text TEXT` | empty | Free-text answer. |

### `screenshot`

Save a screenshot.

```text
reverie screenshot [path]
```

`path` is optional.

## Dashboard and review

### `ui`

Open the run dashboard, which shows current and past runs, in your default browser. One dashboard is shared by all sessions. See [Runs and dashboard](/reverie/guides/runs-and-dashboard/).

```text
reverie ui [--print-only] [--root ROOT]
```

| Option | Default | Description |
| --- | --- | --- |
| `--print-only` | off | Print the URL without opening a browser. |
| `--root ROOT` | `.reverie/runs` | Read runs from this directory instead. Repeatable. |

### `watch`

Open this session's single-session watch page. Use it with `start --headless`.

```text
reverie watch [--print-only]
```

| Option | Default | Description |
| --- | --- | --- |
| `--print-only` | off | Print the URL without opening a browser. |
