#!/usr/bin/env bash
# Delete the FieldOps database and seed it again. Safe while the app runs.
set -euo pipefail
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then
  exec uv run --script app/fieldops.py reset
fi
exec python3 app/fieldops.py reset
