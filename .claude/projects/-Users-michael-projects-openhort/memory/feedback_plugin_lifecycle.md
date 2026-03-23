---
name: Plugin lifecycle must be clean
description: Plugins must load in startup event, not at import time. Single instance only. Clean shutdown required.
type: feedback
---

Never load or start plugins at module import time or in create_app(). Plugin loading, scheduler start, and connector start must happen exclusively in the FastAPI startup event. Plugin stop (connectors, schedulers) must happen in the shutdown event.

**Why:** With uvicorn --reload, create_app() runs multiple times per module import. Loading plugins there caused duplicate Telegram bot instances competing for the same token (TelegramConflictError), stale worker processes surviving kills, and background tasks silently dying on reload.

**How to apply:** Any new plugin lifecycle code (loading, starting, stopping) goes in start_plugins() / stop_plugins() which are called from on_event("startup") / on_event("shutdown"). Never use asyncio.create_task for deferred plugin startup — run it synchronously in the startup event.
