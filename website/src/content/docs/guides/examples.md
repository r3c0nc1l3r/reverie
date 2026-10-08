---
title: Examples
description: The bundled examples, the demo-controls spec and the FieldOps and WidgetLab demo apps, plus short command recipes.
---

Reverie ships three examples:

| Example | What it is |
|---|---|
| `examples/specs/demo-controls.md` | One spec against a public practice site. No sign-in, no fixtures. Described below. |
| `examples/fieldops/` | A local field-service app with five specs, sign-in, `[admin]` checkpoints, and one deliberate bug. See [FieldOps demo](/reverie/guides/fieldops-demo/). |
| `examples/widgetlab/` | A local practice app with a wizard, browser dialogs, late content, a download, tabs and type-ahead, and five specs. See [WidgetLab demo](/reverie/guides/widgetlab-demo/). |

## The demo spec

Reverie ships a demo spec at `examples/specs/demo-controls.md`. It runs against the public practice site [the-internet.herokuapp.com](https://the-internet.herokuapp.com). It needs no sign-in and no fixtures.

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

## Steps

1. Open https://the-internet.herokuapp.com/dropdown. Select 'Option 2' in the dropdown list and check that 'Option 2' is the selected value.
2. Open https://the-internet.herokuapp.com/checkboxes. Make sure both checkboxes are checked (checkbox 1 starts unchecked) and check that both are checked.
3. Open https://the-internet.herokuapp.com/dynamic_loading/1. Click Start and check that the page shows 'Hello World!' after the loading bar.

## Evidence

Pass: 'Option 2' selected, both checkboxes checked, and 'Hello World!' shown.

## Guidance

- The Start button is named in step 3; clicking it is intended.
```

The full file also has Fixtures and Cleanup sections, both set to "None". The Guidance line matters: Start is a commit-style button, and Reverie only clicks those when the intent names them. See [Troubleshooting](/reverie/help/troubleshooting/#a-click-was-refused-exit-code-2).

### Run it

```bash
uv run reverie --session demo start --url https://the-internet.herokuapp.com/
uv run reverie --session demo spec examples/specs/demo-controls.md
uv run reverie --session demo pilot
uv run reverie --session demo progress
uv run reverie ui
uv run reverie --session demo stop
```

The [first run](/reverie/start/first-run/) page explains each command and its output. To write your own spec, see [Writing specs](/reverie/guides/writing-specs/).

## Recipe: one intent with `do`

`do` states one goal in plain words. The stack carries it out and pauses when it needs you.

```bash
uv run reverie --session demo start --url https://the-internet.herokuapp.com/dropdown
uv run reverie --session demo do "Select 'Option 2' in the dropdown list"
uv run reverie --session demo check --text "Option 2"
```

Quote any value you want typed. Reverie types only values that the intent, the plan, or the notes state. Useful options:

| Option | Does |
|---|---|
| `--hint TEXT` | Steers the model, for example which field or button to use. Repeatable. |
| `--max N` | Sets how many steps to try (default 6). |
| `--until-text TEXT` | Stops once the page shows this text. |
| `--until-url TEXT` | Stops once the URL contains this text. |

The command prints why it stopped (`paused: ...`) and how many actions each layer ran.

## Recipe: step by step with `suggest` and `accept`

`suggest` asks the model for one step. Nothing runs until you accept it.

```bash
uv run reverie --session demo goto https://the-internet.herokuapp.com/checkboxes
uv run reverie --session demo goal "Check checkbox 1"
uv run reverie --session demo suggest
uv run reverie --session demo accept
```

The proposal shows the element, the confidence, and which layer chose it. If it is wrong, reject it and add a hint:

```bash
uv run reverie --session demo reject --hint "use the first checkbox"
uv run reverie --session demo suggest
```

If the page changes after a suggestion, `accept` refuses to run it and asks you to suggest again.

## Recipe: direct control with `observe`, `act`, and `check`

You pick the element yourself. No model decides anything.

```bash
uv run reverie --session demo goto https://the-internet.herokuapp.com/dropdown
uv run reverie --session demo observe --grep dropdown
uv run reverie --session demo act e5 --option "Option 2"
uv run reverie --session demo check --text "Option 2"
```

`observe` lists the elements on the page with ids such as `e5`. Use an id from your own output, since ids differ from page to page. `act` clicks, types, or selects. Use `--text` to type into a field and `--option` to choose from a select. `check` asserts visible text or a URL and exits with code 1 when the check fails.

You can also match by label instead of id:

```bash
uv run reverie --session demo act --label "Start"
```

The label must match exactly one element.

## Related

- [CLI reference](/reverie/reference/cli/)
- [Running specs](/reverie/guides/running-specs/)
