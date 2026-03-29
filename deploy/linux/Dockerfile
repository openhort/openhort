# openhort server — full Linux deployment with X11 desktop
# Build context: project root (yayHort/)
#
# Build:  docker build -f deploy/linux/Dockerfile -t openhort-linux .
# Run:    docker run -p 8940:8940 -e LLMING_AUTH_SECRET=changeme openhort-linux

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV PYTHONUNBUFFERED=1

# ── System packages: X11 desktop + Python 3.12 ──────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python
    python3.12 python3.12-venv python3-pip python3.12-dev \
    # X11 virtual framebuffer + window manager
    xvfb fluxbox \
    # X11 tools for window management / capture / input
    wmctrl xdotool imagemagick x11-utils x11-apps xterm \
    # Build tools (for native Python deps)
    gcc g++ pkg-config \
    # Runtime
    procps dbus-x11 git curl \
    && rm -rf /var/lib/apt/lists/*

# Make python3.12 the default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

# ── Install Poetry ───────────────────────────────────────────────────
RUN python3 -m pip install --break-system-packages poetry==2.1.3

# ── Install llming-com from GitHub (runtime dependency) ──────────────
RUN python3 -m pip install --break-system-packages \
    "git+https://github.com/Alyxion/llming-com.git@main" \
    "aiogram>=3.26.0,<4.0"

# ── Copy project and install ─────────────────────────────────────────
WORKDIR /app

# Copy dependency files first (cache layer)
COPY pyproject.toml poetry.lock* ./

# Install dependencies (no dev deps, no local path deps)
RUN poetry config virtualenvs.create false && \
    poetry install --only main --no-root --no-interaction 2>/dev/null || \
    python3 -m pip install --break-system-packages \
        "fastapi>=0.115,<1.0" \
        "uvicorn[standard]>=0.34,<1.0" \
        "Pillow>=11.0,<12.0" \
        "qrcode[pil]>=8.0,<9.0" \
        "pydantic>=2.10,<3.0" \
        "websockets>=16.0,<17.0" \
        "itsdangerous>=2.2.0,<3.0.0" \
        "pyyaml>=6.0.3,<7.0.0" \
        "psutil>=7.2.2,<8.0.0" \
        "aiortc>=1.14.0,<2.0.0"

# Copy the full project
COPY . .

# Install the project itself
RUN python3 -m pip install --break-system-packages -e . 2>/dev/null || true

# ── Fluxbox config (minimal, no toolbar) ─────────────────────────────
RUN mkdir -p /root/.fluxbox && \
    printf '[begin] (fluxbox)\n[end]\n' > /root/.fluxbox/menu && \
    echo 'session.screen0.toolbar.visible: false' > /root/.fluxbox/init

# ── Entrypoint ───────────────────────────────────────────────────────
COPY deploy/linux/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8940

CMD ["/entrypoint.sh"]
