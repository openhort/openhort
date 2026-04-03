#!/bin/bash
# Build the HortStatusBar binary from Swift sources.
# Usage: bash build.sh

set -euo pipefail
cd "$(dirname "$0")"

mkdir -p build

echo "Compiling HortStatusBar..."
swiftc -O \
    -o build/HortStatusBar \
    Sources/SharedKey.swift \
    Sources/PowerManager.swift \
    Sources/ServerBridge.swift \
    Sources/StatusBarController.swift \
    Sources/main.swift \
    -framework AppKit \
    -framework IOKit \
    -framework Security

echo "Built: build/HortStatusBar"
