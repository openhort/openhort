# openhort-sandbox-base — shared foundation for all sandbox images
#
# This image provides the OS, system tools, and user setup.
# LLM extensions build on top of it with their own Dockerfile:
#
#   FROM openhort-sandbox-base:latest
#   USER root
#   RUN npm install -g @anthropic-ai/claude-code
#   USER sandbox
#
# Build:  docker build -t openhort-sandbox-base:latest hort/sandbox/

FROM node:22-slim

ENV DEBIAN_FRONTEND=noninteractive

# ── System packages (rarely changes → cached) ─────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    jq \
    python3 \
    python3-pip \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Non-root user + workspace ─────────────────────────────────────
RUN useradd -m -s /bin/bash sandbox \
    && mkdir -p /workspace \
    && chown sandbox:sandbox /workspace

USER sandbox
WORKDIR /workspace

# Container stays alive between exec calls
CMD ["sleep", "infinity"]
