#!/bin/bash
set -e

# Configuration
REGISTRY=${HORT_REGISTRY:-"yourregistry.azurecr.io"}
RESOURCE_GROUP=${HORT_RG:-"your-resource-group"}
APP_NAME=${HORT_APP_NAME:-"openhort-access"}

# Build version: git short hash + timestamp
BUILD_VERSION="$(git rev-parse --short HEAD)-$(date +%Y%m%d%H%M%S)"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
IMAGE_TAG="v${BUILD_VERSION}"
FULL_IMAGE="${REGISTRY}/openhort/access-server:${IMAGE_TAG}"

echo "Building ${FULL_IMAGE}..."
echo "  Version: ${BUILD_VERSION}"
echo "  Time:    ${BUILD_TIME}"

cd "$(dirname "$0")/.."

# Login to ACR
az acr login --name "${REGISTRY%%.*}"

# Build + push via docker compose
export BUILD_VERSION BUILD_TIME IMAGE_TAG
docker compose -f hort/access/docker-compose.yml build
docker compose -f hort/access/docker-compose.yml push

# Deploy to Azure
echo "Deploying to ${APP_NAME}..."
az webapp config container set \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --container-image-name "${FULL_IMAGE}" 2>&1 | tail -3

az webapp stop --name "${APP_NAME}" --resource-group "${RESOURCE_GROUP}" 2>/dev/null
sleep 5
az webapp start --name "${APP_NAME}" --resource-group "${RESOURCE_GROUP}" 2>/dev/null

echo ""
echo "Deployed: ${FULL_IMAGE}"
echo "Verify:   curl https://${APP_NAME}.azurewebsites.net/cfversion"
