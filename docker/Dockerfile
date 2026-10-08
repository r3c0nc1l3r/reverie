# syntax=docker/dockerfile:1.7
#
# Reverie in a container: Python + uv, Playwright's Chromium, Mesa/VA-API GPU userspace, audio clients.
# Multi-arch (linux/amd64, linux/arm64). See docs/docker.md.
#
#   docker buildx build -f docker/Dockerfile -t reverie:local --load .
#   docker buildx build -f docker/Dockerfile --platform linux/amd64,linux/arm64 -t ghcr.io/you/reverie --push .

ARG PYTHON_VERSION=3.12
ARG DEBIAN_RELEASE=trixie
ARG UV_VERSION=0.12.23

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS base
ARG TARGETARCH
ARG PLAYWRIGHT_VERSION=1.63.0
ARG REVERIE_UID=1000
ARG REVERIE_GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/reverie/venv \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=1

COPY --from=uv /uv /uvx /usr/local/bin/

# GPU userspace (Mesa GL/EGL/GBM/Vulkan, VA-API), audio clients, fonts, and a minimal init.
# Intel VA-API drivers exist for x86 only; Mesa's radeonsi/nouveau/v3d/panfrost VA drivers ship for both.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && packages="ca-certificates curl tini xauth \
        libgl1-mesa-dri libegl1 libegl-mesa0 libgles2 libgbm1 libglx-mesa0 libdrm2 libdrm-amdgpu1 \
        mesa-va-drivers mesa-vulkan-drivers libvulkan1 libva2 libva-drm2 libva-x11-2 libva-wayland2 vainfo \
        libwayland-client0 libwayland-egl1 libxkbcommon0 \
        pulseaudio-utils libasound2-plugins mpv \
        fonts-liberation fonts-noto-color-emoji fonts-dejavu-core" \
    && if [ "$TARGETARCH" = "amd64" ]; then packages="$packages intel-media-va-driver i965-va-driver"; fi \
    && apt-get install -y --no-install-recommends $packages

# Playwright's Chromium and its system libraries. Playwright is a build tool here, not a Reverie dependency:
# Reverie launches the browser itself and talks CDP. The layer only rebuilds when PLAYWRIGHT_VERSION changes.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update \
    && uv venv /opt/playwright-tool \
    && uv pip install --python /opt/playwright-tool/bin/python "playwright==${PLAYWRIGHT_VERSION}" \
    && /opt/playwright-tool/bin/playwright install-deps chromium \
    && /opt/playwright-tool/bin/playwright install chromium --no-shell \
    && ln -s "$(ls -d /opt/ms-playwright/chromium-*/chrome-linux*/ | head -1)chrome" /usr/local/bin/chromium-playwright

# A user that matches the common host UID/GID. The launcher overrides it with --user "$(id -u):$(id -g)".
RUN groupadd --gid "$REVERIE_GID" reverie \
    && useradd --uid "$REVERIE_UID" --gid "$REVERIE_GID" --create-home --shell /bin/bash reverie \
    && mkdir -p /opt/reverie /downloads /runtime \
    && chmod 1777 /downloads /runtime \
    && chmod 0777 /home/reverie

# Python dependencies first (cached until uv.lock changes), then the project.
WORKDIR /opt/reverie/src
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-install-project
COPY reverie ./reverie
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev \
    && chmod -R a+rX /opt/reverie /opt/ms-playwright

COPY docker/entrypoint.sh /usr/local/bin/reverie-entrypoint
COPY docker/reverie-chromium /usr/local/bin/reverie-chromium
COPY docker/gpu-check.py /usr/local/bin/reverie-gpu-check
RUN chmod 0755 /usr/local/bin/reverie-entrypoint /usr/local/bin/reverie-chromium /usr/local/bin/reverie-gpu-check \
    && sed -i '1i #!/opt/reverie/venv/bin/python' /usr/local/bin/reverie-gpu-check

ENV PATH=/opt/reverie/venv/bin:$PATH \
    HOME=/home/reverie \
    XDG_RUNTIME_DIR=/runtime \
    REVERIE_BROWSER=/usr/local/bin/reverie-chromium \
    REVERIE_DOWNLOAD_DIR=/downloads \
    REVERIE_GPU=auto \
    REVERIE_AUDIO=auto

USER reverie
WORKDIR /work
VOLUME ["/downloads"]
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/reverie-entrypoint"]
CMD ["reverie", "--help"]
