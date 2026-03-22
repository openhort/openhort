#!/bin/bash
set -e

# Start virtual framebuffer (1920x1080, 24-bit color)
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
sleep 1

# Start lightweight window manager
fluxbox &
sleep 1

# Launch a couple of sample windows so there's something to see
xterm -geometry 100x30+50+50 -title "Terminal" &
xeyes -geometry 200x200+800+100 &
xterm -geometry 80x20+200+400 -title "Second Terminal" -e "top" &

echo "Desktop ready on DISPLAY=:99"

# Keep container alive
wait
