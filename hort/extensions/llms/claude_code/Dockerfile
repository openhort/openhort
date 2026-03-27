# Claude Code sandbox — extends the openhort base image
#
# Requires the base image to be built first:
#   docker build -t openhort-sandbox-base:latest hort/sandbox/
#
# Build:
#   docker build -t openhort-sandbox-claude:latest hort/extensions/llms/claude_code/
#
# Pin CLI version:
#   docker build --build-arg CLAUDE_CLI_VERSION=1.0.20 -t openhort-sandbox-claude:latest .

FROM openhort-sandbox-base:latest

USER root

# ── Claude Code CLI ────────────────────────────────────────────────
ARG CLAUDE_CLI_VERSION=""
RUN if [ -n "$CLAUDE_CLI_VERSION" ]; then \
      npm install -g "@anthropic-ai/claude-code@$CLAUDE_CLI_VERSION"; \
    else \
      npm install -g @anthropic-ai/claude-code; \
    fi

USER sandbox
