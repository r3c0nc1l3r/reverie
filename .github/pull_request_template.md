<!-- Title: a Conventional Commit, for example `feat(pilot): retry a failed fill once`.
     The squash merge uses the title as the commit on main, and release-please builds CHANGELOG.md from it. -->

## Why

<!-- The problem or goal. Link the issue: Closes #123 -->

## What changed

-

## Verification

<!-- The commands you ran and what you saw. Say what you did not test. -->

- [ ] `uv run ruff check reverie tests`
- [ ] `uv run pytest -q`
- [ ] UI changes: `npm run build-storybook` in `ui/`, screenshots below
- [ ] Pilot or session changes: a real `reverie` run (spec and run id below)

## Risk

<!-- What could break, who notices, how to roll back. A breaking change needs `!` in the title
     (`feat!: ...`) and a `BREAKING CHANGE:` note here. -->
