---
title: WidgetLab demo
description: A local practice app with a wizard, browser dialogs, late content, a download, tabs, and type-ahead, plus five specs for Laya, Jev, and Mercury.
---

WidgetLab is a small, fictional practice app in `examples/widgetlab/`. It has the widgets that trip up browser agents: a multi-step wizard with validation, native confirm and prompt dialogs, content that appears after a delay, a file download, tabs, and type-ahead suggestions. Use it to test the [decision engines](/reverie/reference/models/#decision-engines) locally, without a public site.

The app is one Python file that uses only the standard library. All data lives in memory. It needs no sign-in.

## Start the app

Run these from `examples/widgetlab`. They need `uv` or Python 3.11 or later.

```bash
cd examples/widgetlab
./run.sh                 # http://127.0.0.1:8766/
./reset.sh               # restore the starting data on the running server
```

| Script | What it does |
|---|---|
| `run.sh` | Starts the app on `http://127.0.0.1:8766/`. Set `PORT=9000 ./run.sh` for another port. |
| `reset.sh` | Restores the starting data on the running server. Restarting the app does the same. |

To run a spec you also need Reverie installed ([Installation](/reverie/start/installation/)) and the pilot's model key (`OPENROUTER_API_KEY`) in the environment or in a `.env` file. See [Configuration](/reverie/reference/configuration/).

## Pages

| Page | Widgets |
|---|---|
| Sign up (`/signup`) | Three steps: text fields with an inline email error, a plan radio group, a billing select, Back and Next, and Create account. Each new account gets a reference that starts at WL-1001. |
| Tasks (`/tasks`) | Delete asks with `confirm()`. Rename asks with `prompt()`. A banner reports the change. |
| Reports (`/reports`) | Build report shows "Building the report..." for three seconds, then the result and a Download CSV link (`garden-report.csv`). |
| Settings (`/settings`) | General and Notifications tabs, a Theme select, two checkboxes, and Save settings. A summary line shows the saved values. |
| Color search (`/search`) | Type two letters and suggestions appear after a short delay. Pick one and click Choose. |

## The five specs

The specs are in `examples/widgetlab/specs/`. Each is one Markdown file in the [spec format](/reverie/guides/writing-specs/).

| Spec | What it tests |
|---|---|
| WL-01 Sign up through the wizard | Text fields, a validation error, a radio and a select, Back keeps the choice, and the final commit. |
| WL-02 Task dialogs | A dismissed confirm changes nothing, an accepted one deletes, and a prompt is answered with a stated value. |
| WL-03 Late report and download | Waiting for late content. The download lands in the session's download folder, and an `[admin]` step checks it. |
| WL-04 Settings across tabs | Switching tabs, a select, checkboxes in a hidden panel, and Save. |
| WL-05 Type-ahead | Typing part of a value, waiting for suggestions, and picking one. |

All five pass on fresh data with either engine. Reset the data before each spec.

## Run a spec

This runs WL-02 with Jev as the fast layer. Leave out `--engine jev` to use Laya.

```bash
cd examples/widgetlab
./reset.sh
./run.sh &
reverie init
reverie --session widgets start --url http://127.0.0.1:8766/ --engine jev
reverie --session widgets spec specs/wl-02-task-dialogs.md
reverie --session widgets pilot
reverie --session widgets progress              # poll until the pilot stops
reverie --session widgets stop
```

(`laya-agent` is an alias for `reverie`.) Jev needs `OPENROUTER_API_KEY`.

## What each spec shows

- **Dialogs (WL-02).** The pilot sets the dialog answer before a click. To dismiss the first confirm, it sets `dismiss`, clicks Delete, then sets `accept` again. For the rename, its `dialogs` operation carries the text for the prompt, and that text must be a value the spec states.
- **Select options (WL-01, WL-04).** Each option of a select list is its own element, named like `Billing → Yearly`. Choosing text for a select makes the pilot pick the matching option.
- **Waiting (WL-03, WL-05).** The pilot waits while the report builds or the suggestions load. A bare wait counts as the `wait` action.
- **Download (WL-03).** The file goes to the folder shown as `download_dir` in `reverie status`. See [Runs and dashboard](/reverie/guides/runs-and-dashboard/#downloads).

## Live Jev smoke test

`scripts/jev-smoke.sh` makes four Jev decisions on a synthetic page. It costs about $0.001. With `--e2e` it also runs WL-05 headless with `--engine jev`, which adds pilot model calls.

```bash
scripts/jev-smoke.sh
scripts/jev-smoke.sh --e2e
```

The decision test is skipped without `OPENROUTER_API_KEY`.

## Related

- [Examples](/reverie/guides/examples/)
- [Decision engines](/reverie/reference/models/#decision-engines)
- [Running specs](/reverie/guides/running-specs/)
