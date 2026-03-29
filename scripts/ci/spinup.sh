#!/bin/bash
# Spin up openhort test VMs in Azure.
#
# Usage:
#   bash scripts/ci/spinup.sh              # Ubuntu only (default)
#   bash scripts/ci/spinup.sh all          # All platforms
#   bash scripts/ci/spinup.sh ubuntu       # Ubuntu only
#   bash scripts/ci/spinup.sh windows10    # Windows 10 only
#   bash scripts/ci/spinup.sh windows11    # Windows 11 only
#   SPOT=1 bash scripts/ci/spinup.sh all   # Use spot pricing (cheaper, may evict)
#
# After provisioning completes (~5-10 min), connect via:
#   RDP:  <ip>:3389
#   HTTP: http://<ip>:8940
#
# Tear down: bash scripts/ci/teardown.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-ubuntu}"
RG="openhort-test-rg"
REGION="${REGION:-eastus}"

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
echo "  RG:       $RG"
echo ""

# Create resource group
az group create --name "$RG" --location "$REGION" -o none 2>/dev/null || true

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

    echo "  Ubuntu ready:"
    echo "    RDP:      $IP:3389  (hortuser / OpenHort2026!)"
    echo "    openhort: http://$IP:8940"
    echo "    SSH:      ssh azureuser@$IP"
    echo ""
}

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
    az vm auto-shutdown --resource-group "$RG" --name "$NAME" --time 0000 -o none &
    wait

    # Run setup script via Custom Script Extension
    echo "  Installing openhort via PowerShell (takes 5-10 min)..."
    az vm run-command invoke \
        --resource-group "$RG" \
        --name "$NAME" \
        --command-id RunPowerShellScript \
        --scripts @"$SCRIPT_DIR/setup-windows.ps1" \
        -o none &

    echo "  $DISPLAY_NAME ready:"
    echo "    RDP:      $IP:3389  (hortuser / OpenHort2026!)"
    echo "    openhort: http://$IP:8940  (after setup completes)"
    echo "    Setup runs in background — RDP in to monitor progress"
    echo ""
}

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
