#!/usr/bin/env python3
"""Memory watchdog — kills runaway processes and restarts the server.

Monitors all child Python processes. If any single process or the total
exceeds the threshold, it kills the offender, logs the incident, and
restarts the hort dev server.

Usage:
    # Run alongside dev server (default 20 GB threshold)
    python tools/memory-watchdog/watchdog.py

    # Custom threshold
    python tools/memory-watchdog/watchdog.py --threshold 10

    # Just monitor, don't kill
    python tools/memory-watchdog/watchdog.py --dry-run

    # Watch specific process names
    python tools/memory-watchdog/watchdog.py --watch uvicorn,pytest

Incidents are logged to logs/memory-incidents.jsonl (one JSON object per line).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
INCIDENT_LOG = LOG_DIR / "memory-incidents.jsonl"
SERVER_CMD = ["poetry", "run", "python", "run.py"]


def get_python_processes(watch_names: list[str] | None = None) -> list[dict]:
    """Get all Python processes with memory info."""
    try:
        result = subprocess.run(
            ["ps", "axo", "pid,rss,command"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return []

    processes = []
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid_str, rss_str, command = parts
        try:
            pid = int(pid_str)
            rss_kb = int(rss_str)
        except ValueError:
            continue

        if pid == os.getpid():
            continue

        # Filter to Python/node processes related to openhort
        is_relevant = (
            "python" in command.lower()
            or "uvicorn" in command.lower()
            or "pytest" in command.lower()
            or "node" in command.lower()
        )
        if not is_relevant:
            continue

        # If watch_names specified, only track those
        if watch_names:
            if not any(name in command.lower() for name in watch_names):
                continue

        rss_gb = rss_kb / (1024 * 1024)
        processes.append({
            "pid": pid,
            "rss_kb": rss_kb,
            "rss_gb": round(rss_gb, 2),
            "command": command[:200],
        })

    return processes


def log_incident(incident: dict) -> None:
    """Append incident to the JSONL log file."""
    LOG_DIR.mkdir(exist_ok=True)
    with open(INCIDENT_LOG, "a") as f:
        f.write(json.dumps(incident) + "\n")


def kill_process(pid: int, command: str) -> bool:
    """Kill a process. SIGTERM first, SIGKILL after 3s."""
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(3)
        # Check if still alive
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
            print(f"  SIGKILL sent to {pid}")
        except ProcessLookupError:
            pass
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        print(f"  Permission denied killing {pid}: {command[:80]}")
        return False


def restart_server() -> None:
    """Restart the hort dev server."""
    print("\n--- Restarting hort server ---")

    # Kill any existing uvicorn
    try:
        result = subprocess.run(
            ["pgrep", "-f", "uvicorn hort.app"],
            capture_output=True, text=True,
        )
        for pid_str in result.stdout.strip().splitlines():
            try:
                os.kill(int(pid_str), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
    except Exception:
        pass

    time.sleep(2)

    # Start server in background
    subprocess.Popen(
        SERVER_CMD,
        cwd=str(PROJECT_ROOT),
        stdout=open(LOG_DIR / "server-restart.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"  Server restarted (log: logs/server-restart.log)")


def format_size(gb: float) -> str:
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{gb * 1024:.0f} MB"


def main() -> None:
    parser = argparse.ArgumentParser(description="Memory watchdog for openhort")
    parser.add_argument("--threshold", type=float, default=20.0,
                        help="Kill threshold in GB (default: 20)")
    parser.add_argument("--total-threshold", type=float, default=30.0,
                        help="Total memory threshold in GB (default: 30)")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Check interval in seconds (default: 5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Monitor only, don't kill")
    parser.add_argument("--watch", type=str, default="",
                        help="Comma-separated process names to watch")
    parser.add_argument("--restart", action="store_true", default=True,
                        help="Restart hort server after killing (default: true)")
    parser.add_argument("--no-restart", action="store_false", dest="restart")
    args = parser.parse_args()

    watch_names = [n.strip().lower() for n in args.watch.split(",") if n.strip()] or None
    threshold_kb = int(args.threshold * 1024 * 1024)
    total_threshold_kb = int(args.total_threshold * 1024 * 1024)

    print(f"Memory watchdog started")
    print(f"  Per-process threshold: {args.threshold} GB")
    print(f"  Total threshold:       {args.total_threshold} GB")
    print(f"  Check interval:        {args.interval}s")
    print(f"  Dry run:               {args.dry_run}")
    print(f"  Watch:                 {watch_names or 'all python/node'}")
    print(f"  Incident log:          {INCIDENT_LOG}")
    print()

    server_killed = False

    try:
        while True:
            processes = get_python_processes(watch_names)
            if not processes:
                time.sleep(args.interval)
                continue

            total_kb = sum(p["rss_kb"] for p in processes)
            total_gb = total_kb / (1024 * 1024)

            # Find offenders
            offenders = [p for p in processes if p["rss_kb"] > threshold_kb]
            total_exceeded = total_kb > total_threshold_kb

            if offenders or total_exceeded:
                ts = datetime.now(timezone.utc).isoformat()
                print(f"\n[{ts}] MEMORY ALERT")
                print(f"  Total: {format_size(total_gb)} across {len(processes)} processes")

                if total_exceeded and not offenders:
                    # No single offender but total is too high — kill the largest
                    offenders = sorted(processes, key=lambda p: p["rss_kb"], reverse=True)[:1]

                for proc in offenders:
                    print(f"  OFFENDER: PID {proc['pid']} using {format_size(proc['rss_gb'])}")
                    print(f"    {proc['command'][:120]}")

                    incident = {
                        "timestamp": ts,
                        "pid": proc["pid"],
                        "rss_gb": proc["rss_gb"],
                        "command": proc["command"],
                        "threshold_gb": args.threshold,
                        "total_gb": round(total_gb, 2),
                        "action": "dry_run" if args.dry_run else "killed",
                        "all_processes": processes,
                    }

                    if not args.dry_run:
                        killed = kill_process(proc["pid"], proc["command"])
                        incident["killed"] = killed
                        if "uvicorn" in proc["command"].lower() or "hort" in proc["command"].lower():
                            server_killed = True

                    log_incident(incident)
                    print(f"  Incident logged to {INCIDENT_LOG}")

                # Restart if server was killed
                if server_killed and args.restart and not args.dry_run:
                    time.sleep(3)
                    restart_server()
                    server_killed = False

            else:
                # Periodic status (every 12th check = ~1 min at 5s interval)
                if int(time.time()) % 60 < args.interval:
                    top = sorted(processes, key=lambda p: p["rss_kb"], reverse=True)[:3]
                    status = ", ".join(f"PID {p['pid']}={format_size(p['rss_gb'])}" for p in top)
                    print(f"  [OK] {format_size(total_gb)} total | top: {status}")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nWatchdog stopped.")


if __name__ == "__main__":
    main()
