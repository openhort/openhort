# Error Handling & Information Disclosure

## Rule: No Internal Errors to Users

**Internal errors, stack traces, command strings, container IDs, file paths, or any system-level detail MUST NEVER be shown to end users — through any channel.**

This applies to:

- Telegram bot responses
- Web chat (llming-wire)
- Cloud proxy error pages
- P2P viewer error messages
- API error responses to unauthenticated clients
- Status bar notifications forwarded to remote devices

### What users see

| Situation | User sees | Never shows |
|---|---|---|
| Backend error | "Something went wrong. Try again." | Stack traces, docker commands, container IDs |
| Auth failure | "Not authorized" | Token values, key paths, Keychain details |
| Container crash | "Service temporarily unavailable" | Exit codes, process names, file paths |
| Network timeout | "Connection timed out" | IP addresses, port numbers, tunnel details |
| Plugin failure | "Feature unavailable" | Module names, import errors, config paths |

### Implementation

Every connector and response layer MUST catch exceptions and replace them with safe user-facing messages before sending:

```python
# WRONG — leaks internals
except Exception as e:
    await send_response(str(e))

# RIGHT — safe generic message
except Exception as e:
    logger.exception("Chat backend error")
    await send_response("Something went wrong. Try again.")
```

### Logging

Full error details go to:

- `logs/openhort.log` (rotating, local only)
- Debug API (`/api/llming/debug/`) — requires API key, localhost only
- Status bar (local macOS only, never forwarded remotely)

## Container Lifecycle

### Always Running

Sandbox containers start when first needed and stay running until openhort shuts down. They are NOT stopped between chat messages — session state, MCP config, and auth credentials persist in the container.

### Shutdown Behavior

| Event | Container action |
|---|---|
| Server hot-reload (`--reload`) | Containers keep running (new worker reuses existing containers) |
| `hort stop` (CLI) | All sandbox containers stopped and removed |
| Status bar → Quit | All sandbox containers stopped and removed |
| System reboot / Docker restart | Containers stopped by Docker (no cleanup needed) |
| Crash / kill -9 | Containers orphaned — cleaned up on next `hort start` |

### Startup Cleanup

On `hort start`, scan for orphaned containers (`ohsb-*` prefix) and remove them. This handles the crash case where the previous server didn't get to clean up.

### Implementation

```python
# In on_event("startup"):
#   - Scan docker ps -a --filter name=ohsb- for orphans
#   - Remove stopped orphans
#   - Reuse running ones if still valid

# In on_event("shutdown"):
#   - Stop all containers in _container_sessions
#   - Remove volumes
```

### No Eager Container Creation

Containers are created on first chat message from a user, not at server startup. This avoids wasting resources for users who never chat.
