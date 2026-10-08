#!/usr/bin/env bash
# Reset WidgetLab's in-memory data on a running server.
set -euo pipefail
curl -fsS -X POST "http://127.0.0.1:${PORT:-8766}/reset"; echo
