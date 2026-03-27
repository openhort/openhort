# Roadmap

## What Exists Today

- Claude Code CLI chat (local + container mode)
- OAuth token extraction from macOS Keychain
- Docker sandbox with resource limits (memory, CPU, disk)
- Stream-json parser with adaptive typewriter display
- Conversation continuity via `--resume`
- 21 unit tests, end-to-end integration tests
- Plain-text output (no raw markdown in terminal)

## Phase 1: Core Permissions

- Agent YAML parser and validator
- Tool permission filtering via `--allowedTools` / `--disallowedTools`
- File access control via Docker bind mounts
- Budget tracking from stream-json `result` events
- Command filtering with regex allow/deny + hardcoded deny list
- Audit logging to JSONL
- CLI: `poetry run hort agent start config.yaml`

## Phase 2: Multi-Provider + Source Policies

- OpenAI API provider (direct SDK)
- Anthropic API provider (direct SDK, without Claude Code CLI)
- llming-model provider
- Network restriction via Docker `--network` + DNS control
- MCP server scoping (filtered proxy)
- Access source detection (local, LAN, cloud, telegram, agent, scheduler, API)
- Source-scoped permission resolution
- RequestContext propagation

## Phase 3: Multi-Agent

- Message bus (in-process, asyncio queue-based)
- Agent-to-agent routing with permission checks
- Orchestrator pattern (one agent manages others)
- Pipeline pattern (chain of agents)
- Loop detection (correlation ID tracking + rate limits)

## Phase 4: Hardening

- gVisor runtime support (`--runtime=runsc`)
- Seccomp profiles for containers
- API key rotation / scoped tokens
- Dockerfile hash-based image versioning
- Write-only directory support (proxy pattern)
- Web UI for agent monitoring (openhort dashboard integration)

## Phase 5: Multi-Node

- Node discovery and tunnel establishment
- `cluster.yaml` + `node.yaml` parsers
- Agent deployment command (`hort agent deploy`)
- Cross-node message routing
- Heartbeat and health monitoring
- Cluster status aggregation
- NAT traversal via access server relay
- Worker-side budget enforcement
- API key distribution over tunnel
- mTLS option for high-security deployments

## TODOs

### Cross-Platform Credentials

- **Linux**: `libsecret` / `secret-tool` or file-based fallback
- **Windows**: Credential Manager via `dpapi` / `wincred`
- **Fallback**: `ANTHROPIC_API_KEY` env var (all platforms, CI)
- **Architecture**: `CredentialProvider` interface, auto-detected via `sys.platform`

### Token Refresh

- Check token expiry before each turn
- Re-extract from keychain if expired
- Use `refreshToken` for direct refresh (requires Anthropic OAuth endpoint knowledge)

### Container Image Versioning

- Hash Dockerfile → include in image tag
- Auto-rebuild when Dockerfile changes
- Pin Claude CLI version for reproducibility

### Testing Gaps

- Container integration tests (`@pytest.mark.docker`)
- Linux / Windows host testing
- Token expiry handling
- Network failure scenarios
- Multi-turn resume in container (automated)
- Resource limit enforcement (OOM, CPU throttle)
- CLI validation (`--memory` without `--container`)
