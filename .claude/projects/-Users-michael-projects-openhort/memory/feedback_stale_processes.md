---
name: Always check for stale Python subprocesses
description: When debugging server issues, check for orphaned Python processes (multiprocessing spawn children, old test servers) holding ports.
type: feedback
---

Use `lsof -ti :8940` and `ps -p PID -o pid,lstart,command` to identify stale processes. pgrep -f "uvicorn" misses multiprocessing spawn children. Old test servers from subprojects/ can hold the Telegram bot token.

**Why:** A stale `subprojects.telegram_bot.test_server` process ran for hours competing for the bot token. Multiple `kill -9` attempts missed orphaned multiprocessing workers. The "new" server was actually the old one serving stale code.

**How to apply:** Before debugging "code changes not taking effect" or Telegram conflicts, always: (1) lsof -ti :8940 to find ALL processes on the port, (2) check process start times with ps -p PID -o lstart, (3) kill stale workers individually, not just parent processes.
