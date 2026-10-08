#!/usr/bin/env bash
# Start WidgetLab on http://127.0.0.1:${PORT:-8766}. State is in memory: restart (or POST /reset) to reset it.
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-8766}"
if command -v uv >/dev/null 2>&1; then
  exec uv run --script app/widgetlab.py "$@"
fi
exec python3 app/widgetlab.py "$@"
