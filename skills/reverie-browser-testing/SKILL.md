---
name: reverie-browser-testing
description: Run spec-driven browser tests of a web app with Reverie, from install to verdict. Use when asked to smoke-test, QA, or end-to-end test a web app in a real browser with Reverie; to install or configure Reverie (OpenRouter key, decision engine, local Laya); to run a Markdown test spec; or to read a run's pass/fail result.
---

# Browser testing with Reverie

Reverie runs browser tests written as Markdown specs. You (the agent) are the **orchestrator**: you start a
browser session, load a spec, and let the **pilot** (a multimodal model) run it step by step. Under the pilot,
a **decision engine** makes each click and keystroke (Jev, hosted, by default; or Laya, local), and an
**escalation model** (the text model) steps in when the decision engine is unsure.

Related skills: `reverie-test-specs` (write a spec), `reverie-orchestrator` (drive a session turn by turn,
handle checkpoints), `reverie-run-review` (review and debug runs).

## 1. Install

Reverie is a Python package (3.12+), not on PyPI. Install the `reverie` command from GitHub:

```bash
uv tool install git+https://github.com/r3c0nc1l3r/reverie      # or: pip install git+https://github.com/r3c0nc1l3r/reverie
reverie --version
```

It needs a Chromium-family browser (`chromium`, `google-chrome`, `brave`, ...). Set `REVERIE_BROWSER` to a
path if it is not on `PATH`. `laya-agent` is an older alias of `reverie`.

## 2. Configure

One OpenRouter key covers the default setup: the Jev decision engine, the pilot, and the text model.

```bash
mkdir -p ~/.config/reverie
printf 'OPENROUTER_API_KEY=%s\nTEXT_MODEL_PROVIDER=openrouter\n' "$KEY" >> ~/.config/reverie/.env
chmod 600 ~/.config/reverie/.env
```

Reverie reads the environment first, then `.env` files (first value wins): `$REVERIE_ENV_FILE`, the project
root's `.env`, `./.env`, then `~/.config/reverie/.env`. Keep keys in the user file, never in a repository.

| Choice | Setting |
|---|---|
| Decision engine | `jev` (default, needs `OPENROUTER_API_KEY`) or `laya` (local): `REVERIE_DECISION_ENGINE=laya` or `reverie start --engine laya` |
| Local Laya server | `LAYA_BASE_URL=http://127.0.0.1:8080` for laya.cpp, or `LAYA_BACKEND=mlx` on Apple Silicon |
| Escalation model | On by default; `REVERIE_ESCALATION=off` returns doubtful steps to the pilot instead |
| Pilot model | `REVERIE_PILOT_MODEL` (default `z-ai/glm-5.3-flash`) |

If a Jev session has no key, `reverie start` fails and says how to fix it. It never falls back silently.
Older `LAYA_AGENT_*` setting names still work; the `REVERIE_*` name wins.

## 3. Run a spec (WidgetLab example)

Run commands from the project you test: run history goes to its `.reverie/runs/`.

```bash
git clone https://github.com/r3c0nc1l3r/reverie && cd reverie/examples/widgetlab
./run.sh &                                   # practice app on http://127.0.0.1:8766/
reverie init                                 # creates .reverie/ (runs, specs) here
reverie --session widgets start --url http://127.0.0.1:8766/ --headless
reverie --session widgets spec specs/wl-01-signup-wizard.md
reverie --session widgets pilot --max 150    # runs in the background
reverie --session widgets progress           # poll until "pilot: idle"
reverie --session widgets stop
```

- Use `--headless` unless a person wants to watch. One session = one browser = one run.
- `pilot` stops at its operation budget (`--max`, default 30); run `pilot` again to continue.
- When the pilot pauses with `last pause: admin`, a checkpoint needs you: see `reverie-orchestrator`.

## 4. Read the result

`reverie --session widgets progress` shows each step's status, the pilot's evidence, findings, and the last
pause reason:

| Last pause | Meaning |
|---|---|
| `plan complete` | Every step has a verdict. The test line shows `[pass]` or `[fail]`. |
| `admin` | A checkpoint waits for the orchestrator (terminal work, a sign-in, a question). |
| `budget` | The pilot used its `--max` operations; start it again. |
| `pilot error: ...` | The pilot model gave no valid operation; read the message and start it again. |

Step statuses: `pass`, `fail` (a check showed the wrong outcome, or a medium/high finding), `blocked` (the
environment prevented the test), `skipped`. A failed step does not stop the run.

Review the run visually with `reverie ui` (dashboard on http://127.0.0.1:7788/). See `reverie-run-review`.

## 5. The FieldOps demo (sign-in and database proof)

FieldOps (`examples/fieldops`, port 8765) has sign-in and `[admin]` database checks:

```bash
cd examples/fieldops && ./reset.sh && ./run.sh &
reverie --session dispatcher start --url http://127.0.0.1:8765/login --headless
export FIELDOPS_PASSWORD='fieldops-demo'                 # synthetic demo value
reverie --session dispatcher observe                     # find the Username and Sign in refs
reverie --session dispatcher fill e2 --text dana.dispatch   # e2 = Username on a fresh login page
reverie --session dispatcher secret --env FIELDOPS_PASSWORD
reverie --session dispatcher click e4                      # e4 = Sign in
reverie --session dispatcher spec specs/fs-01-create-and-dispatch.md
reverie --session dispatcher pilot --max 150
```

Expected on fresh data: FS-01, FS-02, FS-03 and FS-05 pass; FS-04 fails at step 3 on the app's deliberate
invoice bug, with a finding. Reset the data before each spec.

## Exit codes

`0` ok, `1` a `check` failed, `2` refused (a guard stopped an action), `3` error, `4` no session.

## Safety

- Password fields are hidden from every model. Type passwords only with `reverie secret --env VAR`.
- The session daemon never runs shell commands; terminal work comes to you as a checkpoint.
- Tokens and codes are masked in trails and model context. Screenshots are not masked: keep secrets off screen.
- Test only apps you are allowed to test. Never put real credentials in a spec.
