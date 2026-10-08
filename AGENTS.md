# Agent instructions — reverie

This file tells coding agents (Claude Code, Codex, Cursor, and others) how to work in this repository.
Read it before you change anything. `CLAUDE.md` points here.

## What reverie is

Reverie runs browser tests from Markdown specs. AI agents drive it; people read the results.

| Layer | Code | Does |
|---|---|---|
| Decision engine (layer 1) | `reverie/model.py` (Jev, hosted, default), `reverie/laya.py` + `decision_backend.py` (Laya, local) | Picks each click and keystroke from the actions observed on the page. |
| Escalation model (layer 2) | `reverie/control/steer.py` | The text model (Mercury) overrules the decision engine when it is unsure. |
| Browser | `reverie/browser.py`, `snapshot.js` | One CDP session through Browser Harness. Observes elements and executes observed actions. |
| Pilot (OpenAI-compatible model) | `reverie/control/pilot.py`, `reverie/model.py` | Runs a spec step by step: intents, checks, marks, findings, lessons, narration. |
| Session daemon | `reverie/control/server.py`, `session.py`, `downloads.py` | One headed Chromium and one `Session` per `--session` name, driven over loopback with a token. |
| CLI | `reverie/control/cli.py` | `reverie` (older alias `laya-agent`). Every command talks to a session daemon. |
| Settings | `reverie/settings.py` | `REVERIE_*` settings and their old `LAYA_AGENT_*` aliases (the new name wins). |
| Dashboard | `reverie/control/dashboard.py` + `.html` | Run history, live runs, replay, and watch pages on 127.0.0.1:7788. |
| Project state | `reverie/control/project.py` | Finds `.reverie/` like git finds `.git`, lists the `.env` files, writes run summaries, and imports old runs. |
| Narration | `reverie/control/narrator.py`, `speech.py`, `kitten.py`, `kokoro.py`, `fish_audio.py` | Spoken progress on a background thread. |

The orchestrator is an AI agent (or a person) that starts sessions, loads specs, runs the pilot,
resolves checkpoints, and reviews verdicts. Stuck-pilot recovery is agent work: it is never exposed
as a user-facing UI.

## Repository map

| Path | Holds |
|---|---|
| `reverie/` | The Python package. `control/` is the orchestrator layer; the top level is the agent core. |
| `tests/test_control.py` | pytest suite. Uses mocks; needs no browser, model, or network. |
| `tests/test_jev.py` | Jev decision engine contracts, with the OpenRouter call mocked. |
| `tests/test_jev_live.py`, `scripts/jev-smoke.sh` | Opt-in live Jev check (`REVERIE_LIVE_JEV=1`); skipped without a key. |
| `tests/test_downloads_integration.py` | Downloads a file with a real Chromium. Skips when no Chromium-family browser is installed. |
| `ui/` | Vite + React 19 + Storybook 10 + Tailwind v4 + shadcn/ui design concepts for the dashboard. |
| `DESIGN.md` | The visual design system. Read it before any UI change. |
| `examples/specs/` | `demo-controls.md` (DEMO-01) against the-internet.herokuapp.com. |
| `examples/fieldops/` | FieldOps demo app (`run.sh`, port 8765) with specs FS-01..FS-05 and fixtures. |
| `skills/` | Installable agent skills (`skills/<name>/SKILL.md`, for the skills CLI). `tests/test_skills.py` checks their front matter. Keep them generic: demo apps only. |
| `examples/widgetlab/` | WidgetLab practice app (`run.sh`, port 8766): wizard, dialogs, late content, download, tabs, type-ahead; specs WL-01..WL-05. |
| `scripts/agent-services.sh` | Starts laya.cpp and local TTS (`start`, `stop`, `status`). |
| `docker/`, `scripts/reverie-docker.sh` | The GPU container image, its compose files, and the launcher. See `docs/docker.md`. |
| `scripts/hooks/pre-push` | Blocks direct pushes to `main`. |
| `docs/` | `docker.md`, and in `images/` the README banner, logo, and screenshots. |
| `.github/` | CI, PR title check, release-please, Dependabot, PR and issue templates. |
| `artifacts/`, `.reverie/runs/`, `.reverie/cache/`, `.reverie/downloads/` | Run output. Git-ignored. Never commit them. |

## Setup and checks

```sh
uv sync                                  # Python 3.12+, dev tools included
cp .env.example .env                     # model keys, LAYA_BASE_URL, behavior flags (keys can go in ~/.config/reverie/.env)
git config core.hooksPath scripts/hooks  # once per clone

uv run ruff check reverie tests          # lint (E501 is ignored on purpose)
uv run pytest -q                         # all tests must pass
(cd ui && npm ci && npx tsc -b --noEmit && npm run build-storybook -- --quiet)
```

Run all three before you open a PR. CI runs the same commands.

## Running reverie

Run commands from the project under test. Reverie writes runs to the nearest `.reverie/runs/`. Settings come
from the environment, then `$REVERIE_ENV_FILE`, the project root's `.env`, `./.env`, and `~/.config/reverie/.env`
(first wins). Browser downloads go to `--download-dir`, `$REVERIE_DOWNLOAD_DIR`, or `downloads/` in the run folder.

```sh
uv run reverie --session demo start --url https://the-internet.herokuapp.com/
uv run reverie --session demo spec examples/specs/demo-controls.md
uv run reverie --session demo pilot        # background run
uv run reverie --session demo progress     # plan steps, pilot state, open checkpoints
uv run reverie --session demo checkpoints  # then: resolve <id> done --note "..." and pilot again
uv run reverie ui                          # dashboard
uv run reverie --session demo stop
```

- Exit codes: 0 ok, 1 check failed, 2 refused, 3 error, 4 no session.
- Daemon state lives in `$XDG_RUNTIME_DIR/laya-agent/` (or `~/.cache/laya-agent/`).
- One session name per test account. Do not run two sessions against the same account.
- A live run needs `OPENROUTER_API_KEY` for Jev, the default decision engine, and for the pilot's endpoint
  (see "Decision engines" and "Model endpoints" in `README.md`). With `REVERIE_DECISION_ENGINE=laya` it needs
  laya.cpp (`LAYA_BASE_URL`) instead of the Jev key. Unit tests need neither.
- Stop your sessions when you finish. If a Chromium profile is locked (exit 21), find the orphan
  process by its profile path and stop that process only. Do not kill processes by name.

## Specs

A spec is one Markdown file with front matter (`id`, `app`, `session`, `role`) and the sections
Goal, Fixtures, Steps, Walkthrough, Evidence, Guidance, and Cleanup. Steps become the plan. A step
that starts with `[admin]` becomes a checkpoint for the orchestrator. After a passing run,
`reverie walkthrough <run> --write <spec>` records the click path. See `examples/` for models.

## Code rules

- **Safety invariants.** Keep them intact:
  - Every browser mutation goes through the observed-action executor.
  - Never accept CSS selectors or executable code from a caller, model, or spec.
  - Commit buttons (Save, Delete, Confirm, and similar) need an explicit intent.
  - The stack types only values that are stated.
  - Password fields go only through `secret`. Secrets never enter argv, narration, the overlay, the trail, or model context.
  - Tokens and codes stay masked in trails.
- **Tests.** A behavior change needs a pytest test in `tests/test_control.py` that fails without it.
  Mock the browser and models, as the existing tests do.
- **Style.** Match the surrounding code: short functions, dense but readable, few comments, module
  docstrings on every file. Ruff with line length 120 (long prompt strings may exceed it).
- **Trail format.** `trail.jsonl` is the source of truth, and the dashboard, replay, and `walkthrough`
  read it. Keep old event shapes readable when you add fields.
- **Environment variables.** Add new settings to `.env.example` with a comment. Match the prefix of related
  Reverie's own settings use the `REVERIE_` prefix and are read with `settings.setting()`. Never add a new
  `LAYA_AGENT_` name; those exist only as aliases in `reverie/settings.py`. Name layers by role (decision
  engine, escalation model, pilot), not by vendor.
- **UI.**
  - Follow `DESIGN.md`.
  - Use react-icons Lucide icons (`react-icons/lu`) and never emojis.
  - Use theme tokens and never raw colors.
  - Tailwind v4 needs literal class names, so use static class maps (see `ui/src/components/kit.tsx`) and not string-built classes.
  - Add or update a story for every UI change.
- **Docs.** Write in Simplified Technical English: short sentences, active voice, one idea per
  sentence. Update `README.md` when a command or behavior users see changes.

## Git and pull requests

Full rules: `CONTRIBUTING.md`. Summary:

1. Branch from `main` as `<type>/<topic>` (`feat/`, `fix/`, `docs/`, `chore/`, ...). Never commit
   or push to `main` directly.
2. The PR title must be a Conventional Commit: `type(scope): summary`. Scopes: `pilot`, `session`,
   `cli`, `dashboard`, `ui`, `examples`, `docs`. Use `!` for breaking changes.
3. Fill in the PR template. Put the commands you ran and their results under "Verification", and
   say what you did not test.
4. CI must be green: `Python (lint + tests)`, `UI (typecheck + Storybook build)`, `conventional`.
5. Squash merge only. A person reviews and merges; agents open PRs but do not merge their own
   PRs unless the user asks.
6. Commit identity for this repo: `r3c0nc1l3r <r3c0nc1l3r@proton.me>` (local git config).

## Versions and releases

- release-please owns the version (`pyproject.toml`, `reverie/__init__.py`,
  `.release-please-manifest.json`) and `CHANGELOG.md`. Do not edit them by hand.
- Each merge to `main` updates the open `chore(main): release X.Y.Z` PR. Merging it tags
  `vX.Y.Z` and creates the GitHub release.
- Before 1.0: `feat` bumps the minor version, and `fix`, `perf`, `refactor`, and `docs` bump the patch.

## Secrets and data

- `.env` is git-ignored. Never print, log, or commit `OPENROUTER_API_KEY`, `OPENCODE_GO_API_KEY`,
  `FISH_AUDIO_API_TOKEN`, or other keys.
- Synthetic test credentials (such as the FieldOps seeded users) are test data and may appear in
  specs and fixtures. Real credentials never may.
- Screenshots and frames can show app data. Commit images only from demo or synthetic apps.
