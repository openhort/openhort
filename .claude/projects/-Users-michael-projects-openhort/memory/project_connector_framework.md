---
name: Connector framework architecture
description: Telegram/Discord connector framework with ConnectorBase, CommandRegistry, system commands, and plugin commands.
type: project
---

The connector framework (hort/ext/connectors.py) provides a unified messaging interface. Key design decisions:

- System commands (help, status, link, etc.) are defined in the connector provider and CANNOT be overridden by plugins
- Plugin commands are registered via ConnectorMixin on any PluginBase subclass
- CommandRegistry.dispatch() returns None for system commands (connector handles them directly)
- ConnectorResponse has fallback chain: html → markdown → text, with automatic plain-text fallback on send failure
- delete_webhook(drop_pending_updates=True) called before polling to claim exclusive access
- Retry logic (5 attempts with backoff) for TelegramConflictError

**Why:** Unified interface for future connectors (Discord, WhatsApp). System command priority prevents plugins from hijacking critical commands.

**How to apply:** New connectors inherit ConnectorBase. Plugins add commands via ConnectorMixin.get_connector_commands(). The Telegram panel (panel.js) follows the same HortExtension pattern as LAN/Cloud panels.
