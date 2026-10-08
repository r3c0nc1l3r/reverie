---
title: Writing specs
description: The spec file format, which sections Reverie reads, and how to write steps the pilot can run.
---

A spec is one Markdown file per test. Reverie turns its steps into a plan and hands the rest to the pilot as notes. This page covers the format, how it is parsed, and how to write steps that work.

## Format

```md
---
id: DEMO-01
app: the-internet
session: demo
role: anonymous
---
# DEMO-01: Short title

## Goal
## Fixtures
## Steps
## Walkthrough
## Evidence
## Guidance
## Cleanup
```

Only `## Steps` is required. A spec without it is refused with `a spec needs a '## Steps' section`.

### Front matter

Front matter is a block between `---` lines at the very top. Each line is `key: value`. A trailing ` # comment` is stripped.

Reverie reads only one key itself:

| Key | Used for |
| --- | --- |
| `id` | The spec's id, stored as `spec_id` in the run's `run.json` so history can group runs by spec. |

Any other key (`app`, `session`, `role`, `mfa`, `requirement` and so on) is parsed but not acted on. You can keep them as labels for people and your own tooling; the bundled demo uses `app`, `session`, `role`, `mfa` and `requirement` that way. The `session` key does not choose the session. You still pass `--session` on the command line.

### How the id and title are derived

- The plan title is the first `# ` heading in the file. With no heading, it falls back to the front-matter `id`, then to `Test`.
- The run's spec id is the front-matter `id`. If there is none, it is the leading token of the title when that looks like `ABC-12` (letters, a dash, digits). Otherwise it is empty.

### Sections

Section names are matched case-insensitively. Everything before the first `##` heading, and any section Reverie does not know, is ignored.

| Section | What Reverie does with it |
| --- | --- |
| `## Steps` | Required. Becomes the plan. |
| `## Goal` | Sent to the pilot as a note (`Goal: ...`). |
| `## Fixtures` | Sent to the pilot as a note. Put known ids, emails and URLs here. Do not put secrets here. |
| `## Evidence` | Sent to the pilot as a note. Say what counts as proof. |
| `## Guidance` | Sent to the pilot as a note. Say which buttons are meant to be clicked, which to avoid, and any site quirks. |
| `## Walkthrough` | Sent to the pilot as a note. Usually written by `reverie walkthrough` (see below). |
| `## Cleanup` | Not read. It is documentation for people. If cleanup needs a terminal, make it an `[admin]` step instead. |

Each note is the section name plus its non-empty lines joined into one line, and notes are capped at 500 characters when stored. Keep them short. The pilot sees the last 12 notes. Values the pilot types must appear in the steps or notes, so a value stated only in `## Fixtures` is allowed too.

### Steps

Steps are numbered (`1.` or `1)`) or bulleted (`-`, `*`) lines under `## Steps`. A `[ ]` or `[x]` checkbox prefix is allowed and dropped. An indented line below a step is joined to it. Backticks and `**` bold are stripped from normal steps.

### Admin steps

A step that starts with `[admin]` becomes a checkpoint for terminal work. Put the command in backticks and it is attached to the checkpoint:

```md
## Steps

1. Open https://example.com/signup and register user@example.com. Check that the page says to confirm by email.
2. [admin] Read the newest confirmation email for user@example.com from the mail API and report the confirmation link. `curl -s http://127.0.0.1:8025/api/v1/messages`
3. Open the confirmation link from the previous step and check that the page shows 'Account confirmed'.
```

When the pilot reaches step 2, it pauses and raises a checkpoint. The orchestrator runs or answers it, then restarts the pilot. See [Running specs](/reverie/guides/running-specs/). Without a command, the step text itself is the request.

## A complete example

This is `examples/specs/demo-controls.md` from the repository. It runs against a public practice site and needs no sign-in.

```md
---
id: DEMO-01
app: the-internet
session: demo
role: anonymous
mfa: false
requirement: demo
---
# DEMO-01 — Form controls and a loading page

## Goal

Show that the agent can use common form controls and wait for content that loads late, on the public practice site https://the-internet.herokuapp.com.

## Fixtures

None. The site is public and needs no sign-in.

## Steps

1. Open https://the-internet.herokuapp.com/dropdown. Select 'Option 2' in the dropdown list and check that 'Option 2' is the selected value.
2. Open https://the-internet.herokuapp.com/checkboxes. Make sure both checkboxes are checked (checkbox 1 starts unchecked) and check that both are checked.
3. Open https://the-internet.herokuapp.com/dynamic_loading/1. Click Start and check that the page shows 'Hello World!' after the loading bar.

## Evidence

Pass: 'Option 2' selected, both checkboxes checked, and 'Hello World!' shown.

## Guidance

- The Start button is named in step 3; clicking it is intended.

## Cleanup

None.
```

## Loading a spec

There are two ways to load steps, and they behave differently.

| Command | Use it for |
| --- | --- |
| `reverie spec FILE` | A stored spec. Parses the front matter, takes the title from the `#` heading, loads `## Steps` as the plan, and sends the note sections (Goal, Fixtures, Evidence, Guidance, Walkthrough) to the pilot. |
| `reverie plan --file FILE [--section TEXT]` | Any Markdown file with a list of steps, such as a test-plan document that holds many tests. It loads steps only; no notes are sent. |

With `--section`, `plan` finds the first heading that starts with that text (for example `## DEMO-01`), and reads the numbered or bulleted lines under it until the next heading of the same or higher level. The heading text becomes the title. You can also add `--step "text"` (repeatable) and `--title`. Both `spec` and `plan` replace any plan already loaded, and are refused while a pilot is running.

```bash
uv run reverie --session demo spec examples/specs/demo-controls.md
uv run reverie --session demo plan --file test-plan.md --section DEMO-01
uv run reverie --session demo plan --title "Smoke" --step "Open https://example.com" --step "Check that 'Example Domain' shows"
```

If you use `plan --file` and the test needs fixture facts or guidance, send them with `reverie note "..."`.

## Where specs live

`reverie init` creates a `.reverie/` directory in your project (it finds the nearest existing one, like git finds `.git`). It contains:

```text
.reverie/
  README.md        what the directory holds
  .gitignore       keeps runs/ and cache/ out of version control
  runs/            one folder per run
  specs/           stored test specs
    README.md      a short guide to the spec format
```

Keep your specs in `.reverie/specs/` and commit them. The `specs/README.md` that `reverie init` writes says:

> A spec is one Markdown file per test. The pilot runs it with `reverie spec <file> && reverie pilot`. Only `## Steps` is required. `## Goal`, `## Fixtures`, `## Evidence`, `## Guidance`, and `## Walkthrough` are passed to the pilot as notes. A step that starts with `[admin]` raises a checkpoint for terminal work; put its command in backticks.

Specs can live anywhere; `reverie spec` takes any path.

## Recording a walkthrough

After a good run you can freeze the click path into the spec. `reverie walkthrough RUN_ID` prints click-by-click Markdown from a run (find ids with `reverie runs list`). With `--write SPEC` it puts that text into the spec's `## Walkthrough` section: it replaces an existing section, or inserts one before `## Evidence`, or appends it at the end.

```bash
uv run reverie runs list
uv run reverie walkthrough demo-20260101-120000 --write .reverie/specs/demo-controls.md
```

The pilot gets the walkthrough as a note on later runs, so it knows the route that worked. Review the text before you commit it.

## Tips for good steps

The pilot works from your steps and from a fixed set of rules. These tips follow from those rules.

- **Start from a known page.** Give a full URL or a clear starting place. The pilot is told to navigate to the page a step starts from before acting.
- **One outcome per step.** The pilot works on one step at a time and marks it when its outcome is proven. Put the check in the step: "...and check that the page shows 'Hello World!'".
- **State the values to type, in quotes.** Reverie types only values stated in the plan or notes. Write `Enter '300' in the rate field`, not "enter a valid rate". Put emails and ids in `## Fixtures`.
- **Name the buttons that are meant to be clicked.** Committing buttons (Save, Submit, Delete, Confirm, Yes, OK, Send and similar) run only when the step names them. Write "click Save" when you mean it. Add a line under `## Guidance` such as "The Start button is named in step 3; clicking it is intended".
- **Split opening from confirming.** "Open the delete dialog" and "confirm the deletion" should be two steps, so the first cannot commit by accident.
- **Say what proves a creation.** A step that creates something is proven only by something new, such as an id or row that did not exist before. An existing id from `## Fixtures` is not proof.
- **Say what must not be clicked.** Under `## Guidance`, list labels to avoid, such as a logo or a "Forgot password?" link.
- **Mark terminal work as `[admin]`.** Database reads, mail lookups, log reads and fixture resets are not browser work. Never put passwords, codes or tokens in a spec; the orchestrator supplies secrets at run time with `reverie secret`.
- **Say "signed out" or "private window" when you mean it.** The pilot can open an isolated tab with its own cookies for those steps.
- **Keep steps and notes short.** Long text is truncated, and a shorter step is easier for the small local model to carry out.

Next: [Running specs](/reverie/guides/running-specs/).
