#!/bin/bash
# Deploy the P2P viewer to the website.
# The viewer is a thin proxy — only WebRTC + DataChannel code.
# No static assets, no vendor libs, no UI code.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="$SCRIPT_DIR/deploy-viewer.conf"

if [ ! -f "$CONF" ]; then
  echo "ERROR: scripts/deploy-viewer.conf not found."
  echo "Copy scripts/deploy-viewer.conf.example and set WEBSITE_DIR."
  exit 1
fi
source "$CONF"

if [ ! -d "$WEBSITE_DIR" ]; then
  echo "ERROR: $WEBSITE_DIR not found"
  exit 1
fi

SOURCE="$SCRIPT_DIR/../hort/extensions/core/peer2peer/static/viewer.html"
DEST="$WEBSITE_DIR/public/p2p/viewer.html"

mkdir -p "$(dirname "$DEST")"
cp "$SOURCE" "$DEST"
echo "Copied viewer.html → $DEST"

cd "$WEBSITE_DIR"
bash scripts/deploy-viewer.sh
