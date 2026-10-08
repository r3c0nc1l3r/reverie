#!/usr/bin/env bash
# Run reverie inside the container image, with the GPU, display, audio, env file, and project wired in.
#
#   scripts/reverie-docker.sh build [--multi]     build the image (--multi: amd64+arm64 with buildx, no --load)
#   scripts/reverie-docker.sh up | down | status  manage the long-lived container for this project
#   scripts/reverie-docker.sh doctor              show user, display, audio, GPU, and VA-API status
#   scripts/reverie-docker.sh gpu-check           open chrome://gpu in the container and report acceleration
#   scripts/reverie-docker.sh shell               bash in the container
#   scripts/reverie-docker.sh <reverie args...>   any reverie command, e.g. --session demo start --url http://localhost:8765/login
#
# `reverie start` leaves a daemon behind, so the container stays up between commands (starts on first use).
# Settings (environment):
#   REVERIE_IMAGE=reverie:local        REVERIE_DOCKER_NAME=reverie-<project dir>
#   REVERIE_PROJECT=$PWD               project mounted at the same path inside the container
#   REVERIE_DISPLAY=auto|wayland|x11|headless
#   REVERIE_AUDIO=auto|on|off          REVERIE_GPU=auto|dri|nvidia|off     REVERIE_GPU_BACKEND=egl|vulkan
#   REVERIE_DOCKER_NETWORK=host|bridge|<network>      host (default) reaches localhost stacks
#   REVERIE_ENV_FILE=~/.config/reverie/.env           mounted read-only at /etc/reverie/.env
#   REVERIE_DOCKER_DOWNLOADS=<project>/.reverie/downloads    -> /downloads (REVERIE_DOWNLOAD_DIR)
#   REVERIE_RUNS_DIR=<project>/.reverie/runs                 runs and artifacts
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE=${REVERIE_IMAGE:-reverie:local}
PROJECT=$(cd "${REVERIE_PROJECT:-$PWD}" && pwd)
slug=$(basename "$PROJECT" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9_.-]/-/g')
NAME=${REVERIE_DOCKER_NAME:-reverie-$slug}
MODE=${REVERIE_DISPLAY:-auto}
AUDIO=${REVERIE_AUDIO:-auto}
GPU=${REVERIE_GPU:-auto}
NETWORK=${REVERIE_DOCKER_NETWORK:-host}
ENV_FILE=${REVERIE_ENV_FILE:-$HOME/.config/reverie/.env}
DOWNLOADS=${REVERIE_DOCKER_DOWNLOADS:-$PROJECT/.reverie/downloads}
RUNS=${REVERIE_RUNS_DIR:-$PROJECT/.reverie/runs}
RT=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}

die() { echo "reverie-docker: $*" >&2; exit 2; }
running() { [[ $(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null) == true ]]; }

build() {
  if [[ ${1:-} == --multi ]]; then
    docker buildx build -f "$HERE/docker/Dockerfile" --platform "${REVERIE_PLATFORMS:-linux/amd64,linux/arm64}" \
      -t "$IMAGE" "${@:2}" "$HERE"   # add --push (registry) or --output type=oci,dest=reverie.tar
  else
    docker buildx build -f "$HERE/docker/Dockerfile" -t "$IMAGE" --load "$@" "$HERE"
  fi
}

up() {
  running && return 0
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  mkdir -p "$DOWNLOADS" "$RUNS"
  local args=(run -d --name "$NAME" --user "$(id -u):$(id -g)" --shm-size "${REVERIE_SHM:-1g}"
    --network "$NETWORK" --workdir "$PROJECT" --label reverie.project="$PROJECT"
    -e REVERIE_AUDIO="$AUDIO" -e REVERIE_GPU="$GPU" -e REVERIE_GPU_BACKEND="${REVERIE_GPU_BACKEND:-egl}"
    -e REVERIE_DOWNLOAD_DIR=/downloads -e HOME=/home/reverie
    -v "$PROJECT:$PROJECT" -v "$DOWNLOADS:/downloads")
  [[ $RUNS == "$PROJECT/.reverie/runs" ]] || args+=(-v "$RUNS:$PROJECT/.reverie/runs")

  # Reverie's own loader reads it (quotes and `export` lines work); docker --env-file rejects `export` lines.
  if [[ -f $ENV_FILE ]]; then
    args+=(-v "$ENV_FILE:/etc/reverie/.env:ro" -e REVERIE_ENV_FILE=/etc/reverie/.env)
  fi

  # GPU: Mesa through /dev/dri for AMD and Intel; the host's render/video groups let the user open the nodes.
  if [[ $GPU == nvidia ]]; then
    args+=(--gpus all -e NVIDIA_DRIVER_CAPABILITIES=all)
  elif [[ $GPU != off && -d /dev/dri ]]; then
    args+=(--device /dev/dri)
    for node in /dev/dri/*; do [[ -c $node ]] && args+=(--group-add "$(stat -c %g "$node")"); done
  fi

  # Display: Wayland first, then X11, else headless.
  local wl=${WAYLAND_DISPLAY:-wayland-0}
  if [[ $MODE == auto ]]; then
    if [[ -S $RT/$wl ]]; then MODE=wayland
    elif [[ -n ${DISPLAY:-} && -d /tmp/.X11-unix ]]; then MODE=x11
    else MODE=headless; fi
  fi
  case $MODE in
    wayland) [[ -S $RT/$wl ]] || die "no Wayland socket at $RT/$wl"
      args+=(-v "$RT/$wl:/runtime/$wl" -e WAYLAND_DISPLAY="$wl") ;;
    x11) [[ -n ${DISPLAY:-} ]] || die "DISPLAY is not set"
      args+=(-v /tmp/.X11-unix:/tmp/.X11-unix -e DISPLAY="$DISPLAY")
      if [[ -n ${XAUTHORITY:-} && -f $XAUTHORITY ]]; then args+=(-v "$XAUTHORITY:/tmp/.Xauthority:ro" -e XAUTHORITY=/tmp/.Xauthority); fi ;;
    headless) ;;
    *) die "REVERIE_DISPLAY must be auto, wayland, x11, or headless" ;;
  esac

  # Audio: PulseAudio, or PipeWire's pulse socket.
  if [[ $AUDIO != off && -S $RT/pulse/native ]]; then
    args+=(-v "$RT/pulse/native:/runtime/pulse/native" -e PULSE_SERVER=unix:/runtime/pulse/native)
  elif [[ $AUDIO == on ]]; then die "REVERIE_AUDIO=on but $RT/pulse/native is missing"; fi

  args+=("$IMAGE" sleep-forever)
  docker "${args[@]}" >/dev/null
  echo "reverie-docker: $NAME up (display=$MODE audio=$AUDIO gpu=$GPU network=$NETWORK)" >&2
}

container_mode() { docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$NAME" | grep -q '^\(WAYLAND_DISPLAY\|DISPLAY\)=' && echo headed || echo headless; }

cmd=${1:-help}
case $cmd in
  help|-h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//' ;;
  build) shift; build "$@" ;;
  up) up ;;
  down) docker rm -f "$NAME" >/dev/null 2>&1 && echo "reverie-docker: $NAME removed" || true ;;
  status) running && echo "$NAME running ($(container_mode))" || { echo "$NAME not running"; exit 1; } ;;
  logs) docker logs "$NAME" ;;
  doctor|gpu-check|shell)
    up; tty=(-i); [[ -t 0 && -t 1 ]] && tty=(-it)
    case $cmd in
      doctor) docker exec "${tty[@]}" -w "$PROJECT" "$NAME" reverie-entrypoint doctor ;;
      gpu-check) shift; docker exec "${tty[@]}" -w "$PROJECT" "$NAME" reverie-entrypoint reverie-gpu-check \
        --out "${REVERIE_GPU_OUT:-/downloads}" "$@" ;;
      shell) docker exec "${tty[@]}" -w "$PROJECT" "$NAME" reverie-entrypoint bash ;;
    esac ;;
  *)
    up
    args=("$@")
    # In a headless container, `start` gets --headless unless the caller already chose.
    if [[ $(container_mode) == headless ]]; then
      for a in "${args[@]}"; do
        if [[ $a == start ]]; then
          [[ " ${args[*]} " == *" --headless "* ]] || args+=(--headless)
          break
        fi
      done
    fi
    tty=(-i); [[ -t 0 && -t 1 ]] && tty=(-it)
    exec docker exec "${tty[@]}" -w "$PWD" "$NAME" reverie-entrypoint reverie "${args[@]}" ;;
esac
