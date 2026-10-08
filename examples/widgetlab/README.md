# WidgetLab: a practice app for Reverie's decision engines

WidgetLab is a small, fictional practice app with the widgets that trip up browser agents: a multi-step wizard with
validation, native confirm and prompt dialogs, content that appears after a delay, a file download, tabs, and
type-ahead suggestions. Use it to test the decision engines (Jev and Laya) and the escalation model locally, without a public site.

The app is one Python file using only the standard library. All data lives in memory.

## Run and reset

```bash
cd examples/widgetlab
./run.sh                 # http://127.0.0.1:8766/   (PORT=9000 ./run.sh for another port)
./reset.sh               # restore the starting data on the running server (or restart it)
```

## Pages

| Page | Widgets |
|---|---|
| Sign up (`/signup`) | Three steps: text fields with an inline email error, a plan radio group, a billing select, Back and Next, and Create account. Each new account gets a reference starting at WL-1001. |
| Tasks (`/tasks`) | Delete asks with `confirm()`; Rename asks with `prompt()`. A banner reports the change. |
| Reports (`/reports`) | Build report shows "Building the report…" for three seconds, then the result and a Download CSV link (`garden-report.csv`). |
| Settings (`/settings`) | General and Notifications tabs, a Theme select, two checkboxes, and Save settings. A summary line shows the saved values. |
| Color search (`/search`) | Type two letters and suggestions appear after a short delay; pick one and click Choose. |

## Specs

| Spec | What it proves |
|---|---|
| [WL-01](specs/wl-01-signup-wizard.md) Sign up through the wizard | Text fields, a validation error, radio and select, Back keeps the choice, and the commit |
| [WL-02](specs/wl-02-task-dialogs.md) Task dialogs | A dismissed confirm changes nothing, an accepted one deletes, and a prompt is answered with a stated value |
| [WL-03](specs/wl-03-late-report-download.md) Late report and download | Waiting for late content; the download lands in the session's download folder (an `[admin]` check) |
| [WL-04](specs/wl-04-settings-tabs.md) Settings across tabs | Switching tabs, a select, checkboxes in a hidden panel, and Save |
| [WL-05](specs/wl-05-type-ahead.md) Type-ahead | Typing part of a value, waiting for suggestions, and picking one |

All five pass on fresh data with either engine. No spec needs a sign-in.

```bash
cd examples/widgetlab
./run.sh &
reverie init
reverie --session widgets start --url http://127.0.0.1:8766/                 # Jev by default; --engine laya for local Laya
reverie --session widgets spec specs/wl-01-signup-wizard.md
reverie --session widgets pilot
reverie --session widgets progress
reverie --session widgets stop
```

Reset the data before each spec. `scripts/jev-smoke.sh --e2e` runs WL-05 headless with Jev as a live smoke test.
