# Hook System for Extensions

Extensions should be able to react to system events and inject
behavior at specific points in the lifecycle.

## Event types

- `on_message_received` — before a connector message is processed
- `on_message_sent` — after a response is sent
- `on_power_used` — before/after a Power executes
- `on_session_start` — new chat session created
- `on_session_end` — session closed or reset
- `on_window_changed` — active window changed on desktop
- `on_screenshot_taken` — after a screenshot is captured

## Use cases

- Logging / audit trail (log all messages to a file)
- Rate limiting (reject if too many messages per minute)
- Content filtering (block sensitive content before sending)
- Auto-context (inject current time, location, calendar into prompt)
- Analytics (track tool usage patterns)

## Current state

We have `hort/signals/` (event bus, processors, triggers) which is
a lower-level system for internal events. Hooks would be the
extension-facing API on top of signals.

## Priority

Medium — the signals system exists, just needs an extension-friendly
wrapper. Most valuable for enterprise deployments (audit, compliance).
