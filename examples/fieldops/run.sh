#!/usr/bin/env bash
# Start FieldOps on http://127.0.0.1:${PORT:-8765}. The database is seeded on the first run.
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-8765}"
if command -v uv >/dev/null 2>&1; then
  exec uv run --script app/fieldops.py serve "$@"
fi
exec python3 app/fieldops.py serve "$@"
