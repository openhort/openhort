FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    fluxbox \
    xterm \
    x11-apps \
    wmctrl \
    xdotool \
    imagemagick \
    x11-utils \
    dbus-x11 \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Fluxbox config: no decorations toolbar clutter
RUN mkdir -p /root/.fluxbox && \
    echo '[begin] (fluxbox)\n[end]' > /root/.fluxbox/menu && \
    echo 'session.screen0.toolbar.visible: false' > /root/.fluxbox/init

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
