#!/bin/bash
# Provision an Ubuntu Desktop VM in Azure for openhort testing.
#
# Usage: bash scripts/ci/provision-ubuntu.sh [resource-group] [vm-name] [region]
#
# The VM gets:
# - Ubuntu 24.04 with XFCE desktop
# - xrdp for remote desktop access (port 3389)
# - openhort server running on port 8940
# - A persistent X11 session for openhort to capture
#
# Connect via:
#   RDP:  <public-ip>:3389  (user: hortuser, pass: OpenHort2026!)
#   HTTP: http://<public-ip>:8940
#
# Estimated cost: ~$0.03/hr (Standard_B2ms spot) or ~$0.08/hr (pay-as-you-go)

set -e

RG="${1:-openhort-test-rg}"
VM_NAME="${2:-openhort-ubuntu}"
REGION="${3:-eastus}"
SIZE="${4:-Standard_B2s}"  # 2 vCPU, 4 GB RAM — sufficient for desktop
IMAGE="Canonical:ubuntu-24_04-lts:server:latest"

# Use spot if SPOT=1, otherwise pay-as-you-go
if [ "${SPOT:-0}" = "1" ]; then
  SPOT_FLAGS="--priority Spot --eviction-policy Deallocate --max-price -1"
else
  SPOT_FLAGS=""
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLOUD_INIT="$SCRIPT_DIR/cloud-init-ubuntu-desktop.yml"

echo "=== openhort Ubuntu Desktop VM ==="
echo "  Resource Group: $RG"
echo "  VM Name:        $VM_NAME"
echo "  Region:         $REGION"
echo "  Size:           $SIZE"
echo ""

# Create resource group if needed
az group create --name "$RG" --location "$REGION" -o none 2>/dev/null || true

# Create VM with spot pricing
echo "Creating VM (spot instance)..."
VM_INFO=$(az vm create \
  --resource-group "$RG" \
  --name "$VM_NAME" \
  --image "$IMAGE" \
  --size "$SIZE" \
  ${SPOT_FLAGS} \
  --admin-username azureuser \
  --generate-ssh-keys \
  --custom-data "$CLOUD_INIT" \
  --public-ip-sku Standard \
  --nsg-rule SSH \
  --output json)

PUBLIC_IP=$(echo "$VM_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['publicIpAddress'])")

echo "VM created: $PUBLIC_IP"

# Open ports: RDP (3389) and openhort (8940)
echo "Opening ports..."
az vm open-port --resource-group "$RG" --name "$VM_NAME" --port 3389 --priority 1010 -o none &
az vm open-port --resource-group "$RG" --name "$VM_NAME" --port 8940 --priority 1020 -o none &
wait

# Set auto-shutdown at midnight UTC (cost control)
echo "Setting auto-shutdown..."
az vm auto-shutdown \
  --resource-group "$RG" \
  --name "$VM_NAME" \
  --time 0000 \
  -o none

echo ""
echo "=== VM provisioning started ==="
echo ""
echo "  cloud-init is installing packages + openhort (takes 5-10 minutes)"
echo ""
echo "  Monitor progress:"
echo "    ssh azureuser@$PUBLIC_IP 'tail -f /var/log/cloud-init-output.log'"
echo ""
echo "  When ready:"
echo "    RDP:      $PUBLIC_IP:3389"
echo "    User:     hortuser"
echo "    Password: OpenHort2026!"
echo "    openhort: http://$PUBLIC_IP:8940"
echo ""
echo "  Cleanup:"
echo "    az group delete --name $RG --yes --no-wait"
echo ""
