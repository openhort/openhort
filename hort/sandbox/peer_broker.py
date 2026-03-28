"""Peer communication MCP server — stdio JSON-RPC for inter-container messaging.

Each broker instance serves one peer. Two instances share state via a
directory-based mailbox on the host filesystem:

    /tmp/peer-collab-{session}/
        A_inbox/           ← messages for peer A (written by B's broker)
        B_inbox/           ← messages for peer B (written by A's broker)
        status_A.json      ← A's current status
        status_B.json      ← B's current status

Usage::

    python -m hort.sandbox.peer_broker --peer-id A --session-dir /tmp/peer-collab-xxx
    python -m hort.sandbox.peer_broker --peer-id B --session-dir /tmp/peer-collab-xxx

Implements MCP stdio protocol (Content-Length framed JSON-RPC).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


def _other_peer(peer_id: str) -> str:
    return "B" if peer_id == "A" else "A"


def _inbox_dir(session_dir: Path, peer_id: str) -> Path:
    d = session_dir / f"{peer_id}_inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _status_path(session_dir: Path, peer_id: str) -> Path:
    return session_dir / f"status_{peer_id}.json"


def _read_status(session_dir: Path, peer_id: str) -> dict:
    path = _status_path(session_dir, peer_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"status": "idle", "description": "", "peer_id": peer_id}


def _write_status(session_dir: Path, peer_id: str, status: str, description: str) -> None:
    path = _status_path(session_dir, peer_id)
    data = {"status": status, "description": description, "peer_id": peer_id,
            "updated_at": datetime.now(timezone.utc).isoformat()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.rename(path)


def _send_message(session_dir: Path, from_peer: str, message: str) -> dict:
    to_peer = _other_peer(from_peer)
    inbox = _inbox_dir(session_dir, to_peer)
    ts = datetime.now(timezone.utc).isoformat()
    msg = {
        "from_peer": from_peer,
        "to_peer": to_peer,
        "content": message,
        "timestamp": ts,
    }
    # Atomic write: tempfile in same dir → rename
    fd, tmp = tempfile.mkstemp(dir=str(inbox), suffix=".tmp")
    os.write(fd, json.dumps(msg).encode())
    os.close(fd)
    final = inbox / f"{int(time.time() * 1000)}_{from_peer}.json"
    os.rename(tmp, str(final))
    return msg


def _read_messages(session_dir: Path, peer_id: str, mark_read: bool = True) -> list[dict]:
    inbox = _inbox_dir(session_dir, peer_id)
    messages = []
    files = sorted(inbox.glob("*.json"))
    for f in files:
        try:
            msg = json.loads(f.read_text())
            messages.append(msg)
            if mark_read:
                f.rename(f.with_suffix(".read"))
        except (json.JSONDecodeError, OSError):
            continue
    return messages


def _wait_for_message(session_dir: Path, peer_id: str, timeout: float) -> list[dict]:
    inbox = _inbox_dir(session_dir, peer_id)
    deadline = time.time() + timeout
    while time.time() < deadline:
        files = sorted(inbox.glob("*.json"))
        if files:
            return _read_messages(session_dir, peer_id, mark_read=True)
        time.sleep(0.5)
    return []


# ── MCP protocol ──────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "peer_send",
        "description": "Send a message to your peer instance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message to send"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "peer_read",
        "description": "Read unread messages from your peer. Returns a list of messages.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "peer_status",
        "description": "Check your peer's current status (idle/busy/done) and what they're working on.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "peer_wait",
        "description": "Wait for a message from your peer. Blocks until a message arrives or timeout.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Max seconds to wait (default 30)",
                    "default": 30,
                },
            },
        },
    },
    {
        "name": "peer_done",
        "description": "Signal that you have completed your work. Include a summary of what you did.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Summary of completed work"},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "peer_set_status",
        "description": "Update your status so your peer can see what you're working on.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["idle", "busy"],
                    "description": "Your current status",
                },
                "description": {
                    "type": "string",
                    "description": "What you are currently doing",
                },
            },
            "required": ["status", "description"],
        },
    },
]


def _handle_tool_call(
    tool_name: str, args: dict, peer_id: str, session_dir: Path,
) -> dict:
    """Execute a tool and return the MCP result content."""
    if tool_name == "peer_send":
        msg = _send_message(session_dir, peer_id, args["message"])
        return {"content": [{"type": "text", "text": f"Message sent to peer {msg['to_peer']} at {msg['timestamp']}"}]}

    if tool_name == "peer_read":
        messages = _read_messages(session_dir, peer_id)
        if not messages:
            return {"content": [{"type": "text", "text": "No unread messages from your peer."}]}
        lines = []
        for m in messages:
            lines.append(f"[{m['timestamp']}] {m['from_peer']}: {m['content']}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    if tool_name == "peer_status":
        other = _other_peer(peer_id)
        status = _read_status(session_dir, other)
        return {"content": [{"type": "text", "text": json.dumps(status, indent=2)}]}

    if tool_name == "peer_wait":
        timeout = args.get("timeout_seconds", 30)
        messages = _wait_for_message(session_dir, peer_id, timeout)
        if not messages:
            return {"content": [{"type": "text", "text": f"No messages received within {timeout}s timeout."}]}
        lines = []
        for m in messages:
            lines.append(f"[{m['timestamp']}] {m['from_peer']}: {m['content']}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    if tool_name == "peer_done":
        _write_status(session_dir, peer_id, "done", args["summary"])
        # Also send the summary as a message to the peer
        _send_message(session_dir, peer_id, f"[DONE] {args['summary']}")
        return {"content": [{"type": "text", "text": "Status set to done. Your peer has been notified."}]}

    if tool_name == "peer_set_status":
        _write_status(session_dir, peer_id, args["status"], args["description"])
        return {"content": [{"type": "text", "text": f"Status updated: {args['status']} — {args['description']}"}]}

    return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}


def _handle_jsonrpc(msg: dict, peer_id: str, session_dir: Path) -> dict | None:
    """Handle one JSON-RPC message, return response or None for notifications."""
    method = msg.get("method", "")
    msg_id = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": f"peer-broker-{peer_id}", "version": "1.0.0"},
            },
        }

    if method == "notifications/initialized":
        return None  # notification, no response

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        result = _handle_tool_call(tool_name, tool_args, peer_id, session_dir)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result,
        }

    # Unknown method
    if msg_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return None


def _read_message(stream) -> dict | None:
    """Read one Content-Length framed JSON-RPC message from stdin."""
    content_length = None
    while True:
        line = stream.readline()
        if not line:
            return None
        text = line.strip()
        if not text:
            if content_length is not None:
                break
            continue
        if text.lower().startswith("content-length:"):
            content_length = int(text.split(":", 1)[1].strip())

    if content_length is None:
        return None

    body = stream.read(content_length)
    return json.loads(body)


def _write_message(msg: dict, stream) -> None:
    """Write one Content-Length framed JSON-RPC message to stdout."""
    body = json.dumps(msg)
    header = f"Content-Length: {len(body)}\r\n\r\n"
    stream.write(header + body)
    stream.flush()


def run_broker(peer_id: str, session_dir: str) -> None:
    """Main loop — read JSON-RPC from stdin, respond on stdout."""
    session_path = Path(session_dir)
    session_path.mkdir(parents=True, exist_ok=True)

    # Initialize own inbox and status
    _inbox_dir(session_path, peer_id)
    _write_status(session_path, peer_id, "idle", "")

    while True:
        msg = _read_message(sys.stdin)
        if msg is None:
            break

        response = _handle_jsonrpc(msg, peer_id, session_path)
        if response is not None:
            _write_message(response, sys.stdout)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Peer broker MCP server")
    parser.add_argument("--peer-id", required=True, choices=["A", "B"])
    parser.add_argument("--session-dir", required=True)
    args = parser.parse_args()
    run_broker(args.peer_id, args.session_dir)


if __name__ == "__main__":
    main()
