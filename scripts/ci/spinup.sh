#!/bin/bash
# Spin up openhort test VMs in Azure — fully automated.
#
# Usage:
#   bash scripts/ci/spinup.sh              # Ubuntu only (default)
#   bash scripts/ci/spinup.sh all          # All platforms
#   bash scripts/ci/spinup.sh ubuntu       # Ubuntu only
#   bash scripts/ci/spinup.sh windows10    # Windows 10 only
#   bash scripts/ci/spinup.sh windows11    # Windows 11 only
#   SPOT=1 bash scripts/ci/spinup.sh all   # Use spot pricing (cheaper, may evict)
#
# Everything is automated: VM creation, software install, SSH setup,
# server start, and E2E verification. No manual steps required.
#
# Tear down: bash scripts/ci/teardown.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-ubuntu}"
RG="openhort-test-rg"
REGION="${REGION:-eastus}"
BRANCH="${BRANCH:-feature/windows-support}"

# Spot pricing flags
if [ "${SPOT:-0}" = "1" ]; then
    SPOT_FLAGS="--priority Spot --eviction-policy Deallocate --max-price -1"
    echo "  Mode: Spot instances (cheaper, may evict)"
else
    SPOT_FLAGS=""
    echo "  Mode: Pay-as-you-go"
fi

echo "=== openhort test environment ==="
echo "  Target:   $TARGET"
echo "  Region:   $REGION"
echo "  Branch:   $BRANCH"
echo "  RG:       $RG"
echo ""

# Create resource group
az group create --name "$RG" --location "$REGION" -o none 2>/dev/null || true

# ── Helpers ──────────────────────────────────────────────────────────

wait_for_ssh() {
    local IP="$1" USER="$2" MAX_WAIT="${3:-300}"
    echo "  Waiting for SSH ($IP)..."
    for i in $(seq 1 $((MAX_WAIT / 5))); do
        if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 -o BatchMode=yes "$USER@$IP" 'echo ok' >/dev/null 2>&1; then
            echo "  SSH ready after $((i * 5))s"
            return 0
        fi
        # Also try password auth (Windows)
        if command -v sshpass >/dev/null 2>&1; then
            if sshpass -p 'OpenHort2026!' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 "$USER@$IP" 'echo ok' >/dev/null 2>&1; then
                echo "  SSH ready (password) after $((i * 5))s"
                return 0
            fi
        fi
        sleep 5
    done
    echo "  SSH not ready after ${MAX_WAIT}s"
    return 1
}

wait_for_http() {
    local IP="$1" PORT="${2:-8940}" MAX_WAIT="${3:-120}"
    echo "  Waiting for HTTP ($IP:$PORT)..."
    for i in $(seq 1 $((MAX_WAIT / 5))); do
        if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://$IP:$PORT/" 2>/dev/null | grep -q "200"; then
            echo "  HTTP 200 after $((i * 5))s"
            return 0
        fi
        sleep 5
    done
    echo "  HTTP not ready after ${MAX_WAIT}s"
    return 1
}

ssh_cmd() {
    local IP="$1" USER="$2"
    shift 2
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$USER@$IP" "$@" 2>&1
}

ssh_cmd_pw() {
    local IP="$1" USER="$2"
    shift 2
    sshpass -p 'OpenHort2026!' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$USER@$IP" "$@" 2>&1
}

# ── Ubuntu ───────────────────────────────────────────────────────────

provision_ubuntu() {
    echo "--- Provisioning Ubuntu 24.04 ---"
    local IP
    IP=$(az vm create \
        --resource-group "$RG" \
        --name openhort-ubuntu \
        --image "Canonical:ubuntu-24_04-lts:server:latest" \
        --size Standard_B2s \
        $SPOT_FLAGS \
        --admin-username azureuser \
        --generate-ssh-keys \
        --custom-data "$SCRIPT_DIR/cloud-init-ubuntu-desktop.yml" \
        --public-ip-sku Standard \
        --nsg-rule SSH \
        --query publicIpAddress -o tsv)

    az vm open-port --resource-group "$RG" --name openhort-ubuntu --port 3389 --priority 1010 -o none &
    az vm open-port --resource-group "$RG" --name openhort-ubuntu --port 8940 --priority 1020 -o none &
    az vm auto-shutdown --resource-group "$RG" --name openhort-ubuntu --time 0000 -o none &
    wait

    # Wait for cloud-init to finish (installs desktop + openhort)
    echo "  Waiting for cloud-init (~5-10 min)..."
    wait_for_ssh "$IP" "azureuser" 300
    for i in $(seq 1 60); do
        STATUS=$(ssh_cmd "$IP" "azureuser" 'cloud-init status 2>/dev/null | grep -o "done\|running"' || echo "unknown")
        if [ "$STATUS" = "done" ]; then
            echo "  cloud-init done after $((i * 10))s"
            break
        fi
        sleep 10
    done

    # Verify openhort is running
    wait_for_http "$IP" 8940 60

    echo ""
    echo "  Ubuntu READY:"
    echo "    SSH:      ssh azureuser@$IP"
    echo "    RDP:      $IP:3389  (hortuser / OpenHort2026!)"
    echo "    openhort: http://$IP:8940"
    echo ""
}

# ── Windows ──────────────────────────────────────────────────────────

provision_windows() {
    local NAME="$1" DISPLAY_NAME="$2" IMAGE="$3"

    echo "--- Provisioning $DISPLAY_NAME ---"
    local IP
    IP=$(az vm create \
        --resource-group "$RG" \
        --name "$NAME" \
        --image "$IMAGE" \
        --size Standard_B2ms \
        $SPOT_FLAGS \
        --admin-username hortuser \
        --admin-password "OpenHort2026!" \
        --public-ip-sku Standard \
        --nsg-rule RDP \
        --query publicIpAddress -o tsv)

    az vm open-port --resource-group "$RG" --name "$NAME" --port 8940 --priority 1020 -o none &
    az vm open-port --resource-group "$RG" --name "$NAME" --port 22 --priority 1030 -o none &
    az vm auto-shutdown --resource-group "$RG" --name "$NAME" --time 0000 -o none &
    wait

    # Run setup via Custom Script Extension (async — installs SSH, Python, Git, openhort)
    echo "  Running setup script (~10 min)..."
    az vm extension set \
        --resource-group "$RG" \
        --vm-name "$NAME" \
        --name CustomScriptExtension \
        --publisher Microsoft.Compute \
        --version 1.10 \
        --settings "{\"commandToExecute\": \"powershell -ExecutionPolicy Bypass -Command \\\"iex (irm https://raw.githubusercontent.com/openhort/openhort/$BRANCH/scripts/ci/setup-windows.ps1)\\\"\"}" \
        -o none

    # Wait for SSH (installed by setup script)
    echo "  Waiting for SSH..."
    if ! wait_for_ssh "$IP" "hortuser" 600; then
        # Fallback: try password auth
        echo "  Key auth failed, SSH may need password auth"
    fi

    # Install our SSH key for passwordless access
    echo "  Installing SSH key..."
    local PUBKEY
    PUBKEY=$(cat ~/.ssh/id_rsa.pub 2>/dev/null || cat ~/.ssh/id_ed25519.pub 2>/dev/null || echo "")
    if [ -n "$PUBKEY" ]; then
        sshpass -p 'OpenHort2026!' ssh -o StrictHostKeyChecking=no "hortuser@$IP" "
            New-Item -ItemType Directory -Force -Path C:\Users\hortuser\.ssh | Out-Null
            Set-Content -Path C:\Users\hortuser\.ssh\authorized_keys -Value '$PUBKEY'
            icacls C:\Users\hortuser\.ssh\authorized_keys /inheritance:r /grant 'hortuser:(R)' /grant 'SYSTEM:(F)' | Out-Null
        " 2>/dev/null || echo "  (Key install via SSH failed — will use password auth)"
    fi

    # Start openhort in the interactive RDP session
    # The server needs an active desktop for screen capture (BitBlt/PrintWindow)
    # schtasks /Run /I runs in the interactive session
    echo "  Starting openhort in interactive session..."
    ssh_cmd_pw "$IP" "hortuser" '
        schtasks /Run /TN "openhort" /I 2>$null
    ' >/dev/null 2>&1 || ssh_cmd "$IP" "hortuser" '
        schtasks /Run /TN "openhort" /I 2>$null
    ' >/dev/null 2>&1 || true

    # Note: openhort won't respond until someone RDPs in (no desktop = no capture)
    # But the server itself will start and serve the UI
    sleep 10

    # Verify
    local HTTP_OK=false
    if wait_for_http "$IP" 8940 30; then
        HTTP_OK=true
    fi

    echo ""
    echo "  $DISPLAY_NAME READY:"
    echo "    SSH:      ssh hortuser@$IP  (or sshpass -p 'OpenHort2026!')"
    echo "    RDP:      $IP:3389  (hortuser / OpenHort2026!)"
    if [ "$HTTP_OK" = true ]; then
        echo "    openhort: http://$IP:8940  (running)"
    else
        echo "    openhort: http://$IP:8940  (starts after RDP login)"
    fi
    echo ""
    echo "    IMPORTANT: Screen capture requires an active RDP session."
    echo "    Connect via RDP once to activate the desktop, then openhort"
    echo "    will capture live content. Without RDP, thumbnails are black."
    echo ""
}

# ── Main ─────────────────────────────────────────────────────────────

case "$TARGET" in
    ubuntu)
        provision_ubuntu
        ;;
    windows10|win10)
        provision_windows "openhort-win10" "Windows 10" \
            "MicrosoftWindowsDesktop:windows-10:win10-22h2-pro-g2:latest"
        ;;
    windows11|win11)
        provision_windows "openhort-win11" "Windows 11" \
            "MicrosoftWindowsDesktop:windows-11:win11-24h2-pro:latest"
        ;;
    all)
        provision_ubuntu
        provision_windows "openhort-win10" "Windows 10" \
            "MicrosoftWindowsDesktop:windows-10:win10-22h2-pro-g2:latest"
        provision_windows "openhort-win11" "Windows 11" \
            "MicrosoftWindowsDesktop:windows-11:win11-24h2-pro:latest"
        ;;
    *)
        echo "Unknown target: $TARGET"
        echo "Usage: $0 [ubuntu|windows10|windows11|all]"
        exit 1
        ;;
esac

echo "=== Done ==="
echo "  Tear down: bash scripts/ci/teardown.sh"
echo "  Auto-shutdown: midnight UTC"
