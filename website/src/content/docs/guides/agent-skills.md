---
title: Agent skills
description: Install skills that teach AI coding agents to test web apps with Reverie, using the skills CLI.
---

Reverie ships four agent skills. A skill is a `SKILL.md` file with instructions an AI coding agent loads when a
task matches its description. With them, an agent such as Claude Code, Codex, or Cursor knows how to install
Reverie, write specs, run them, handle checkpoints, and review the results.

## Install

Use the [skills CLI](https://github.com/vercel-labs/skills) from the project where the agent works:

```bash
npx skills add r3c0nc1l3r/reverie        # or: bunx skills add r3c0nc1l3r/reverie
```

The CLI asks which skills and which agents to install for. Useful options:

| Option | Effect |
|---|---|
| `--list` | Show the skills without installing them. |
| `--skill reverie-test-specs` | Install one skill (`'*'` for all). |
| `--agent claude-code codex` | Install for these agents (`'*'` for all). |
| `-g` | Install for your user instead of this project. |
| `-y` | Skip the prompts. |

A project install puts one copy in `.agents/skills/<name>/` and links it into each agent's folder (for example
`.claude/skills/`). `npx skills list` shows what is installed; `npx skills update` updates it.

## The skills

| Skill | When the agent uses it |
|---|---|
| `reverie-browser-testing` | Asked to smoke-test or end-to-end test a web app; to install or configure Reverie (OpenRouter key, decision engine, local Laya); to run a spec and read the verdict. |
| `reverie-test-specs` | Writing a new spec or fixing a flaky one: one provable outcome per step, quoted values, named commit buttons, `[admin]` checkpoints, walkthroughs. Includes a spec template. |
| `reverie-orchestrator` | Driving a session turn by turn: the pilot loop, checkpoints and `exec`/`resolve`, sign-in with `secret`, and direct `observe`/`act`/`check`/`do`. |
| `reverie-run-review` | Explaining a verdict: the dashboard and replay, the trail's events and fields, findings, escalations, stalls, refusals, and tidying run history. |

All examples use the [FieldOps](/reverie/guides/fieldops-demo/) and [WidgetLab](/reverie/guides/widgetlab-demo/)
demo apps, so an agent can practise without touching a real site.

## Safety

Skills run with the agent's permissions, so review them before you install them. The Reverie skills tell the
agent to keep secrets out of specs and command lines, to type passwords only with `reverie secret --env`, and to
test only apps it is allowed to test.

## Contributing

The skills live in [`skills/`](https://github.com/r3c0nc1l3r/reverie/tree/main/skills) in the repository.
`tests/test_skills.py` checks that each one has a valid `name` (the folder name, lowercase with hyphens) and a
`description` that says when to use it. Keep them generic: no app, company, or person names beyond the demo apps.
