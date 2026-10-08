---
name: reverie-orchestrator
description: Drive Reverie browser sessions from a coding agent as the orchestrator. Use when running a Reverie test turn by turn, when the pilot pauses for an [admin] checkpoint, a sign-in, or a question, when you need to resolve checkpoints with terminal proof, or when you must act on a page directly (observe, act, check, do, suggest) because the pilot or the decision engine is stuck.
---

# Orchestrating Reverie from a coding agent

Reverie has three layers under you, the **orchestrator**:

| Layer | Who | Does |
|---|---|---|
| Pilot | a multimodal model | Runs the spec: one operation per turn (an intent, a direct action, a check, a mark, a finding, a checkpoint). |
| Decision engine (layer 1) | Jev (hosted, default) or Laya (local) | Makes each click and keystroke for an intent. |
| Escalation model (layer 2) | the text model | Overrules the decision engine when it is unsure, looping, or off-goal. |

You start sessions, sign in, load specs, start the pilot, answer checkpoints, and judge verdicts. The session
daemon never runs shell commands: anything that needs a terminal comes to you.

Pass `--session NAME` on every command (or set `REVERIE_SESSION`). Add `--json` before the command for
machine-readable output, e.g. `reverie --session widgets --json status`.

## The loop

```bash
S="--session dispatcher"
reverie $S start --url http://127.0.0.1:8765/login --headless   # FieldOps demo
# sign in (see "Secrets and sign-in"), then:
reverie $S spec specs/fs-01-create-and-dispatch.md
reverie $S note "The newest work order today is the one this test creates"   # facts only, no secrets
reverie $S pilot --foreground --max 150   # blocks until the pilot pauses
reverie $S progress                       # read the pause reason and the steps
```

Without `--foreground`, `pilot` returns at once and runs in the background: poll `progress` until it shows
`pilot: idle`, or use `wait --timeout 900`, which returns when a checkpoint, a steering request, or a question
needs you (not when the plan simply completes).

Then act on the pause reason and start the pilot again:

| `last pause` | Do |
|---|---|
| `admin` | Handle the checkpoint (below), then `pilot`. |
| `budget` | `pilot` again (each start runs at most `--max` operations; default 30). |
| `plan complete` | Review the verdict (`reverie-run-review`), then `stop`. |
| a stall or "stuck" checkpoint | Read the last events (`events --since N`), fix the cause (often the spec), resolve, `pilot`. |

`reverie $S events -f` streams events until the pilot stops. `reverie $S pilot stop` halts it at the next
boundary.

## Checkpoints

```bash
reverie $S checkpoints                               # pending ones show their id, title, and command
reverie $S exec <id> --yes                           # run an [admin] step's own command here, record the output
reverie $S resolve <id> done --note "11 | WO-1011 | Leak under the prep sink"   # or failed / skipped
reverie $S checkpoint "Reset the fixtures before step 3"                         # raise one yourself
```

- `exec` runs the command from **your** working directory (run Reverie from the project, e.g. `examples/fieldops`).
- Put the evidence in `--note`: the row, the count, the link you found. The pilot reads it.
- Resolving a checkpoint that belongs to a step marks that step (`done` → pass, `failed` → fail, `skipped`).
- Checkpoints raised by the pilot or by a page never carry a command; you decide what to run.

## Secrets and sign-in

Password fields are hidden from every model. The orchestrator signs in:

```bash
reverie $S observe --grep "user\|sign"               # find the refs, e.g. e2 (Username) and e4 (Sign in)
reverie $S fill e2 --text dana.dispatch
reverie $S secret --env FIELDOPS_PASSWORD            # types into the one visible password field; never logged
reverie $S click e4
```

Never put a password in a spec, a note, or a command line. One session per test account: two sessions on the
same account can sign each other out.

## Acting on the page yourself

Use these when the pilot is stuck on one control, or to explore before writing a spec.

| Command | Use |
|---|---|
| `observe [--grep TEXT] [--text CHARS]` | List the elements with their ids (`e7`), optionally with page text. |
| `act e7 [--text "..."] [--option "..."]`, `click`, `fill`, `select`, `hover` | One direct action on an observed element. `--redact` keeps a typed value out of logs. |
| `do "Type 'la' into Color"` | The decision engine (and the escalation model) carry out one intent, pausing when unsure. |
| `suggest` → `accept` / `reject --hint "..."` | One proposed step at a time; nothing runs until `accept`. |
| `check --text "..." [--absent "..."] [--url part]` | Assert the page; exit 1 on failure. `--link TEXT --href part` checks a link's target without printing it. |
| `goto URL`, `back`, `tabs`, `tab new URL [--isolated]`, `switch`, `tidy-tabs` | Navigation. `--isolated` opens a signed-out tab with its own cookies. |
| `dialog accept|dismiss [--text "..."]` | Answer a native dialog that is blocking the page. |
| `mark 3 pass --note "evidence"` | Set a plan step's verdict yourself. |

Values you ask the stack to type must be quoted in the intent (`do "Type 'robin@example.org' into Email"`);
committing buttons (Save, Delete, Submit, ...) run only when the intent names them. Refusals exit with code 2.

## Choosing the decision engine

`reverie start --engine jev|laya` (or `REVERIE_DECISION_ENGINE`) sets the session's engine for `do`, `auto`, and
the pilot. `suggest`, `auto`, `step` and `run` also take `--engine` for one command. Jev needs
`OPENROUTER_API_KEY`; Laya needs a local laya.cpp server (`LAYA_BASE_URL`) or MLX.

## Finish cleanly

- `reverie $S stop` every session you started. Check `ps` for none left behind; never kill processes by name.
- Report the verdict with its evidence: steps, findings, and the checkpoint notes.
- After a code change to Reverie itself, `reverie $S reload` picks up most modules; daemon changes need a restart.

Exit codes: `0` ok, `1` check failed, `2` refused, `3` error, `4` no session.
