---
name: reverie-test-specs
description: Write and improve Reverie browser test specs (Markdown files whose steps the pilot runs). Use when creating a new Reverie spec, turning a manual test or user story into one, fixing a flaky or failing spec, adding [admin] checkpoints for database or email proof, or writing a spec's walkthrough from a passing run.
---

# Writing Reverie test specs

A spec is one Markdown file per test. `reverie spec <file>` turns its `## Steps` into the plan and sends the
other sections to the pilot as notes. Good specs make runs repeatable; vague ones make the pilot guess.

Start from `template.md` next to this file. Real examples: `examples/widgetlab/specs/` and
`examples/fieldops/specs/` in the Reverie repository.

## Format

```md
---
id: WL-04
app: widgetlab
---
# WL-04 — Change settings across tabs

## Goal
## Fixtures
## Steps
## Walkthrough
## Evidence
## Guidance
## Cleanup
```

| Part | What Reverie does with it |
|---|---|
| Front matter | Only `id` is used: it labels the run (`spec_id` in `run.json`). Other keys are labels for people. Without `id`, a leading `ABC-12` in the title is used. |
| `# Title` | The plan's title. |
| `## Steps` | Required. Numbered or bulleted lines become plan steps; indented lines join the step above. |
| `## Goal`, `## Fixtures`, `## Evidence`, `## Guidance`, `## Walkthrough` | Each becomes one note for the pilot (about 500 characters kept per note). |
| `## Cleanup` | Not read by Reverie; for people. Terminal cleanup belongs in an `[admin]` step. |

Section names are case-insensitive. Text before the first `##` is ignored.

## Rules for steps

1. **One provable outcome per step.** The pilot marks each step pass or fail on evidence it checked.
   "Click Save settings and check that the page shows 'Settings saved.'" is a step; "Click Save" alone is not.
2. **Quote every value to type**, in single quotes: `Type 'Robin Vale' into Full name`. The decision engine,
   the escalation model, and the pilot refuse to type values that the steps or notes do not state.
3. **Name controls as the page shows them**: visible label, tab or menu path, option text
   (`On the Notifications tab, tick 'Weekly digest email'`).
4. **Name the committing button.** Clicks on Save, Delete, Submit, Confirm, Send, Pay, Update and similar controls run
   only when the step names them. Put "open the dialog" and "confirm it" in separate steps, and say in
   `## Guidance` which commit buttons the test intends to click.
5. **Say what proves the step**: the exact text to see, or what must be gone, or the URL part.
6. **Sign-in is a precondition, not a step.** The orchestrator signs in before the pilot starts; state it in
   `## Fixtures`. Password fields are hidden from the models.
7. **No secrets anywhere**: no passwords, tokens, one-time codes, or real personal data. Use synthetic fixtures.
8. **3–8 steps per spec.** Split longer flows into several specs.

## Checkpoints: `[admin]` steps

A step that starts with `[admin]` becomes a checkpoint for the orchestrator: terminal work the browser cannot
do, such as a database read, an email lookup, a log read, or a fixture reset. Put the command in backticks and
say exactly what result proves the step:

```md
5. [admin] Count the work orders and read the newest one: `./query.sh "select count(*) from work_orders"`. Expected: 11 work orders, the newest titled 'Leak under the prep sink'.
```

Browser work never goes in an `[admin]` step. Only `[admin]` steps you write (and the orchestrator) can carry a
command; checkpoints raised by a model never do.

## Dialogs, tabs, waits, downloads

- **Native dialogs** (alert, confirm, prompt) are answered automatically: accept by default
  (`REVERIE_DIALOGS=dismiss` changes that). To cancel one confirm, say so in the step ("set the next dialog to be
  dismissed, then click 'Delete Water the ferns'"). To answer a prompt, quote the value
  ("answer the prompt with 'Oil and adjust the bicycle chain'"). See WL-02.
- **Late content**: say what to wait for ("Wait until the page shows 'Report ready'"). See WL-03.
- **Signed-out checks**: ask for a new isolated tab; the pilot can open one with its own cookies.
- **Downloads** land in the session's download folder, never `~/Downloads`; prove them with an `[admin]` step that
  lists `download_dir` from `reverie status`. See WL-03.

## Walkthroughs: make the next run near-certain

After a run passes, write its click-by-click steps into the spec:

```bash
reverie runs list
reverie walkthrough <run-id> --write specs/wl-01-signup-wizard.md
```

Then edit the `## Walkthrough` section like instructions for a new tester: delete stray or repeated actions; keep
each control's label, each typed value, each dialog and its answer, and the proof. The pilot follows the
walkthrough first and uses its own judgment when the page differs.

## When a spec fails or flakes

Fix the cause in this order:

1. **The spec**: split the step, quote the value, name the control and the commit button, add a walkthrough line.
2. **The app's markup** (if you own it): give unnamed controls a `<label>`, `aria-label`, or stable `id`/`name`.
3. **Reverie** itself, only if the pattern recurs across sites (see `reverie-run-review`).

A failed step is information, not something to work around: when the app is wrong, the pilot records a
finding and marks the step `fail`. Keep that verdict.
