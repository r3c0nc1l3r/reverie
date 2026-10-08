---
name: reverie-run-review
description: Review and debug Reverie browser test runs. Use when asked whether a Reverie test passed and why, to inspect a run in the dashboard or replay, to read the run trail (trail.jsonl, run.json), to explain a failed or blocked step, a finding, an escalation, a stall, or a refused action, or to tidy run history.
---

# Reviewing and debugging Reverie runs

Every session writes one run folder in the project's `.reverie/runs/<session>-<stamp>/`:

| File | Holds |
|---|---|
| `trail.jsonl` | Every event, one JSON object per line. The source of truth. |
| `run.json` | Summary: spec id, title, verdict, steps done. |
| `frames/` | Screenshots for replay. |
| `downloads/` | Browser downloads (unless `--download-dir` or `REVERIE_DOWNLOAD_DIR` chose another folder). |

Reverie uses the nearest `.reverie/` in the current directory or a parent, like git with `.git`.

## Look at it

```bash
reverie ui                         # dashboard on http://127.0.0.1:7788/: suites, tests, runs, frames, timeline
reverie ui --root path/to/runs     # runs from another folder
reverie runs list                  # run ids
reverie --session widgets progress # live: steps, pilot state, open checkpoints, last events
reverie --session widgets events --since 40
reverie --session widgets recap    # a short spoken summary of the session so far
```

In the dashboard, ↑/↓ or ←/→ step through the frames (recorded narration plays), `L` returns to the live
view, and `N` toggles narration. Each run has a replay: one slide per unique screen with step cards,
verdicts, and the pilot's spoken updates. `reverie --session NAME watch` opens a live, read-only watch page.

## Read the trail

```bash
python3 - <<'PY'
import json, glob
run = sorted(glob.glob(".reverie/runs/*/trail.jsonl"))[-1]
for line in open(run):
    e = json.loads(line)
    if e["event"] in {"mark", "finding", "checkpoint", "ui_review", "pilot_end", "error"}:
        print(e["event"], {k: v for k, v in e.items() if k not in {"t", "event"}})
PY
```

Useful events:

| Event | Tells you |
|---|---|
| `mark` | A step's status and the pilot's evidence note. |
| `finding` | A defect the pilot recorded: severity, what, expected, actual, workaround. |
| `check` | An assertion and whether it passed. |
| `act` | One action: `by` is `decision`, `escalation`, `pilot`, or `orchestrator`; decision-layer acts also carry `decision_engine` (`jev` or `laya`). |
| `suggest` | A proposal: `layer`, `decision_engine`, `decision_confidence`, `escalation` (why layer 2 took over), and for Jev `decision_ms` and `decision_cost`. |
| `auto` | Why a `do` intent paused (`reason`) and how many actions each layer ran (`layers`). |
| `checkpoint`, `resolve` | Work handed to the orchestrator, and its outcome note. |
| `ui_review`, `ui_flag` | Visual problems a model saw in the step's screenshots. |
| `stalled`, `pilot_end` | Why the pilot stopped (`plan complete`, `admin`, `budget`, an error, a stall). |

Runs recorded by older versions use `laya`, `jev`, or `mercury` in `by`/`layer`; read them as decision engine
(Laya or Jev) and escalation model.

## Explain the verdict

- **pass** needs a passing check in that step and no medium or high finding.
- **fail** means a check showed the wrong outcome or the pilot recorded a medium/high finding. A workaround does
  not turn a failure into a pass. The run continues after a failed step.
- **blocked** means the environment prevented the test (missing data, an error page that cannot be passed).
- A high-severity `ui_review` problem in the tested feature is a real finding even when the data checks passed.

## Common causes

| Symptom | Likely cause and fix |
|---|---|
| `refused: ... commits a change the intent did not ask for` (exit 2) | The intent did not name the Save/Delete/Submit button. Name it in the step. |
| `would type '...', which the goal does not state` | The value is not quoted in the step or notes. Quote it. |
| Escalations with `confidence 0.xx < 0.60` | The decision engine is unsure: the control has a vague label, or two controls look alike. Name it more precisely, add a walkthrough line, or improve the app's labels. `REVERIE_DECISION_MIN_CONFIDENCE` sets the threshold. |
| `loop: the same action ran three times` | The page did not react; it may be loading or the target is wrong. Add a wait condition ("wait until ... shows") or a hint. |
| A stall checkpoint | No pilot activity for `REVERIE_STALL_SECONDS` (default 240): a hung model call or page. Check the model endpoint, then resolve and restart the pilot. |
| A "stuck" checkpoint | 12 pilot operations on one step without progress (`REVERIE_PILOT_STUCK`). The step is ambiguous or the app misbehaves; split or clarify it. |
| `Jev, the default decision engine, needs an OpenRouter key` | Set `OPENROUTER_API_KEY`, or use local Laya (`REVERIE_DECISION_ENGINE=laya`). |
| Hover-only menus the stack cannot open | Use `hover`, or a step that opens the page by its URL. |
| Email bodies inside iframes | Open the message's own HTML view, and prove links with `check --link TEXT --href part` instead of printing them. |

Fix the spec first, then the app's markup, and only then Reverie itself (its guards and prompts live in
`reverie/control/session.py`, `pilot.py`, and `steer.py`).

## Tidy up

```bash
reverie runs prune                 # hide broken or failed finished runs (kept on disk)
reverie runs hide <run-id> ...     # hide specific runs
reverie walkthrough <run-id> --write specs/<spec>.md   # after a pass, save the clicks into the spec
```

Delete a run only by its exact folder path, one at a time, and only runs that covered tool debugging.
