---
name: Use HTML not Markdown for Telegram
description: Telegram bot responses must use HTML formatting, not Markdown v1 which breaks on special characters.
type: feedback
---

Always use ConnectorResponse with html= field for Telegram, never markdown=. Use <b>bold</b> instead of *bold*.

**Why:** Telegram's Markdown v1 parser fails on em-dashes (—), forward slashes (/), and other common characters inside bold markers. The error is "Can't find end of the entity starting at byte offset X". The fallback to plain text works but loses formatting.

**How to apply:** When writing system commands or plugin responses for Telegram, use the html field: ConnectorResponse(text="plain", html="<b>formatted</b>"). The render_text() method on ConnectorBase picks HTML when the connector supports it.
