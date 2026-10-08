#!/usr/bin/env bash
# Live smoke test for the hosted Jev decision engine (opt-in; it spends a little OpenRouter credit).
#
#   scripts/jev-smoke.sh          four Jev decisions on a synthetic page (about $0.001)
#   scripts/jev-smoke.sh --e2e    also run WidgetLab spec WL-05 headless with --engine jev (pilot model calls too)
#
# Keys come from the environment or Reverie's .env files (~/.config/reverie/.env). Without OPENROUTER_API_KEY the
# decision test is skipped. Downloads, runs and the browser profile go to a temporary folder that is removed.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
REVERIE_LIVE_JEV=1 uv run pytest -q -s tests/test_jev_live.py
[[ "${1:-}" == "--e2e" ]] || exit 0

work="$(mktemp -d)"
port="${PORT:-8796}"
session="jev-smoke-$$"
reverie() { uv run --project "$root" reverie --session "$session" "$@"; }
cleanup() {
  (cd "$work" && reverie stop >/dev/null 2>&1) || true
  [[ -n "${app:-}" ]] && kill "$app" 2>/dev/null || true
  rm -rf "$work"
}
trap cleanup EXIT
PORT="$port" examples/widgetlab/run.sh >"$work/widgetlab.log" 2>&1 &
app=$!
for _ in $(seq 30); do curl -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1 && break; sleep 0.5; done
cd "$work"
reverie start --headless --voice off --engine jev --download-dir "$work/downloads" --url "http://127.0.0.1:$port/" >/dev/null
reverie spec "$root/examples/widgetlab/specs/wl-05-type-ahead.md" >/dev/null
reverie pilot --max 60 >/dev/null
for _ in $(seq 60); do
  reverie progress | grep -q 'pilot: running' || break
  sleep 5
done
reverie progress | sed -n '1,6p'
reverie progress | grep -q '\[pass\]'
