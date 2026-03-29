#!/bin/bash
set -e

# ── Start X11 virtual framebuffer ────────────────────────────────────
RESOLUTION="${HORT_RESOLUTION:-1920x1080x24}"
echo "Starting Xvfb on $DISPLAY ($RESOLUTION)..."
Xvfb $DISPLAY -screen 0 "$RESOLUTION" -ac +extension GLX +render -noreset &
XVFB_PID=$!

# Wait for Xvfb to be ready
for i in $(seq 1 30); do
    xdpyinfo -display $DISPLAY >/dev/null 2>&1 && break
    sleep 0.2
done

# ── Start window manager ─────────────────────────────────────────────
echo "Starting fluxbox..."
fluxbox &
sleep 0.5

# ── Launch sample windows (optional, set HORT_NO_DEMO to skip) ───────
if [ -z "$HORT_NO_DEMO" ]; then
    xterm -geometry 100x30+50+50 -title "Terminal" &
    xeyes -geometry 200x200+800+100 &
    xterm -geometry 80x20+200+400 -title "System Monitor" -e "top" &
    echo "Demo windows launched"
fi

echo "Desktop ready on DISPLAY=$DISPLAY"

# ── Start openhort server ────────────────────────────────────────────
echo "Starting openhort server..."
cd /app
exec python -m uvicorn hort.app:app \
    --host 0.0.0.0 \
    --port "${HORT_HTTP_PORT:-8940}" \
    --log-level info
