---
title: Concepts
description: The three layers, sessions, plans, checkpoints, guards and run evidence that Reverie is built from.
---

Reverie runs browser tests that you write as Markdown specs. This page explains the moving parts so the rest of the docs make sense. The command is `reverie`; `laya-agent` is an older alias for it.

## The three layers

Three kinds of worker share the job. Each does the part it is cheapest and safest at. The decision engine and the escalation model together are called the stack.

| Layer | What it is | What it does |
| --- | --- | --- |
| Decision engine, with an escalation model | The decision engine is Jev (hosted on OpenRouter, the default) or Laya (local). The escalation model is a text model (Mercury by default) that overrules the engine when it is unsure. | Makes each single click or keystroke on the page. |
| The pilot | A multimodal model that sees screenshots (default `z-ai/glm-5.3-flash`, set with `REVERIE_PILOT_MODEL`) | Reads the plan, turns each step into short intents for the decision engine, runs checks, marks steps, records findings and lessons. |
| The orchestrator | You, or a coding agent, at a terminal | Starts the session, loads the spec, handles admin work (database reads, mail lookups, secrets), and reviews the verdict. |

```text
  orchestrator   starts sessions, loads specs, resolves checkpoints, reviews
       |         (terminal commands; the only layer that runs shell commands)
       v
     pilot       plans the next move, checks results, marks steps pass/fail/blocked
       |         (one validated operation per turn; never a selector, shell or secret)
       v
  decision engine    picks the element and clicks or types it
  + escalation model (Jev or Laya; a text model steps in when unsure)
       |
       v
    Chromium     one dedicated browser window per session
```

The decision engine is Jev (hosted on OpenRouter, the default, needs `OPENROUTER_API_KEY`) or Laya (local through laya.cpp or MLX, no key). Choose it for the session with `reverie start --engine laya` or `REVERIE_DECISION_ENGINE=laya`. See [Decision engines](/reverie/reference/models/#decision-engines).

When the decision engine's confidence is low, when it would type a value the intent does not state, or when it starts looping, the escalation model takes over for that action. If the escalation model is also unsure, the stack pauses and hands control up to the pilot, and the pilot hands it up to the orchestrator. `REVERIE_ESCALATION=off` turns the escalation model off.

## Sessions

A session is one browser plus one run. `reverie start --url ...` spawns a small background daemon that:

- opens a dedicated Chromium window with its own profile, so your own browser profile is never touched;
- answers commands from the CLI on a loopback port (127.0.0.1 only);
- writes the run's evidence to `.reverie/runs/<session>-<timestamp>/`.

Sessions have names. Pass `--session NAME` to every command (or set `REVERIE_SESSION`); the default name is `default`. You can run several sessions side by side, each with its own browser. `reverie stop` closes the browser and ends the run.

## Plans and specs

A plan is a numbered list of steps. You load one from a spec (`reverie spec file.md`) or directly (`reverie plan --step ...`). A spec is a Markdown file with front matter and sections. Its steps become the plan, and its other sections are passed to the pilot as notes. See [Writing specs](/reverie/guides/writing-specs/).

## Steps and statuses

Each step has a status:

| Status | Meaning |
| --- | --- |
| `pending` | Not started. |
| `running` | The pilot is working on it. |
| `pass` | Proven by a check the pilot ran during that step. |
| `fail` | A check showed the wrong outcome, or a medium or high finding was recorded. |
| `blocked` | The environment prevented the test (missing data, an error that cannot be passed). |
| `skipped` | Not run, or a checkpoint for it was skipped. |

The test result follows the steps: any `fail` makes the test `fail`; otherwise it is `pass` once every step is `pass` or `skipped`, `blocked` if some step is blocked and none is pending, and `running` until then. A failed step does not stop the run, so later steps still gather evidence.

The pilot cannot mark a step `pass` unless a check it ran in that step passed, or while the step has a medium or high finding.

## Checkpoints

A checkpoint is a request for the orchestrator. The session never runs shell commands itself, so anything that needs a terminal becomes a checkpoint. They come from four places:

- an `[admin]` step in the spec (it may carry a command in backticks);
- the pilot, when it needs a database read, a log, a mail lookup, a sign-in with a secret, or has a question;
- the orchestrator, with `reverie checkpoint "title"`;
- the stall and loop detectors.

The detectors raise a checkpoint on their own:

- **Stall.** If a running pilot logs no activity for 240 seconds (a hung model or browser call), Reverie records a stall, asks the pilot to stop at its next boundary, and raises a checkpoint. Change the limit with `REVERIE_STALL_SECONDS`.
- **No progress.** If the pilot makes 12 operations on one step without a new passing check, it pauses with a checkpoint. Change the limit with `REVERIE_PILOT_STUCK`.
- **Loops.** Inside one intent, the stack stops when an action changes nothing three times in a row, or when the same action runs three times. It also hands off to the escalation model when the decision engine repeats an action or a two-step cycle.

The pilot pauses while a checkpoint is pending. You resolve it as `done`, `failed` or `skipped`, then start the pilot again. If the checkpoint belongs to a step, resolving it marks that step. See [Running specs](/reverie/guides/running-specs/).

## Findings

A finding is a defect or deviation the pilot records without stopping the test. It has a severity (`high`, `medium`, `low`), what is wrong, what was expected, what the app did, and an optional workaround. A step with a medium or high finding must be marked `fail`. Findings show in `reverie progress` and in the run dashboard.

## Guards

Several rules hold no matter what a model asks for. They are enforced in code, not left to the prompt.

- **Commit buttons need explicit intent.** A click on a control whose label starts with a committing word (Yes, OK, Confirm, Delete, Remove, Submit, Save, Approve, Send, Pay, Reset, Update and similar) runs only if the intent or hints name that word. Otherwise nothing runs and the stack pauses. So a spec should split "open the dialog" and "confirm the dialog" into separate steps. Radio buttons, checkboxes, options and tabs are exempt.
- **Only stated values are typed.** The decision engine and the escalation model type only values the intent or hints quote (`'300'`), or a distinctive token such as an email or number that appears in them. The pilot's direct `act` on a text field is checked against the plan and notes. Anything else is refused.
- **Masking of tokens and codes.** Query-style values named `token`, `code`, `otp`, `key`, `sig`, `signature`, `password` or `pwd` are replaced with `[redacted]` before they reach the trail, a model prompt or the screen. Values typed with `--redact` are logged as `[redacted]`, and `reverie secret` never records its value.
- **No secrets for the pilot.** The pilot is told never to guess passwords, codes or tokens. Sign-ins with a secret go through an admin checkpoint, and you type the password with `reverie secret`.
- **Read-only and avoid lists.** For a navigation-only intent the pilot can mark it read-only, and then nothing is typed or selected. It can also name labels the stack must never click.
- **Pilot navigation is limited.** The pilot may only go to hosts that are already open or named in the plan or notes.
- **Checkpoint commands come from you.** A checkpoint raised by a model or a page never carries a command.

## The trail and run evidence

Every event goes into `.reverie/runs/<session>-<timestamp>/trail.jsonl`: actions, pilot operations and outcomes, checks, marks, findings, checkpoints, dialogs. It is the source of truth. Beside it are `run.json` (a short summary: spec id, title, verdict, step counts) and `frames/` (screenshots for replay). The `runs/` and `cache/` directories are git-ignored by default. Review runs with `reverie ui`; see [Runs and the dashboard](/reverie/guides/runs-and-dashboard/).

## The playbook

When the pilot learns a durable rule for a site from a failure (for example "on this login page the submit button is named X; never click the logo"), it records a lesson. Lessons are stored per host in `.reverie/playbook.json`, deduplicated, with at most 30 per host. They are fed back to the pilot on later runs, and the stack sees the latest ones for the current host. Commit the file if it helps other people. `REVERIE_PLAYBOOK` points to a different file.

## UI review

When a step is marked `pass`, `fail` or `blocked`, a multimodal model reviews up to five of the step's screenshots for things a user would notice: overlapping or clipped elements, broken images, raw template code, error banners, wrong data. The pilot also notes anything broken it sees each turn. Both show up on the step and in the trail. If a high-severity UI problem affects the step's feature, the pilot is told to mark the step `fail`. Turn the review off with `REVERIE_UI_REVIEW=0`.

## Next

- [Writing specs](/reverie/guides/writing-specs/)
- [Running specs](/reverie/guides/running-specs/)
- [CLI reference](/reverie/reference/cli/)
