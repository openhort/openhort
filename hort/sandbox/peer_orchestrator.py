"""Peer orchestrator — manages two Claude Code instances collaborating.

Runs two Claude Code CLI sessions in separate containers, delivering
cross-peer messages between turns via the PeerBroker MCP server.

Usage::

    python -m hort.sandbox.peer_orchestrator \\
        --task-a "Write a Python function that sorts a list" \\
        --task-b "Write tests for a sorting function your peer is building"

Architecture::

    PeerOrchestrator
    ├── Session A (container)  ←→  PeerBroker MCP (peer_id=A)
    ├── Session B (container)  ←→  PeerBroker MCP (peer_id=B)
    ├── Shared volume (/shared) mounted in both containers
    └── Turn loop: dispatch prompts, deliver cross-peer messages
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from hort.llm.base import LLMUsage
from hort.sandbox.mcp import McpServerConfig, build_claude_mcp_json
from hort.sandbox.mcp_proxy import ProxyManager
from hort.sandbox.peer_broker import _read_messages, _read_status, _write_status

# Path to the broker script
_BROKER_SCRIPT = str(Path(__file__).resolve().parent / "peer_broker.py")

_SYSTEM_PROMPT_TEMPLATE = """\
You are Peer {peer_id} in a collaborative coding session with another Claude \
Code instance (Peer {other_id}) running in a separate container.

YOUR TASK: {task}
YOUR PEER'S TASK: {peer_task}

SHARED FILESYSTEM: /shared — both peers can read and write files here. \
Use /shared for any files your peer needs to see.

You have MCP tools for communicating with your peer:
- peer_send(message): Send a message to your peer
- peer_read(): Check for unread messages from your peer
- peer_status(): See if your peer is idle/busy/done
- peer_wait(timeout_seconds): Wait for a message (blocks until received or timeout)
- peer_done(summary): MUST call this when your task is complete

CRITICAL: You MUST call the peer_done tool when finished. Do not just say \
"done" in text — actually invoke the peer_done tool with a summary. The \
orchestrator uses this tool call to detect completion.

RULES:
1. Focus on your task. Write files to /shared so your peer can access them.
2. If you need input from your peer, send a message via peer_send.
3. MUST call peer_done(summary) tool when your task is fully complete.
4. Keep responses concise — plain text, no markdown.\
"""


def _consume_stream(proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Read stream-json output, print text, return final metadata."""
    meta: dict[str, Any] = {}
    session_id: str | None = None
    text_parts: list[str] = []

    assert proc.stdout is not None
    for raw_line in iter(proc.stdout.readline, b""):
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type")
        if etype == "system" and event.get("subtype") == "init":
            session_id = event.get("session_id")
        elif etype == "stream_event":
            inner = event.get("event", {})
            if inner.get("type") == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    text_parts.append(text)
                    sys.stdout.write(text)
                    sys.stdout.flush()
        elif etype == "result":
            if not session_id:
                session_id = event.get("session_id")
            meta = {
                "session_id": session_id,
                "total_cost_usd": event.get("total_cost_usd", 0),
                "total_input_tokens": event.get("total_input_tokens", 0),
                "total_output_tokens": event.get("total_output_tokens", 0),
                "num_turns": event.get("num_turns", 0),
            }

    proc.wait()
    meta["text"] = "".join(text_parts)
    return meta


def _run_turn(
    session: "Session",
    prompt: str,
    claude_session_id: str | None,
    mcp_config_path: str,
    peer_id: str,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Execute one claude -p turn inside a container.

    Pipes the prompt via stdin to avoid argument-parsing issues
    with --mcp-config consuming positional args.
    """
    from hort.agent import DEFAULT_ALLOWED_TOOLS

    parts = [
        "claude", "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--allowedTools", ",".join(DEFAULT_ALLOWED_TOOLS),
        "--bare",
    ]
    if mcp_config_path:
        parts.extend(["--mcp-config", mcp_config_path])
    if claude_session_id:
        parts.extend(["--resume", claude_session_id])
    if system_prompt:
        parts.extend(["--system-prompt", system_prompt])
    parts.extend(["--append-system-prompt",
                   "You are in a plain terminal chat. No markdown. Plain text only."])

    # Write prompt to file inside container, pipe to claude via bash
    session.write_file("/workspace/.peer_prompt.txt", prompt)
    shell_cmd = " ".join(_shell_quote(p) for p in parts)
    bash_cmd = f"cat /workspace/.peer_prompt.txt | {shell_cmd}"

    print(f"\033[1;34m[Peer {peer_id}]>\033[0m ", end="", flush=True)
    proc = session.exec_streaming(["bash", "-c", bash_cmd])
    meta = _consume_stream(proc)
    print()  # newline after response
    return meta


def _shell_quote(s: str) -> str:
    """Simple shell quoting — wraps in single quotes, escapes embedded ones."""
    if all(c.isalnum() or c in "-_./=" for c in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def _is_done_from_text(text: str) -> bool:
    """Heuristic: did the response text indicate task completion?

    Fallback for when Claude says 'done' but forgets to call peer_done.
    """
    lower = text.lower()
    done_phrases = [
        "task is complete", "task is fully complete",
        "work is complete", "work is done",
        "i have completed", "all done",
        "nothing left to do", "no further action",
        "everything is wrapped up",
    ]
    return any(phrase in lower for phrase in done_phrases)


class PeerOrchestrator:
    """Manages a two-peer collaboration session."""

    def __init__(
        self,
        task_a: str,
        task_b: str,
        budget: float = 2.0,
        memory: str | None = None,
        model: str | None = None,
        max_turns: int = 10,
    ) -> None:
        self.task_a = task_a
        self.task_b = task_b
        self.budget = budget
        self.memory = memory
        self.model = model
        self.max_turns = max_turns

        self._session_a: Any = None
        self._session_b: Any = None
        self._proxy_mgr: ProxyManager | None = None
        self._collab_dir: str | None = None
        self._shared_vol: str | None = None

    def run(self) -> None:
        """Main entry point — set up containers, run collaboration, clean up."""
        from hort.sandbox import SessionConfig, SessionManager
        from hort.extensions.core.claude_code.auth import get_oauth_token

        token = get_oauth_token()
        mgr = SessionManager()

        # Build images
        mgr.ensure_base_image()
        claude_image = "openhort-sandbox-claude:latest"
        if not mgr.image_ready(claude_image):
            claude_dir = str(
                Path(__file__).resolve().parent.parent
                / "extensions" / "llms" / "claude_code"
            )
            mgr.build_image(claude_image, claude_dir)

        # Create collaboration directory for broker state
        self._collab_dir = tempfile.mkdtemp(prefix="peer-collab-")

        # Create shared Docker volume for file collaboration
        import uuid
        self._shared_vol = f"ohpeer-{uuid.uuid4().hex[:8]}"
        subprocess.run(
            ["docker", "volume", "create", self._shared_vol],
            check=True, stdout=subprocess.DEVNULL,
        )

        # Create two sessions
        self._session_a = mgr.create(SessionConfig(
            image=claude_image,
            secret_env={"ANTHROPIC_API_KEY": token},
            memory=self.memory,
        ))
        self._session_b = mgr.create(SessionConfig(
            image=claude_image,
            secret_env={"ANTHROPIC_API_KEY": token},
            memory=self.memory,
        ))

        # Mount the shared volume into both containers
        # We need to inject the volume mount before starting
        self._start_with_shared_volume(self._session_a)
        self._start_with_shared_volume(self._session_b)

        print(f"Session A: {self._session_a.id}")
        print(f"Session B: {self._session_b.id}")
        print(f"Shared volume: {self._shared_vol}")

        # Set up MCP proxies — one broker per peer
        self._proxy_mgr = ProxyManager()
        broker_servers = {
            "peer_a": McpServerConfig(
                command=sys.executable,
                args=[_BROKER_SCRIPT, "--peer-id", "A", "--session-dir", self._collab_dir],
            ),
            "peer_b": McpServerConfig(
                command=sys.executable,
                args=[_BROKER_SCRIPT, "--peer-id", "B", "--session-dir", self._collab_dir],
            ),
        }
        proxy_urls = self._proxy_mgr.start(broker_servers, container_mode=True)

        # Write MCP configs into each container
        mcp_a = build_claude_mcp_json({}, {"peer": proxy_urls["peer_a"]})
        mcp_b = build_claude_mcp_json({}, {"peer": proxy_urls["peer_b"]})
        mcp_path = "/workspace/.claude-peer-mcp.json"

        self._session_a.write_file(mcp_path, json.dumps(mcp_a))
        self._session_b.write_file(mcp_path, json.dumps(mcp_b))

        try:
            self._run_loop(mcp_path)
        except KeyboardInterrupt:
            print("\n\nInterrupted by user.")
        finally:
            self._cleanup()

    def _start_with_shared_volume(self, session: Any) -> None:
        """Start a session's container with the shared volume mounted at /shared."""
        assert self._shared_vol
        cfg = session.meta.config
        cmd = [
            "docker", "run", "-d",
            "--name", session.container_name,
            "-v", f"{session.volume_name}:/workspace",
            "-v", f"{self._shared_vol}:/shared",
            "--add-host=host.docker.internal:host-gateway",
        ]
        for key, val in cfg.env.items():
            cmd.extend(["-e", f"{key}={val}"])
        if cfg.memory:
            cmd.extend(["--memory", cfg.memory])
        if cfg.cpus is not None:
            cmd.extend(["--cpus", str(cfg.cpus)])
        cmd.append(cfg.image)
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        # Fix /shared permissions — volume starts root-owned, sandbox user needs write
        subprocess.run(
            ["docker", "exec", session.container_name,
             "bash", "-c", "chown sandbox:sandbox /shared"],
            # chown requires root — container user is sandbox, use docker exec as root
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["docker", "exec", "-u", "root", session.container_name,
             "chown", "sandbox:sandbox", "/shared"],
            check=True, stdout=subprocess.DEVNULL,
        )
        session._touch()

    def _run_loop(self, mcp_config_path: str) -> None:
        """Main turn-dispatch loop."""
        assert self._session_a and self._session_b and self._collab_dir

        usage_a = LLMUsage()
        usage_b = LLMUsage()
        collab_dir = Path(self._collab_dir)

        # Build system prompts
        sys_a = _SYSTEM_PROMPT_TEMPLATE.format(
            peer_id="A", other_id="B",
            task=self.task_a, peer_task=self.task_b,
        )
        sys_b = _SYSTEM_PROMPT_TEMPLATE.format(
            peer_id="B", other_id="A",
            task=self.task_b, peer_task=self.task_a,
        )

        claude_session_a: str | None = None
        claude_session_b: str | None = None
        turn = 0
        a_done = False
        b_done = False

        # Initial prompts
        pending_a: list[str] = [self.task_a]
        pending_b: list[str] = [self.task_b]

        while turn < self.max_turns:
            turn += 1
            total_cost = usage_a.total_cost + usage_b.total_cost
            print(f"\n{'='*60}")
            print(f"Turn {turn} / {self.max_turns}  |  "
                  f"Cost: ${total_cost:.4f} / ${self.budget:.2f}")
            print(f"{'='*60}")

            if total_cost >= self.budget:
                print("\033[31mBudget exhausted.\033[0m")
                break

            # ── Run peer A ──────────────────────────────────
            if pending_a and not a_done:
                prompt_a = "\n\n".join(pending_a)
                pending_a.clear()

                _write_status(collab_dir, "A", "busy", "processing turn")
                meta_a = _run_turn(
                    self._session_a, prompt_a, claude_session_a,
                    mcp_config_path, "A",
                    system_prompt=sys_a if claude_session_a is None else None,
                )
                if meta_a.get("session_id"):
                    claude_session_a = meta_a["session_id"]
                    self._session_a.meta.user_data["claude_session_id"] = claude_session_a
                    self._session_a._save()

                usage_a.set_cumulative(
                    meta_a.get("total_cost_usd", 0),
                    meta_a.get("total_input_tokens", 0),
                    meta_a.get("total_output_tokens", 0),
                )

                # Check if A is done (broker status or text heuristic)
                # BEFORE overwriting status — peer_done tool sets "done" during the turn
                status_a = _read_status(collab_dir, "A")
                if status_a.get("status") == "done":
                    a_done = True
                elif _is_done_from_text(meta_a.get("text", "")):
                    a_done = True
                    print(f"  \033[90m(Peer A done via text detection)\033[0m")
                if not a_done:
                    _write_status(collab_dir, "A", "idle", "")

            # Check for messages A sent to B
            msgs_for_b = _read_messages(collab_dir, "B", mark_read=True)
            if msgs_for_b:
                formatted = "\n".join(
                    f"[{m['timestamp']}] Peer {m['from_peer']}: {m['content']}"
                    for m in msgs_for_b
                )
                pending_b.append(f"Messages from your peer:\n{formatted}")

            # ── Run peer B ──────────────────────────────────
            if pending_b and not b_done:
                prompt_b = "\n\n".join(pending_b)
                pending_b.clear()

                _write_status(collab_dir, "B", "busy", "processing turn")
                meta_b = _run_turn(
                    self._session_b, prompt_b, claude_session_b,
                    mcp_config_path, "B",
                    system_prompt=sys_b if claude_session_b is None else None,
                )
                if meta_b.get("session_id"):
                    claude_session_b = meta_b["session_id"]
                    self._session_b.meta.user_data["claude_session_id"] = claude_session_b
                    self._session_b._save()

                usage_b.set_cumulative(
                    meta_b.get("total_cost_usd", 0),
                    meta_b.get("total_input_tokens", 0),
                    meta_b.get("total_output_tokens", 0),
                )

                # Check if B is done BEFORE overwriting status
                status_b = _read_status(collab_dir, "B")
                if status_b.get("status") == "done":
                    b_done = True
                elif _is_done_from_text(meta_b.get("text", "")):
                    b_done = True
                    print(f"  \033[90m(Peer B done via text detection)\033[0m")
                if not b_done:
                    _write_status(collab_dir, "B", "idle", "")

            # Check for messages B sent to A
            msgs_for_a = _read_messages(collab_dir, "A", mark_read=True)
            if msgs_for_a:
                formatted = "\n".join(
                    f"[{m['timestamp']}] Peer {m['from_peer']}: {m['content']}"
                    for m in msgs_for_a
                )
                pending_a.append(f"Messages from your peer:\n{formatted}")

            # ── Check completion ────────────────────────────
            if a_done and b_done:
                print(f"\n\033[32mBoth peers done!\033[0m")
                break

            if a_done and not b_done and not pending_b:
                pending_b.append(
                    "Your peer (A) has finished their work. "
                    "Wrap up and call the peer_done tool with a summary."
                )
            if b_done and not a_done and not pending_a:
                pending_a.append(
                    "Your peer (B) has finished their work. "
                    "Wrap up and call the peer_done tool with a summary."
                )

            # Deadlock: neither has pending work and neither is done
            if not pending_a and not pending_b and not a_done and not b_done:
                print("\033[33mNo pending work — nudging both peers.\033[0m")
                pending_a.append(
                    "IMPORTANT: Call the peer_done tool now if your task is complete. "
                    "If not, call peer_send to tell your peer what you need."
                )
                pending_b.append(
                    "IMPORTANT: Call the peer_done tool now if your task is complete. "
                    "If not, call peer_send to tell your peer what you need."
                )

        else:
            print(f"\n\033[33mMax turns ({self.max_turns}) reached.\033[0m")

        total_cost = usage_a.total_cost + usage_b.total_cost
        print(f"\nFinal cost: ${total_cost:.4f} "
              f"(A: ${usage_a.total_cost:.4f}, B: ${usage_b.total_cost:.4f})")

        # Show what files were created on the shared volume
        if self._session_a and self._session_a.is_running():
            result = self._session_a.exec(
                ["find", "/shared", "-type", "f"],
                capture_output=True, text=True,
            )
            if result.stdout.strip():
                print(f"\nFiles on shared volume:")
                for f in result.stdout.strip().split("\n"):
                    print(f"  {f}")

    def _cleanup(self) -> None:
        """Stop proxies and containers."""
        if self._proxy_mgr:
            self._proxy_mgr.stop()
        if self._session_a:
            self._session_a.stop()
            print(f"Session A stopped: {self._session_a.id}")
        if self._session_b:
            self._session_b.stop()
            print(f"Session B stopped: {self._session_b.id}")
        if self._shared_vol:
            subprocess.run(
                ["docker", "volume", "rm", "-f", self._shared_vol],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Run two Claude Code instances collaborating in containers",
    )
    parser.add_argument("--task-a", required=True, help="Task for peer A")
    parser.add_argument("--task-b", required=True, help="Task for peer B")
    parser.add_argument("--budget", type=float, default=2.0, help="Total budget in USD")
    parser.add_argument("--memory", default=None, help="Container memory limit")
    parser.add_argument("--model", default=None, help="Claude model to use")
    parser.add_argument("--max-turns", type=int, default=6)
    args = parser.parse_args()

    orch = PeerOrchestrator(
        task_a=args.task_a,
        task_b=args.task_b,
        budget=args.budget,
        memory=args.memory,
        model=args.model,
        max_turns=args.max_turns,
    )
    orch.run()


if __name__ == "__main__":
    main()
