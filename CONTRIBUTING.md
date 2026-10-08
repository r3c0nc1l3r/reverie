# Contributing

## Workflow

1. Create a branch from `main`. Name it `<type>/<short-topic>`, for example
   `feat/run-review`, `fix/pilot-typing-loop`, or `docs/design-md`.
2. Commit in small steps. Conventional Commit messages are preferred on the
   branch, but only the PR title reaches `main`.
3. Push the branch and open a pull request with `gh pr create --fill`. Fill in
   the template: why, what changed, verification, and risk.
4. CI must pass: `Python (lint + tests)`, `UI (typecheck + Storybook build)`,
   and `PR title`.
5. Squash merge. The PR title becomes the one commit on `main`, and GitHub
   deletes the branch.

Do not push to `main` directly. Enable the local guard once per clone:

```sh
git config core.hooksPath scripts/hooks
```

## PR titles

The title must be a [Conventional Commit](https://www.conventionalcommits.org/):
`type(scope): summary`. release-please reads these titles to pick the next
version and write `CHANGELOG.md`.

| Type | Use it for | Version bump (before 1.0) | Changelog |
|---|---|---|---|
| `feat` | New behavior | minor | Features |
| `fix` | Bug fix | patch | Bug Fixes |
| `perf` | Faster, same behavior | patch | Performance |
| `refactor` | Code change, same behavior | patch | Refactoring |
| `docs` | Docs only | patch | Documentation |
| `test`, `build`, `ci`, `chore` | Tooling | none alone | hidden |
| `feat!` or `BREAKING CHANGE:` | Incompatible change | minor before 1.0, major after | Breaking |

Common scopes: `pilot`, `session`, `cli`, `dashboard`, `ui`, `examples`, `docs`.

## Versions and releases

- The version lives in `pyproject.toml`, `reverie/__init__.py`, and
  `.release-please-manifest.json`. Do not change it by hand.
- Each push to `main` updates one open release PR, titled
  `chore(main): release X.Y.Z`. Merge it when you want to cut a release.
  release-please then tags `vX.Y.Z` and creates the GitHub release.
- `reverie --version` prints the installed version.

## Checks to run locally

```sh
uv run ruff check reverie tests
uv run pytest -q
(cd ui && npx tsc -b --noEmit && npm run build-storybook -- --quiet)
```
