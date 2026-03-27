# llming-models sandbox — extends the openhort base image
#
# Requires the base image:
#   docker build -t openhort-sandbox-base:latest hort/sandbox/
#
# Build:
#   docker build -t openhort-sandbox-llming:latest hort/extensions/llms/llming_api/

FROM openhort-sandbox-base:latest

USER root

# ── llming-models SDK + provider dependencies ──────────────────────
RUN pip3 install --no-cache-dir --break-system-packages \
    llming-models \
    anthropic \
    openai \
    tiktoken

USER sandbox
