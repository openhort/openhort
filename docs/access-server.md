# Access Server — Remote Proxy for openhort

The access server lets you reach your openhort instances from anywhere. It acts as a relay — your machines connect to it, and you access them through a single URL.

## Architecture

```
Phone/Tablet                    Azure                         Your Machine
     │                            │                                │
     │  HTTPS                     │                                │
     ├──────────────────────────→ │  Access Server                │
     │  login + session cookie    │  (openhort-access)            │
     │                            │                                │
     │  /proxy/{host_id}/...      │         WebSocket Tunnel       │
     ├──────────────────────────→ │ ←────────────────────────────→ │  Tunnel Client
     │                            │  (persistent connection)       │  (hort.access.tunnel_client)
     │  ← proxied response ─────→│                                │
     │                            │                                │  openhort (port 8940)
     │  /proxy/{host_id}/ws/...   │                                │
     ├──────────(WebSocket)─────→ │ ←────────(relayed)───────────→ │
     │                            │                                │
```

- **Access server** runs on Azure (or any cloud). Handles authentication, host registry, and proxying.
- **Tunnel client** runs on each machine alongside openhort. Maintains a persistent WebSocket to the access server.
- **All traffic** (HTTP + WebSocket) is relayed through the tunnel — no direct connection to the machine needed.

## Quick Start

### 1. Deploy the access server

```bash
# Set your registry (never hardcode — use env vars)
export HORT_REGISTRY=yourregistry.azurecr.io
export HORT_ADMIN_PASSWORD="YourSecurePassword123!"

# Build and push
docker buildx build --platform linux/amd64 \
    -t $HORT_REGISTRY/openhort/access-server:latest \
    -f hort/access/Dockerfile \
    --build-arg ADMIN_PASSWORD="$HORT_ADMIN_PASSWORD" \
    --push .

# Deploy to Azure (or use scripts/deploy-access.sh)
az appservice plan create --name openhort-plan --resource-group YOUR_RG --location germanywestcentral --sku B1 --is-linux
az webapp create --name openhort-access --resource-group YOUR_RG --plan openhort-plan \
    --container-image-name $HORT_REGISTRY/openhort/access-server:latest \
    --container-registry-user YOUR_ACR_USER --container-registry-password YOUR_ACR_PASS

# CRITICAL: Enable WebSockets on Azure App Service
az webapp config set --name openhort-access --resource-group YOUR_RG --web-sockets-enabled true

# Configure
az webapp config appsettings set --name openhort-access --resource-group YOUR_RG \
    --settings WEBSITES_PORT=8080 ACCESS_SESSION_SECRET="$(openssl rand -hex 32)"
```

### 2. Create a user and host

```bash
# Login (via curl or the web UI)
curl -c cookies.txt -X POST https://openhort-access.azurewebsites.net/api/access/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"YourSecurePassword123!"}'

# Create a host entry
curl -b cookies.txt -X POST https://openhort-access.azurewebsites.net/api/access/hosts \
    -H "Content-Type: application/json" \
    -d '{"display_name":"My Mac"}'
# Returns: {"host_id":"abc123","connection_key":"<KEY>","display_name":"My Mac"}
```

### 3. Connect your machine

On the machine running openhort:

```bash
# Start openhort locally (if not already running)
poetry run python run.py

# Connect to the access server
python -m hort.access.tunnel_client \
    --server=https://openhort-access.azurewebsites.net \
    --key="<CONNECTION_KEY>" \
    --local=http://localhost:8940
```

### 4. Access from anywhere

Open `https://openhort-access.azurewebsites.net` in a browser. Log in, see your machines, click one to open the full openhort viewer — proxied through Azure.

## Components

### `hort/access/auth.py` — Authentication

| Feature | Implementation |
|---|---|
| Password hashing | PBKDF2-SHA256, 100K iterations, 32-byte salt |
| Password validation | Minimum 8 chars, upper + lower + digit |
| Brute-force protection | Per-IP rate limiter: 10 attempts per 5 minutes |
| Timing attack prevention | Artificial delay on ALL auth attempts (success and failure), 0.5s base with exponential backoff up to 10s |
| Connection keys | 32-byte URL-safe tokens (`secrets.token_urlsafe(32)`) |

### `hort/access/store.py` — Storage

Two backends:

| Backend | Use case | Config |
|---|---|---|
| `FileStore` | Single instance, baked into container | `--store hort-access.json` |
| `MongoStore` | Multi-instance, dynamic users | `--store mongodb://...` |

The `FileStore` JSON file is created at Docker build time with the admin user baked in. For production with dynamic user management, use MongoDB (Azure CosmosDB with MongoDB API works).

### `hort/access/server.py` — Proxy Server

**Endpoints:**

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/` | GET | — | Login page (Quasar UI) |
| `/api/access/login` | POST | — | Authenticate, set session cookie |
| `/api/access/logout` | POST | session | Clear session |
| `/api/access/me` | GET | session | Current user info |
| `/api/access/hosts` | GET | session | List user's hosts (with online status) |
| `/api/access/hosts` | POST | session | Create a new host, returns connection key |
| `/api/access/tunnel` | WS | key | Host tunnel connection (query param `?key=`) |
| `/proxy/{host_id}/{path}` | ANY | session | Proxy HTTP requests to host |
| `/proxy/{host_id}/{path}` | WS | — | Proxy WebSocket connections to host |

**Tunnel protocol** (JSON over WebSocket):

```
Access Server → Host:
  {"type": "http_request", "req_id": "...", "method": "GET", "path": "/api/hash", "headers": {...}, "body": ""}
  {"type": "ws_open", "ws_id": "...", "path": "/ws/stream/..."}
  {"type": "ws_data", "ws_id": "...", "text": "..."} or {"binary": "<base64>"}
  {"type": "ws_close", "ws_id": "..."}

Host → Access Server:
  {"type": "http_response", "req_id": "...", "status": 200, "headers": {...}, "body": "..."}
  {"type": "ws_data", "ws_id": "...", "text": "..."} or {"binary": "<base64>"}
```

**Critical implementation detail:** The tunnel WebSocket uses a **send queue** (`asyncio.Queue`) instead of direct `ws.send_text()`. Starlette's WebSocket does not support concurrent send and receive from different coroutines — the reader and writer must be separate tasks sharing the WS through the queue.

### `hort/access/tunnel_client.py` — Host Connector

Runs on each openhort machine. Maintains a persistent WebSocket connection to the access server. Relays:
- **HTTP requests** → makes local HTTP requests via `httpx` and sends responses back
- **WebSocket connections** → opens local WebSocket connections via `websockets` and bridges data

Auto-reconnects on disconnect (5 second backoff).

### `hort/access/Dockerfile`

```dockerfile
FROM --platform=linux/amd64 python:3.13-slim
# ... installs deps, bakes admin user at build time
```

**IMPORTANT:** `--platform=linux/amd64` is required because Azure App Service runs x86_64. Without this, building on an ARM Mac produces an incompatible image.

The admin password is passed via `--build-arg ADMIN_PASSWORD=...` — never hardcoded in the Dockerfile or committed to git.

## Azure Deployment Checklist

| Step | Command | Notes |
|---|---|---|
| ACR login | `az acr login --name YOUR_ACR` | Required before push |
| Build for amd64 | `docker buildx build --platform linux/amd64 ...` | ARM Mac builds won't work on Azure |
| Push to ACR | `docker push YOUR_ACR/openhort/access-server:latest` | |
| Create App Service plan | `az appservice plan create --sku B1 --is-linux` | B1 is cheapest (~$13/month) |
| Create Web App | `az webapp create --container-image-name ... --container-registry-user ... --container-registry-password ...` | Pass ACR credentials at creation time |
| **Enable WebSockets** | `az webapp config set --web-sockets-enabled true` | **CRITICAL — without this, tunnel WS connects but messages don't relay** |
| Set port | `az webapp config appsettings set --settings WEBSITES_PORT=8080` | Container listens on 8080 |
| Set session secret | `az webapp config appsettings set --settings ACCESS_SESSION_SECRET="$(openssl rand -hex 32)"` | Persistent across restarts |

### Common Issues

| Symptom | Cause | Fix |
|---|---|---|
| `ImagePullUnauthorizedFailure` | ACR credentials not configured | Pass `--container-registry-user` and `--container-registry-password` when creating the webapp |
| Login returns 500 | Password hash iterations mismatch (old image had 600K, new code has 100K) | Rebuild the image — the admin user hash is baked in at build time |
| Tunnel connects but proxy times out | WebSockets not enabled on Azure | `az webapp config set --web-sockets-enabled true` |
| Tunnel connects but proxy times out | Local openhort server not running | Start it: `poetry run python run.py` |
| `Internal Server Error` on login | Empty `ACCESS_SESSION_SECRET` env var | The code uses `or secrets.token_hex(32)` fallback — ensure the env var is either unset or has a value |
| Image runs on Mac but not Azure | Wrong platform (ARM vs AMD64) | Use `--platform=linux/amd64` in Dockerfile or `docker buildx build --platform linux/amd64` |

## Security Model

```
User → (HTTPS + session cookie) → Access Server → (WS tunnel + connection key) → Host
```

- **Users** authenticate with username + password (PBKDF2 hashed)
- **Hosts** authenticate with connection keys (one-time generated, stored in the host's config)
- **Sessions** use signed cookies (Starlette SessionMiddleware with HMAC)
- **Brute force** prevented by per-IP rate limiting + artificial delay on all auth attempts
- **No credentials in git** — admin password via build arg, ACR credentials via env vars, session secret via app settings

## Local Development

```bash
# Create test user
python -m hort.access.server --setup-user admin "TestPass123" --store /tmp/test.json

# Create test host
python -m hort.access.server --setup-host admin "My Mac" --store /tmp/test.json

# Start access server locally
python -m hort.access.server --port 8400 --store /tmp/test.json

# Connect tunnel
python -m hort.access.tunnel_client --server=http://localhost:8400 --key="<KEY>" --local=http://localhost:8940
```

## Scripts

`scripts/deploy-access.sh` — automated build + push + deploy. Configure via environment variables:

| Variable | Default | Description |
|---|---|---|
| `HORT_REGISTRY` | `your-registry.azurecr.io` | ACR hostname |
| `HORT_ADMIN_PASSWORD` | `ChangeMe123!` | Initial admin password |
| `HORT_RG` | `your-resource-group` | Azure resource group |
| `HORT_APP_NAME` | `openhort-access` | Azure Web App name |
| `HORT_LOCATION` | `germanywestcentral` | Azure region |
