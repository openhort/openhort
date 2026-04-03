# Connector Ecosystem

Currently only Telegram. The connector framework (ConnectorBase,
ConnectorMixin, CommandRegistry) is already connector-agnostic.
Need more connectors.

## Candidates

- **WhatsApp Business API** — large user base, similar to Telegram
- **Microsoft Teams** — enterprise, webhook-based
- **Discord** — developer community
- **Slack** — enterprise, mature bot API
- **Web Chat** — embedded in the openhort UI itself
- **Matrix** — open protocol, self-hosted
- **Signal** — privacy-focused (limited bot API)

## Web Chat (highest priority)

A web-based chat panel in the openhort UI. Uses the same chat backend
as Telegram but renders in the browser. Would show:
- Full ChatProgressEvent stream (tool names, thinking status)
- Inline images from screenshots
- Clickable window buttons
- Session management

Could be a Vue component in index.html or a separate panel extension.

## Shared infrastructure

All connectors share:
- ChatBackendManager (chat routing)
- CommandRegistry (plugin commands)
- ConnectorResponse (multi-format responses)
- SOUL.md prompt system

Adding a new connector = implement ConnectorBase + platform-specific
message handling. The rest is automatic.

## Priority

Web Chat: high (already have the UI framework).
WhatsApp/Teams: medium (needs auth framework first).
Others: low.
