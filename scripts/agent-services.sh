#!/usr/bin/env bash
# Start, stop, or inspect the local services behind laya-agent: laya.cpp decisions and local narration.
# LOCAL_TTS=kitten (default; CPU, no GPU memory) or kokoro (ggml; ~450 MiB VRAM on Vulkan, which can
# exhaust a 2 GiB iGPU carve-out).
# Prefers Vulkan builds and falls back to CPU builds. Logs and pid files live in $STATE.
#
#   scripts/agent-services.sh start | stop | status
#
# Paths (override with env): TOOLS_DIR=~/tools holds the checkouts below unless each is set on its own.
#   LAYA_CPP_DIR=$TOOLS_DIR/laya.cpp  CRISPASR_DIR=$TOOLS_DIR/CrispASR  KITTEN_PYTHON=$TOOLS_DIR/kitten-tts/.venv/bin/python
#   KOKORO_MODEL_DIR=~/.cache/crispasr  LAYA_PORT=8080  KOKORO_PORT=8880
set -euo pipefail

TOOLS_DIR=${TOOLS_DIR:-$HOME/tools}
LAYA_CPP_DIR=${LAYA_CPP_DIR:-$TOOLS_DIR/laya.cpp}
CRISPASR_DIR=${CRISPASR_DIR:-$TOOLS_DIR/CrispASR}
KOKORO_MODEL_DIR=${KOKORO_MODEL_DIR:-$HOME/.cache/crispasr}
LAYA_PORT=${LAYA_PORT:-8080}
KOKORO_PORT=${KOKORO_PORT:-8880}
KOKORO_VOICE=${KOKORO_VOICE:-af_heart}
LOCAL_TTS=${LOCAL_TTS:-kitten}
KITTEN_PYTHON=${KITTEN_PYTHON:-$TOOLS_DIR/kitten-tts/.venv/bin/python}
KITTEN_PORT=${KITTEN_PORT:-8890}
KITTEN_VOICE=${KITTEN_VOICE:-Jasper}
HERE=$(cd "$(dirname "$0")" && pwd)
STATE=${XDG_RUNTIME_DIR:-$HOME/.cache}/laya-agent/services
mkdir -p "$STATE"

pick() {  # pick <vulkan-binary> <cpu-binary> -> "path flag"
  if [[ -x $1 ]] && vulkaninfo --summary >/dev/null 2>&1; then echo "$1 vulkan"; elif [[ -x $2 ]]; then echo "$2 cpu"; fi
}

running() { [[ -f $STATE/$1.pid ]] && kill -0 "$(cat "$STATE/$1.pid")" 2>/dev/null; }

wait_http() {  # wait_http <url> <seconds>
  for _ in $(seq "$2"); do curl -sf --max-time 2 "$1" >/dev/null && return 0; sleep 1; done
  return 1
}

start_laya() {
  running laya && { echo "laya:   already running"; return; }
  read -r bin mode < <(pick "$LAYA_CPP_DIR/build-vulkan/bin/laya-cli" "$LAYA_CPP_DIR/build-cpu/bin/laya-cli") || true
  [[ -n ${bin:-} ]] || { echo "laya:   no laya-cli build in $LAYA_CPP_DIR" >&2; return 1; }
  nohup "$bin" "--$mode" --server --host 127.0.0.1 --port "$LAYA_PORT" \
    --model "$LAYA_CPP_DIR/models/laya" --variant typed-decisions >"$STATE/laya.log" 2>&1 &
  echo $! >"$STATE/laya.pid"
  if wait_http "http://127.0.0.1:$LAYA_PORT/health" 90; then
    echo "laya:   ready ($mode) http://127.0.0.1:$LAYA_PORT"
  else
    echo "laya:   did not become healthy; see $STATE/laya.log" >&2; return 1
  fi
}

start_kokoro() {
  running kokoro && { echo "kokoro: already running"; return; }
  read -r bin mode < <(pick "$CRISPASR_DIR/build-vulkan/bin/crispasr" "$CRISPASR_DIR/build-cpu/bin/crispasr") || true
  [[ -n ${bin:-} ]] || { echo "kokoro: no crispasr build in $CRISPASR_DIR" >&2; return 1; }
  # On Vulkan, also run the iSTFTNet vocoder on the GPU (the CPU pin only works around a Metal hang).
  [[ $mode == vulkan ]] && export CRISPASR_KOKORO_GEN_GPU=1
  nohup "$bin" --server --backend kokoro --host 127.0.0.1 --port "$KOKORO_PORT" \
    -m "$KOKORO_MODEL_DIR/kokoro-82m-f16.gguf" --voice-dir "$KOKORO_MODEL_DIR" \
    --voice "$KOKORO_MODEL_DIR/kokoro-voice-$KOKORO_VOICE.gguf" -l en >"$STATE/kokoro.log" 2>&1 &
  echo $! >"$STATE/kokoro.pid"
  if wait_http "http://127.0.0.1:$KOKORO_PORT/health" 90; then
    echo "kokoro: ready ($mode) http://127.0.0.1:$KOKORO_PORT"
  else
    echo "kokoro: did not become healthy; see $STATE/kokoro.log" >&2; return 1
  fi
}

start_kitten() {
  running kitten && { echo "kitten: already running"; return; }
  [[ -x $KITTEN_PYTHON ]] || { echo "kitten: no kittentts environment at $KITTEN_PYTHON" >&2; return 1; }
  nohup "$KITTEN_PYTHON" "$HERE/kitten_server.py" --port "$KITTEN_PORT" --voice "$KITTEN_VOICE" \
    >"$STATE/kitten.log" 2>&1 &
  echo $! >"$STATE/kitten.pid"
  if wait_http "http://127.0.0.1:$KITTEN_PORT/health" 120; then
    echo "kitten: ready (cpu) http://127.0.0.1:$KITTEN_PORT"
  else
    echo "kitten: did not become healthy; see $STATE/kitten.log" >&2; return 1
  fi
}

stop_one() {
  if running "$1"; then kill "$(cat "$STATE/$1.pid")"; echo "$1: stopped"; else echo "$1: not running"; fi
  rm -f "$STATE/$1.pid"
}

case ${1:-status} in
  start) start_laya; if [[ $LOCAL_TTS == kokoro ]]; then start_kokoro; else start_kitten; fi ;;
  stop) stop_one laya; stop_one kokoro; stop_one kitten ;;
  status)
    for s in laya kokoro kitten; do
      if running "$s"; then echo "$s: running (pid $(cat "$STATE/$s.pid"))"; else echo "$s: stopped"; fi
    done ;;
  *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
