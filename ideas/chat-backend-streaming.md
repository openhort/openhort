# Chat Backend Streaming & Rich Responses

The chat backend currently returns plain text. It should support
richer response types and real-time streaming.

## Streaming to connectors

Instead of waiting for the full response, stream text chunks
to the connector as they arrive. Telegram can edit the last
message in-place (like ChatGPT does). Web chat can show a
typing animation with live text.

## Rich responses

The chat backend should detect when Claude's response contains:
- **Images** (from screenshot tool) → send as photo, not text
- **Code blocks** → format appropriately for the connector
- **Lists / tables** → use connector-native formatting
- **Multiple tool results** → summarize, don't dump raw data

## Implementation

Claude Code CLI with `--include-partial-messages` gives streaming
deltas. The chat backend could yield these to the connector
instead of collecting them all.

For Telegram: use `editMessageText` to update the last message
in-place as chunks arrive. Delete the "Working..." message and
replace with the real response.

## Priority

Medium — the current "wait then send" works but feels slow.
Streaming would dramatically improve perceived responsiveness.
