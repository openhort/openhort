FROM node:22-slim

ENV DEBIAN_FRONTEND=noninteractive

# Basic tools Claude might use
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    jq \
    python3 \
    python3-pip \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Non-root user (--dangerously-skip-permissions refuses to run as root)
RUN useradd -m -s /bin/bash claude
RUN mkdir -p /workspace && chown claude:claude /workspace

USER claude
WORKDIR /workspace

# Keep the container alive
CMD ["sleep", "infinity"]
