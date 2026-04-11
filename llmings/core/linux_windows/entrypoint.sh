#!/bin/bash

# Start virtual framebuffer (1920x1080, 24-bit color)
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!

# Wait for Xvfb to be ready
for i in $(seq 1 30); do
    xdpyinfo -display :99 >/dev/null 2>&1 && break
    sleep 0.2
done

# Start lightweight window manager
fluxbox &
sleep 0.5

# Launch sample windows (failures are non-fatal)
xterm -geometry 100x30+50+50 -title "Terminal" &
xeyes -geometry 200x200+800+100 &
xterm -geometry 80x20+200+400 -title "Second Terminal" -e "top" &

echo "Desktop ready on DISPLAY=:99"

# Keep container alive by waiting on Xvfb (the core process)
wait $XVFB_PID
