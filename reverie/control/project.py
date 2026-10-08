"""Project state: Reverie keeps run history and caches in `.reverie/` under the project it runs in.

The project root is the nearest directory, from the working directory up, that holds `.reverie/` (the way git
finds `.git`); with none, it is the working directory. Layout:

  .reverie/README.md       what this directory holds
  .reverie/.gitignore      keeps runs/, cache/, and downloads/ out of version control
  .reverie/specs/          stored test specs (created by `reverie init`)
  .reverie/runs/           one folder per session run: trail.jsonl, run.json, frames/
  .reverie/cache/          disposable caches (speech audio)
  .reverie/playbook.json   lessons the pilot keeps per host (unless REVERIE_PLAYBOOK is set)

Settings and API keys come from the environment, then from the .env files in `env_files()`.
"""

import json
import os
import re
import shutil
from pathlib import Path

from ..settings import setting

NAME = ".reverie"
LEGACY = Path("artifacts") / "agent-sessions"

GITIGNORE = "runs/\ncache/\ndownloads/\n"

README = """# .reverie

Reverie keeps its project state here. AI agents drive the tests; this directory is their evidence.

- `runs/`: one folder per session run (`<session>-<stamp>/`) with `trail.jsonl` (every event, the source of
  truth), `run.json` (a short summary for fast history listing), and `frames/` (screens for replay).
- `specs/`: stored test specs. Load one with `reverie spec .reverie/specs/<file>.md`.
- `cache/`: disposable caches, such as synthesized narration audio.
- `downloads/`: browser downloads when the Docker launcher runs Reverie.
- `playbook.json`: lessons the pilot learned per host. Commit it if the lessons help other agents.

`runs/`, `cache/`, and `downloads/` are ignored by git (see `.gitignore`). Review runs with `reverie ui`.
"""

SPECS_README = """# Specs

A spec is one Markdown file per test. The pilot runs it with `reverie spec <file> && reverie pilot`.

```markdown
---
id: DEMO-01
app: https://example.com
---
# DEMO-01: Example page shows its heading

## Goal
What the test proves, in one or two sentences.

## Steps
1. Open https://example.com.
2. Check that the heading "Example Domain" shows.

## Evidence
What the run must record as proof.
```

Only `## Steps` is required. `## Goal`, `## Fixtures`, `## Evidence`, `## Guidance`, and `## Walkthrough` are
passed to the pilot as notes. A step that starts with `[admin]` raises a checkpoint for terminal work; put its
command in backticks.
"""


def project_root(start=None):
    """The nearest directory from `start` (default: cwd) upward that holds `.reverie/`; else `start`."""
    here = Path(start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / NAME).is_dir():
            return folder
    return here


def reverie_dir(start=None):
    """`.reverie/` under the project root, created on demand with its README and .gitignore."""
    path = project_root(start) / NAME
    path.mkdir(parents=True, exist_ok=True)
    for name, text in ((".gitignore", GITIGNORE), ("README.md", README)):
        if not (path / name).exists():
            (path / name).write_text(text)
    ignore = path / ".gitignore"
    try:
        lines = ignore.read_text().splitlines()
        missing = [line for line in GITIGNORE.splitlines() if line not in lines]
        if missing:  # Projects created before an entry existed get it too.
            ignore.write_text("\n".join(lines + missing) + "\n")
    except OSError:
        pass
    return path


def runs_dir(start=None):
    return reverie_dir(start) / "runs"


def cache_dir(start=None):
    path = reverie_dir(start) / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_runs_dir(start=None):
    """Where older versions wrote runs (`artifacts/agent-sessions`), if it exists; else None."""
    path = project_root(start) / LEGACY
    return path if path.is_dir() else None


def run_roots(start=None):
    """Directories that hold runs: `.reverie/runs`, then the legacy directory when it exists."""
    roots = [project_root(start) / NAME / "runs"]  # Reading history never creates .reverie/.
    legacy = legacy_runs_dir(start)
    if legacy is not None:
        roots.append(legacy)
    return roots


def env_files(start=None):
    """The .env files to read, first wins: $REVERIE_ENV_FILE, the project root's .env, the working directory's
    .env, then the user file $XDG_CONFIG_HOME/reverie/.env (default ~/.config/reverie/.env). Keep API keys in the
    user file to share them across projects without copying them into each repository."""
    here = Path(start or Path.cwd()).resolve()
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    wanted = [os.environ.get("REVERIE_ENV_FILE"), project_root(here) / ".env", here / ".env",
              config / "reverie" / ".env"]
    found = []
    for item in wanted:
        if item and Path(item).is_file() and Path(item).resolve() not in found:
            found.append(Path(item).resolve())
    return found


def playbook_path():
    configured = setting("REVERIE_PLAYBOOK")
    return Path(configured) if configured else reverie_dir() / "playbook.json"


def init(start=None):
    """Create `.reverie/` with its README, .gitignore, runs/, and specs/README.md. Returns the paths created."""
    root = project_root(start)
    base = root / NAME
    wanted = [base, base / ".gitignore", base / "README.md", base / "runs", base / "specs",
              base / "specs" / "README.md"]
    missing = [p for p in wanted if not p.exists()]
    reverie_dir(root)
    (base / "runs").mkdir(exist_ok=True)
    (base / "specs").mkdir(exist_ok=True)
    if not (base / "specs" / "README.md").exists():
        (base / "specs" / "README.md").write_text(SPECS_README)
    return missing


def write_run_summary(folder, summary):
    """Write `run.json` atomically. Best effort: the trail stays the source of truth."""
    try:
        target = Path(folder) / "run.json"
        temp = target.with_suffix(".json.tmp")
        temp.write_text(json.dumps(summary, indent=1, default=str))
        temp.replace(target)
    except OSError:
        pass


def summarize_trail(folder):
    """A `run.json` summary for a run folder written before run.json existed, from its trail's latest test."""
    from .dashboard import parse_trail

    runs = parse_trail(Path(folder) / "trail.jsonl")
    if not runs:
        return None
    run = runs[-1]
    return {"spec_id": spec_id(run["source"], run["title"]), "title": run["title"], "source": run["source"],
            "session": run["session"], "started": run["started"] or None, "ended": run["ended"] or None,
            "verdict": run["result"],
            "steps_done": sum(1 for st in run["steps"] if st["status"] not in {"pending", "running"}),
            "steps_total": len(run["steps"])}


def remap_sources(folder, mapping):
    """Rewrite spec `source` path prefixes (old -> new) in a run's trail plan events and run.json."""
    def fix(value):
        for old, new in mapping:
            if isinstance(value, str) and value.startswith(old):
                return new + value[len(old):]
        return value

    trail = Path(folder) / "trail.jsonl"
    lines, changed = [], False
    for line in trail.read_text(errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            lines.append(line)
            continue
        if record.get("event") == "plan" and fix(record.get("source")) != record.get("source"):
            record["source"], changed = fix(record["source"]), True
            line = json.dumps(record)
        lines.append(line)
    if changed:
        temp = trail.with_suffix(".jsonl.tmp")
        temp.write_text("\n".join(lines) + "\n")
        temp.replace(trail)
    return changed


def import_legacy(start=None, source=None, copy=False, mapping=()):
    """Bring legacy run folders into `.reverie/runs`: from `artifacts/agent-sessions` in this project, or from
    `source` (any older runs directory). Moves them unless `copy`. Rewrites spec paths by `mapping` (old, new)
    pairs, and writes run.json for every run that lacks one. Returns the imported folder names."""
    legacy = Path(source) if source else legacy_runs_dir(start)
    target = runs_dir(start)
    target.mkdir(parents=True, exist_ok=True)
    moved = []
    if legacy is not None and legacy.is_dir():
        for folder in sorted(legacy.iterdir()):
            if not (folder / "trail.jsonl").is_file() or (target / folder.name).exists():
                continue
            if copy:
                shutil.copytree(folder, target / folder.name)
            else:
                shutil.move(str(folder), str(target / folder.name))
            moved.append(folder.name)
        hidden = legacy / "hidden-runs.json"
        if hidden.is_file():
            try:
                ids = set(json.loads(hidden.read_text()))
                mine = target / "hidden-runs.json"
                if mine.is_file():
                    ids |= set(json.loads(mine.read_text()))
                mine.write_text(json.dumps(sorted(ids), indent=1))
                if not copy:
                    hidden.unlink()
            except (OSError, ValueError):
                pass
    for folder in sorted(target.iterdir()):
        if not (folder / "trail.jsonl").is_file():
            continue
        remapped = bool(mapping) and remap_sources(folder, mapping)
        if remapped or not (folder / "run.json").is_file():
            summary = summarize_trail(folder)
            if summary:
                write_run_summary(folder, summary)
    return moved


def spec_id(source=None, title=None):
    """A spec's id: its front-matter `id:`, else the title's leading token (`DEMO-01 — ...` gives DEMO-01)."""
    if source:
        try:
            with open(source) as handle:
                head = handle.read(4096)
            if head.startswith("---"):
                for line in head[3:].partition("\n---")[0].splitlines():
                    key, _, value = line.partition(":")
                    if key.strip() == "id" and value.strip():
                        return value.split(" #")[0].strip()
        except OSError:
            pass
    match = re.match(r"^\s*([A-Za-z][\w]*-\d+[\w.-]*)", title or "")
    return match.group(1) if match else None
