# Quick Start

Get a sandboxed AI agent running in under 5 minutes.

!!! note "Prerequisites"
    - Docker Desktop running
    - Claude Code CLI installed (`npm install -g @anthropic-ai/claude-code`)
    - Logged in to Claude Code (`claude auth login`)
    - openhort repo cloned with dependencies (`poetry install`)

## 1. Start a Simple Chat

No config file needed — just chat:

```bash
# Local mode (runs on your machine)
poetry run python -m subprojects.claude_chat

# Container mode (runs inside Docker sandbox)
poetry run python -m subprojects.claude_chat --container
```

Type messages, get responses. Type `exit` to quit.

## 2. Pick a Model

```bash
poetry run python -m subprojects.claude_chat --model sonnet
poetry run python -m subprojects.claude_chat --model haiku
```

## 3. Add Resource Limits

Container mode supports memory and CPU limits:

```bash
poetry run python -m subprojects.claude_chat -c --memory 512m --cpus 2
```

!!! warning "Resource limit behavior"
    The agent is **OOM-killed** if it exceeds the memory limit.
    CPU time is **throttled** (not killed) beyond the CPU limit.

## 4. Use a Custom System Prompt

```bash
poetry run python -m subprojects.claude_chat -c \
  --system "You are a Python tutor. Explain concepts simply."
```

## 5. Create an Agent Config (YAML)

For repeatable setups, create a YAML file:

```yaml
# agents/my-agent.yaml
name: my-agent
model:
  provider: claude-code
  api_key_source: keychain
budget:
  max_cost_usd: 1.00
  max_turns: 20
permissions:
  tools:
    allow: [Read, Glob, Grep]
```

```bash
poetry run hort agent start agents/my-agent.yaml
```

## What's Happening Under the Hood

1. Your Claude OAuth token is read from the macOS Keychain
2. A Docker container is started with `claude-chat-sandbox` image
3. The token is passed as `ANTHROPIC_API_KEY` (never written to disk)
4. Each message runs `claude -p` inside the container via `docker exec`
5. Responses are streamed back through the typewriter display engine
6. Conversation context is maintained via `--resume` across turns

See [Architecture](../developer/internals/architecture.md) for the full picture.
