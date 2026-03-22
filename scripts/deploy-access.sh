#!/bin/bash
set -e

# Configuration — set these via env vars before running
REGISTRY=${HORT_REGISTRY:-"your-registry.azurecr.io"}
IMAGE_NAME=${HORT_IMAGE:-"openhort/access-server"}
IMAGE_TAG=${HORT_TAG:-"latest"}
ADMIN_PASSWORD=${HORT_ADMIN_PASSWORD:-"ChangeMe123!"}
RESOURCE_GROUP=${HORT_RG:-"your-resource-group"}
APP_NAME=${HORT_APP_NAME:-"openhort-access"}
LOCATION=${HORT_LOCATION:-"germanywestcentral"}

FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "Building ${FULL_IMAGE}..."
cd "$(dirname "$0")/.."
docker build \
    -t "${FULL_IMAGE}" \
    -f hort/access/Dockerfile \
    --build-arg ADMIN_PASSWORD="${ADMIN_PASSWORD}" \
    .

echo "Pushing to ${REGISTRY}..."
az acr login --name "${REGISTRY%%.*}"
docker push "${FULL_IMAGE}"

echo "Deploying to Azure Web App: ${APP_NAME}..."
# Create app service plan if not exists
az appservice plan show --name "${APP_NAME}-plan" --resource-group "${RESOURCE_GROUP}" 2>/dev/null || \
    az appservice plan create \
        --name "${APP_NAME}-plan" \
        --resource-group "${RESOURCE_GROUP}" \
        --location "${LOCATION}" \
        --sku B1 \
        --is-linux

# Create web app if not exists
az webapp show --name "${APP_NAME}" --resource-group "${RESOURCE_GROUP}" 2>/dev/null || \
    az webapp create \
        --name "${APP_NAME}" \
        --resource-group "${RESOURCE_GROUP}" \
        --plan "${APP_NAME}-plan" \
        --deployment-container-image-name "${FULL_IMAGE}"

# Configure
az webapp config appsettings set \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --settings \
        WEBSITES_PORT=8080 \
        ACCESS_SESSION_SECRET="$(openssl rand -hex 32)"

# Update container image
az webapp config container set \
    --name "${APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --container-image-name "${FULL_IMAGE}" \
    --container-registry-url "https://${REGISTRY}"

echo ""
echo "Deployed! Access at: https://${APP_NAME}.azurewebsites.net"
echo "Login with: admin / <your password>"
