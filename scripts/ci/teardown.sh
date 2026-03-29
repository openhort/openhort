#!/bin/bash
# Tear down all openhort test VMs in Azure.
#
# Usage: bash scripts/ci/teardown.sh [resource-group]
#
# Deletes the entire resource group (VMs, disks, NICs, IPs — everything).

set -e

RG="${1:-openhort-test-rg}"

echo "=== Tearing down openhort test environment ==="
echo "  Resource Group: $RG"
echo ""

# Check if the resource group exists
if ! az group show --name "$RG" -o none 2>/dev/null; then
    echo "  Resource group '$RG' does not exist. Nothing to tear down."
    exit 0
fi

# List what's in it
echo "  Resources:"
az resource list --resource-group "$RG" --query "[].{name:name, type:type}" -o table 2>/dev/null || true
echo ""

# Delete (async — returns immediately, deletion continues in background)
az group delete --name "$RG" --yes --no-wait
echo "  Deletion started (runs in background)."
echo "  Monitor: az group show --name $RG -o table"
echo ""
