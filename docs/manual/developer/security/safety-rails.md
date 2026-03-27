# Safety Rails

These rules are hardcoded in the framework. They cannot be
disabled or overridden by YAML configuration.

## Universal Rails

1. **No API keys in YAML** — the parser rejects config files
   containing literal API keys.

2. **Destructive commands always blocked** — `rm -rf`, `mkfs`,
   `dd of=/dev/`, `sudo`, `su`, `reboot`, `shutdown` are denied
   regardless of command filter config.

3. **Cloud metadata always blocked** — `169.254.169.254` is
   denied in all network configurations.

4. **Audit logging cannot be disabled** — every tool call,
   command, message, and permission denial is logged.

5. **Budget tracking cannot be disabled** — limits can be set
   high, but tracking always runs.

6. **Container user is always non-root** — the `claude` user
   (UID 1000) has no sudo access.

7. **Dangerous procfs paths never mounted** — `/proc/kcore`,
   `/proc/sysrq-trigger`, and similar are not accessible.

## Multi-Node Rails

8. **Workers never expose controller endpoints** — a worker
   cannot be remotely promoted to a controller.

9. **`accept_from` enforced on every command** — workers only
   accept commands from listed node IDs.

10. **Worker budget caps cannot be exceeded** — even if the
    controller sends a higher budget, the worker's local
    `max_budget_usd_per_session` takes precedence.

11. **API keys never written to disk on workers** — keys exist
    only in the container's environment variable.

12. **Connection keys never logged** — even in audit logs,
    connection keys are redacted.

13. **Roles cannot be changed via tunnel** — a node's role
    must be configured locally in `node.yaml`.

14. **No direct worker-to-worker messaging** — all cross-node
    messages route through the controller's message bus.

## Access Source Rails

15. **Container requests cannot impersonate local/LAN** —
    requests from containers are always tagged `agent:<name>`.

16. **Unlisted sources get DENY_ALL** — if a source type is
    not in the `sources` config, it has zero access.

17. **Source overrides can only restrict** — a source policy
    intersects with base permissions, never expands them.
