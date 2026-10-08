#!/bin/sh
# Container entrypoint. Runs for `docker run` and for every `docker exec` that the launcher makes, so it
# must be idempotent: it only derives environment (audio, display, GPU) and then execs the command.
#
#   REVERIE_AUDIO   auto (default) | on | off   narration through the mounted PulseAudio/PipeWire socket
#   REVERIE_GPU     auto (default) | dri | off  see reverie-chromium
#   REVERIE_DOWNLOAD_DIR                         where the browser saves downloads (default /downloads)
set -eu

RUNTIME="${XDG_RUNTIME_DIR:-/runtime}"
mkdir -p "$RUNTIME" "${REVERIE_DOWNLOAD_DIR:-/downloads}" 2>/dev/null || true

# Audio. The launcher mounts the host socket at $RUNTIME/pulse/native (PipeWire exposes the same protocol).
audio="${REVERIE_AUDIO:-auto}"
if [ "$audio" = "auto" ]; then
    if [ -S "$RUNTIME/pulse/native" ] || [ -n "${PULSE_SERVER:-}" ]; then audio=on; else audio=off; fi
fi
if [ "$audio" = "on" ]; then
    [ -n "${PULSE_SERVER:-}" ] || export PULSE_SERVER="unix:$RUNTIME/pulse/native"
else
    # No player and no offline voice are installed, so "off" makes Reverie resolve its voice to off.
    unset PULSE_SERVER
    export SPEECH_PROVIDER=off
fi

# Display. Wayland wins over X11 when both sockets are mounted.
if [ -n "${WAYLAND_DISPLAY:-}" ] && [ ! -S "$RUNTIME/$WAYLAND_DISPLAY" ] && [ ! -S "$WAYLAND_DISPLAY" ]; then
    unset WAYLAND_DISPLAY
fi
if [ -n "${DISPLAY:-}" ]; then
    num="${DISPLAY#*:}"; num="${num%%.*}"
    [ -S "/tmp/.X11-unix/X$num" ] || unset DISPLAY
fi
if [ -n "${WAYLAND_DISPLAY:-}" ] || [ -n "${DISPLAY:-}" ]; then
    export REVERIE_HAS_DISPLAY=1
else
    export REVERIE_HAS_DISPLAY=0
fi

if [ "${REVERIE_DOCKER_DOCTOR:-0}" = "1" ] || [ "${1:-}" = "doctor" ]; then
    [ "${1:-}" = "doctor" ] && shift
    echo "user:       $(id -u):$(id -g) groups=$(id -G)"
    echo "arch:       $(uname -m)"
    echo "display:    wayland=${WAYLAND_DISPLAY:-none} x11=${DISPLAY:-none}"
    echo "audio:      $audio (PULSE_SERVER=${PULSE_SERVER:-unset}) speech=${SPEECH_PROVIDER:-default}"
    echo "gpu:        REVERIE_GPU=${REVERIE_GPU:-auto}"; ls -l /dev/dri 2>/dev/null | sed 's/^/            /' || echo "            no /dev/dri"
    echo "downloads:  ${REVERIE_DOWNLOAD_DIR:-/downloads} ($( [ -w "${REVERIE_DOWNLOAD_DIR:-/downloads}" ] && echo writable || echo NOT writable))"
    echo "browser:    ${LAYA_AGENT_BROWSER:-unset}"
    if command -v vainfo >/dev/null 2>&1 && [ -e /dev/dri/renderD128 ]; then
        vainfo 2>&1 | sed -n '1,12p' | sed 's/^/vainfo:     /'
    fi
    exit 0
fi

# `sleep-forever` keeps a long-lived container for `docker exec` sessions (reverie start leaves a daemon).
if [ "${1:-}" = "sleep-forever" ]; then
    exec sleep infinity
fi
exec "$@"
