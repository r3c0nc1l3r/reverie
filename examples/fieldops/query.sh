#!/usr/bin/env bash
# Print the rows of one read-only SQL query against the FieldOps database (for [admin] checkpoints).
# Example: ./query.sh "select number, status from work_orders order by number"
set -euo pipefail
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then
  exec uv run --script app/fieldops.py query "$1"
fi
exec python3 app/fieldops.py query "$1"
