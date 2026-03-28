# Inter-Container Claude Code Communication

## Implementation Status

Working end-to-end. Two real Claude Code instances in Docker containers
collaborated to write a calculator module and its tests (22 passing) via
a shared volume and MCP-based message broker.

**Key files:**

- `hort/sandbox/peer_broker.py` — MCP stdio server for peer messaging (send/read/wait/done)
- `hort/sandbox/peer_orchestrator.py` — Turn-dispatch loop managing two Claude sessions
- `hort/sandbox/mcp.py` — Fixed SSE config format (`type: "sse"` required by Claude CLI)

**Run it:**

```bash
poetry run python -m hort.sandbox.peer_orchestrator \
  --task-a "Write /shared/module.py ..." \
  --task-b "Write /shared/test_module.py ..." \
  --budget 0.80 --max-turns 6
```

**Findings from real testing:**

- `claude -p --mcp-config` consumes positional args — must pipe prompt via stdin
- Claude CLI requires `"type": "sse"` in MCP config (plain `"url"` rejected)
- Claude often says "done" without calling `peer_done` tool — text heuristic needed as fallback
- Shared volume needs `chown` after creation (Docker volumes start root-owned)
- Cost per collaboration round: ~$0.02–0.08 depending on task complexity

---

## Problem Statement

Two Claude Code instances, each running in separate Docker containers (sandbox sessions), need to collaborate on a shared task. They must be able to exchange messages, coordinate work, and react to each other's output — even when one instance is faster or temporarily idle.

**Two modes to consider:**

| Mode | How started | Who controls turns | Feasibility |
|------|------------|-------------------|-------------|
| **Openhort-managed** | `run_chat()` / `claude -p` | Orchestrator on host | ✅ Fully feasible |
| **Standard Claude Code** | User types `claude` in container shell | User (interactive terminal) | ⚠️ Partially feasible |

---

## Key Insight: `claude -p --resume` Makes This Tractable

Claude Code's CLI has a critical property: **`claude -p` is stateless per invocation but stateful per conversation via `--resume`**.

```
claude -p --resume <session_id> "Your peer sent: ..."
```

Each invocation is one turn: prompt in → response out → process exits. The orchestrator can call `--resume` whenever it wants, injecting new context (including peer messages) into the conversation. This turns the "wake up a sleeping instance" problem into a simple "start a new turn" problem.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          HOST (openhort)                            │
│                                                                     │
│  ┌────────────────────┐         ┌──────────────────────────────┐   │
│  │   PeerBroker        │         │   PeerOrchestrator           │   │
│  │   (MCP Server)      │◄───────►│                              │   │
│  │                     │         │ • monitors broker queues      │   │
│  │  Channels:          │         │ • dispatches turns            │   │
│  │    A.inbox          │         │ • handles speed asymmetry     │   │
│  │    A.outbox ──► B   │         │ • budget tracking             │   │
│  │    B.inbox          │         │ • wake-up / nudge logic       │   │
│  │    B.outbox ──► A   │         │                              │   │
│  └──┬──────────┬───────┘         └───────┬──────────┬───────────┘   │
│     │ SSE      │ SSE                     │          │               │
│     │ proxy    │ proxy          docker exec    docker exec          │
│     │          │                claude -p      claude -p            │
│     │          │                --resume       --resume             │
│  ┌──▼──────┐ ┌─▼──────────┐                                        │
│  │Container│ │ Container   │                                        │
│  │    A    │ │     B       │                                        │
│  │         │ │             │                                        │
│  │ claude  │ │  claude     │                                        │
│  │ --mcp   │ │  --mcp      │                                        │
│  │ peer_*  │ │  peer_*     │                                        │
│  └─────────┘ └─────────────┘                                        │
└─────────────────────────────────────────────────────────────────────┘
```

Three components:

1. **PeerBroker** — MCP server on the host, proxied into both containers. Provides message send/receive tools.
2. **PeerOrchestrator** — Manages turn sequencing, delivers cross-peer messages, handles wake-up.
3. **MCP tools** — `peer_send`, `peer_read`, `peer_status`, `peer_wait` — used by Claude instances naturally during their work.

---

## Component 1: PeerBroker (MCP Server)

An MCP stdio server running on the host, proxied into containers via the existing `McpSseProxy` infrastructure.

### Data Model

```python
class PeerMessage(BaseModel):
    id: str                          # uuid
    from_peer: str                   # "A" or "B"
    to_peer: str                     # "A" or "B"
    content: str                     # free-form text
    timestamp: datetime
    read: bool = False

class PeerChannel(BaseModel):
    peer_id: str                     # "A" or "B"
    inbox: list[PeerMessage] = []    # messages received
    status: Literal["idle", "busy", "done"] = "idle"
    task_description: str = ""       # what this peer is working on

class PeerBrokerState(BaseModel):
    session_id: str                  # unique collaboration session
    channels: dict[str, PeerChannel] # keyed by peer_id
    created_at: datetime
```

### MCP Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `peer_send` | `message: str` | Send a message to the other peer. Automatically determines sender/recipient from the MCP connection identity. |
| `peer_read` | `mark_read: bool = True` | Read all unread messages from the other peer. Returns list of messages with timestamps. |
| `peer_status` | — | Check the other peer's status: idle, busy, or done. Includes their task description. |
| `peer_wait` | `timeout_seconds: int = 60` | Block until a new message arrives from the peer, or timeout. Returns the message(s) or a timeout indicator. |
| `peer_done` | `summary: str` | Signal that this peer has completed its work. Includes a final summary. |
| `peer_set_status` | `status: str, description: str` | Update own status and task description (so peer can see what you're doing). |

### Identity Resolution

Each container connects to the broker through a separate SSE proxy instance. The proxy URL encodes the peer identity:

```
Container A → http://host.docker.internal:PORT_A/sse  → broker knows caller is "A"
Container B → http://host.docker.internal:PORT_B/sse  → broker knows caller is "B"
```

Two separate proxy instances, same broker process, different port = different identity. The broker inspects which port the request arrived on to determine the caller.

**Alternative:** Single proxy, identity passed as a tool parameter or via environment variable injected into the container.

### Implementation Location

```
hort/sandbox/peer_broker.py     — PeerBrokerState, message routing logic
hort/sandbox/peer_mcp.py        — MCP tool definitions (JSON-RPC handlers)
```

Builds on the existing `McpSseProxy` pattern — no new transport code needed.

---

## Component 2: PeerOrchestrator

The orchestrator runs on the host and manages the lifecycle of both Claude instances. It is the "outer loop" that decides when each instance gets its next turn.

### Turn Model

```
                    ┌──────────┐
                    │  IDLE    │ ◄── waiting for prompt
                    └────┬─────┘
                         │ orchestrator sends prompt
                         ▼
                    ┌──────────┐
                    │  BUSY    │ ◄── claude -p running
                    └────┬─────┘
                         │ process exits
                         ▼
                    ┌──────────┐
                    │ BETWEEN  │ ◄── orchestrator checks broker
                    │  TURNS   │     for pending peer messages
                    └────┬─────┘
                         │
                    ┌────▼─────┐
          ┌─────────┤ DISPATCH │──────────┐
          │         └──────────┘          │
          ▼                               ▼
    peer messages?                   no messages?
    inject as next turn              wait / check other peer
```

### Core Loop (Pseudocode)

```python
async def run_collaboration(task_a: str, task_b: str, budget: float):
    broker = PeerBroker()
    session_a = create_claude_session(peer_id="A", broker=broker)
    session_b = create_claude_session(peer_id="B", broker=broker)

    # Initial prompts include system context about peer collaboration
    pending_a = [_initial_prompt("A", task_a)]
    pending_b = [_initial_prompt("B", task_b)]

    usage = LLMUsage(budget_limit=budget)

    while not _both_done(broker):
        # Run whichever peer has pending work
        if pending_a and not broker.is_busy("A"):
            prompt = _merge_prompts(pending_a)
            pending_a.clear()
            meta_a = await _run_turn(session_a, prompt)
            usage.set_cumulative(meta_a["total_cost_usd"], ...)

        # Check broker: did A send anything for B?
        new_for_b = broker.read_undelivered("B")
        if new_for_b:
            pending_b.append(_format_peer_messages(new_for_b))

        if pending_b and not broker.is_busy("B"):
            prompt = _merge_prompts(pending_b)
            pending_b.clear()
            meta_b = await _run_turn(session_b, prompt)
            usage.set_cumulative(meta_b["total_cost_usd"], ...)

        # Check broker: did B send anything for A?
        new_for_a = broker.read_undelivered("A")
        if new_for_a:
            pending_a.append(_format_peer_messages(new_for_a))

        # If neither has pending work, check for deadlock
        if not pending_a and not pending_b:
            if _deadlock_detected(broker):
                _nudge_peers(session_a, session_b, broker)
            else:
                await asyncio.sleep(1)  # brief pause before re-check
```

### _run_turn Implementation

```python
async def _run_turn(session: Session, prompt: str) -> dict:
    """Execute one claude -p --resume turn inside a container."""
    claude_session_id = session.meta.user_data.get("claude_session_id")

    cmd = [
        "claude", "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--dangerously-skip-permissions",
        "--bare",
        "--mcp-config", "/workspace/.claude-peer-mcp.json",
    ]
    if claude_session_id:
        cmd.extend(["--resume", claude_session_id])
    cmd.append(prompt)

    # Run in thread executor (never block event loop)
    proc = await asyncio.to_thread(session.exec_streaming, cmd)
    meta = await asyncio.to_thread(_consume_stream, proc)

    if meta.get("session_id"):
        session.meta.user_data["claude_session_id"] = meta["session_id"]
        session._save()

    return meta
```

### Implementation Location

```
hort/sandbox/peer_orchestrator.py   — PeerOrchestrator class, turn loop
```

---

## Component 3: Wake-Up Mechanisms

### Problem: One Instance Is Idle While the Other Has Work

Three scenarios and their solutions:

### Scenario 1: A finishes turn, sends message to B, B is between turns

**Solution:** The orchestrator's loop naturally picks this up. B's pending queue gets the message, and the orchestrator starts B's next turn.

This is the common case and requires no special handling.

### Scenario 2: A is mid-turn (long-running), B sends a message

**Solution:** A cannot be interrupted mid-turn (Claude CLI doesn't support that). Two options:

**Option 2a — Wait for A's turn to finish:**
The message queues in the broker. When A's turn completes, the orchestrator delivers B's message as A's next prompt.

**Option 2b — A polls within its turn:**
If A's system prompt instructs it to "periodically call `peer_read()` during long tasks," A can discover the message mid-turn. The `peer_read` MCP tool returns immediately with whatever is in the inbox.

Recommendation: Use 2a by default. Use 2b only for tasks where mid-turn coordination is critical (e.g., A is building something that B needs to validate step-by-step).

### Scenario 3: Both peers are idle (deadlock)

**Solution:** The orchestrator detects this (neither peer has pending work, neither has called `peer_done`). It sends a nudge:

```python
def _nudge_peers(session_a, session_b, broker):
    """Break deadlock by prompting both peers to continue."""
    if broker.status("A") != "done":
        pending_a.append(
            "Status check: Your peer is idle and waiting. "
            "If you need something from them, send a message via peer_send. "
            "If your work is complete, call peer_done with a summary."
        )
    # Same for B
```

### Scenario 4: One peer is much slower

**Solution:** The orchestrator tracks turn duration and implements patience:

```python
# Fast peer (A) finished and is waiting for slow peer (B)
if broker.has_pending_for("A") is False and broker.is_busy("B"):
    # Don't nudge B — it's working. A just has to wait.
    # But if B has been busy for > MAX_TURN_DURATION:
    if turn_duration("B") > MAX_TURN_DURATION:
        # B might be stuck. Log warning, optionally nudge.
        logger.warning("Peer B turn exceeding %ds", MAX_TURN_DURATION)
```

---

## Speed Asymmetry in Detail

Speed differences between instances are expected and normal. The design handles this at multiple levels:

### Token-Level Speed

Different models or different prompt complexity → one instance produces output faster. This is invisible to the architecture — it only matters at the turn level.

### Turn-Level Speed

Instance A completes its turn in 10s, instance B takes 120s.

**Design response:**
- The orchestrator doesn't round-robin. It runs whichever peer has pending work.
- If A finishes and has no pending work (no new messages from B), A simply waits.
- The orchestrator can optionally give A more work: "While waiting for your peer, you could also work on X."
- Budget tracking is cumulative across both instances.

### Asymmetric Workload

One instance has a trivial task, the other has a complex multi-step task.

**Design response:**
- `peer_done(summary)` lets the fast instance signal completion.
- The orchestrator can then focus entirely on the remaining instance.
- Or: redirect the fast instance to help the slow one:

```python
if broker.status("A") == "done" and broker.status("B") == "busy":
    # A is done. Optionally, give A a review task:
    pending_a.append(
        f"Your peer is still working on: {broker.task_description('B')}. "
        "Review what they've done so far (check peer_read for updates) "
        "and offer suggestions if you can help."
    )
```

---

## Motivating a Stalled Instance

Sometimes a Claude instance produces output that doesn't advance the task — it gets stuck in a loop, produces vague responses, or seems to lose track of its goal.

### Detection

The orchestrator can analyze the response:

```python
def _assess_progress(response_text: str, broker: PeerBroker, peer_id: str) -> str:
    """Heuristic: did the peer make progress?"""
    # No tool calls and short response → possibly stalled
    # Called peer_done → definitely progressed
    # Called peer_send → made communication progress
    # Long response with no tool calls → might be rambling
    ...
```

### Nudge Strategies

1. **Restate the goal:** "Reminder: your task is X. Your peer has completed Y. Focus on the next concrete step."

2. **Provide structure:** "Please respond with: (1) What you've done so far, (2) What's blocking you, (3) Your next action."

3. **Inject peer context:** "Your peer suggests: [message from other instance]. Does this help unblock you?"

4. **Escalate to user:** After N failed nudges, the orchestrator surfaces the situation to the human operator.

### Implementation

Nudges are just prompts sent via `--resume`. The orchestrator builds them based on heuristics and broker state. No special mechanism needed.

---

## Feasibility Analysis

### Openhort-Managed Mode: ✅ Fully Feasible

Everything aligns:

- **Turn control:** The orchestrator calls `claude -p --resume` — full control over when each instance runs.
- **Message delivery:** Between turns, the orchestrator checks the broker and injects messages as prompts.
- **Wake-up:** Starting a new `--resume` turn IS the wake-up. No interruption needed.
- **MCP tools:** Existing proxy infrastructure bridges the broker into containers.
- **Budget:** Tracked per-turn across both instances.
- **State:** `--resume` preserves conversation history. Session volumes preserve workspace.

### Standard Claude Code (Interactive): ⚠️ Partially Feasible

Challenges:

| Aspect | Status | Notes |
|--------|--------|-------|
| MCP tools | ✅ Works | Claude Code supports MCP config — `peer_send`/`peer_read` work fine |
| Sending messages | ✅ Works | Instance calls `peer_send` tool during its work |
| Receiving messages | ⚠️ Polling only | Instance must actively call `peer_read` or `peer_wait` |
| Wake-up from idle | ❌ Not possible | Interactive Claude waits at `you>` prompt — can't inject input from outside |
| Mid-turn interruption | ❌ Not possible | No mechanism to interrupt Claude during a response |

**What could work in interactive mode:**

1. **System prompt instructs polling:** "After completing each step, call `peer_read()` to check for messages from your collaborator."

2. **`peer_wait` as synchronization:** Instance A calls `peer_wait(timeout=120)`. The MCP tool blocks until B sends something. This works within a turn but not across turns.

3. **User-mediated:** The human user of each instance manually triggers checks: "Check if your peer has sent any messages." This defeats the purpose of automation.

**Verdict:** Interactive mode works for *cooperative* communication (both instances actively sending/receiving during their turns) but not for *reactive* communication (waking up an idle instance). Use openhort-managed mode for true autonomous collaboration.

---

## System Prompt Template

Each Claude instance receives a system prompt that establishes the collaboration context:

```
You are Peer {A|B} in a collaborative coding session. You are working alongside
another Claude Code instance (Peer {B|A}) in a separate container.

YOUR TASK: {task_description}
YOUR PEER'S TASK: {peer_task_description}
SHARED WORKSPACE: /workspace (both peers can see files here via the broker)

COLLABORATION TOOLS (via MCP):
- peer_send(message): Send a message to your peer
- peer_read(): Check for messages from your peer
- peer_status(): See if your peer is busy/idle/done
- peer_wait(timeout_seconds): Wait for a message from your peer
- peer_done(summary): Signal that your work is complete
- peer_set_status(status, description): Update what you're working on

RULES:
1. Work on your task independently, but coordinate with your peer when needed.
2. If you need something from your peer, send a message and continue with
   other work while waiting.
3. When you complete a significant step, update your status via peer_set_status.
4. Call peer_done(summary) when your task is fully complete.
5. If you receive a message from your peer, address it before continuing
   your own work.
```

---

## Shared Workspace via Volumes

Both containers can share a Docker volume for file-level collaboration:

```python
# Create a shared volume
shared_vol = f"ohshared-{collaboration_id}"
subprocess.run(["docker", "volume", "create", shared_vol], check=True)

# Mount into both containers at /shared
# (in addition to each container's own /workspace)
cmd_a = [..., "-v", f"{shared_vol}:/shared", ...]
cmd_b = [..., "-v", f"{shared_vol}:/shared", ...]
```

This enables:
- Instance A writes code to `/shared/module_a.py`
- Instance B reads and integrates it into `/shared/main.py`
- Both can see each other's file changes in real-time

The broker MCP tools handle coordination ("I've pushed changes to /shared, please review"), while the volume handles the actual data.

**Caveat:** Docker volumes have no file locking. The broker's messaging layer serves as the coordination protocol to prevent conflicts.

---

## Docker Network for Direct Container Communication

Currently containers are standalone (no Docker network). For peer communication, we could optionally create a shared network:

```python
network = f"ohpeer-{collaboration_id}"
subprocess.run(["docker", "network", "create", network], check=True)

# Both containers join the network
subprocess.run(["docker", "network", "connect", network, container_a], check=True)
subprocess.run(["docker", "network", "connect", network, container_b], check=True)

# Now containers can reach each other by name:
#   container A → http://ohsb-<b_id>:port/...
#   container B → http://ohsb-<a_id>:port/...
```

This is optional — the host-based broker is sufficient. Direct networking would only matter if we wanted containers to run their own services that the peer accesses directly (e.g., a web server in container A that B tests).

---

## Budget and Cost Control

Both instances share a single budget:

```python
class CollaborationBudget:
    total_limit: float              # e.g., $5.00
    per_turn_limit: float | None    # e.g., $0.50 per turn
    total_spent: float = 0.0

    def can_proceed(self) -> bool:
        return self.total_spent < self.total_limit

    def record(self, cost: float) -> None:
        self.total_spent += cost
```

The orchestrator checks the budget before dispatching each turn. If budget is exhausted, both instances receive a final "Budget exhausted, wrap up your work" prompt.

---

## Failure Modes and Recovery

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Container crashes | `session.is_running()` returns False | Restart container, resume conversation via `--resume` |
| Claude CLI error (non-zero exit) | Process exit code | Retry with same prompt, or surface error to orchestrator |
| Infinite loop (instance keeps talking to itself) | Turn count exceeds threshold | Inject "STOP: You've exceeded the turn limit. Call peer_done." |
| Deadlock (both waiting for each other) | Both idle, neither done, no pending messages | Nudge both with status summary |
| Budget exhaustion | `usage.budget_exceeded` | Final turn: "Budget exhausted. Summarize your work." |
| MCP proxy failure | Proxy health check / tool call timeout | Restart proxy, retry turn |

---

## Implementation Plan

### Phase 1: PeerBroker MCP Server

- `hort/sandbox/peer_broker.py` — In-memory message broker with channel model
- `hort/sandbox/peer_mcp.py` — MCP JSON-RPC tool handlers
- Wire into existing `McpSseProxy` — two proxy instances per collaboration

### Phase 2: PeerOrchestrator

- `hort/sandbox/peer_orchestrator.py` — Turn dispatch loop
- Integration with `Session` and `ClaudeCodeProvider`
- Budget tracking across both instances

### Phase 3: CLI Entry Point

- `python -m hort.sandbox.peer_collab --task-a "..." --task-b "..." --budget 5.0`
- Alternatively: extend `run_chat` with `--peer` mode

### Phase 4: Shared Volume and Network (optional)

- Shared volume creation and mounting
- Docker network for direct container access

### Phase 5: UI Integration (optional)

- Split-pane view in openhort UI showing both instances
- Real-time message flow visualization
- Manual intervention (inject messages into either instance)

---

## Example: Two Instances Collaborating on a Feature

**Task A:** "Implement the backend API for user authentication (FastAPI routes, Pydantic models, JWT tokens). Write to /shared/auth/"

**Task B:** "Implement the frontend login form (React component, API integration, error handling). Write to /shared/frontend/"

**Flow:**

1. Orchestrator starts both with their tasks + system prompt
2. A begins writing models, B begins writing the React component
3. A finishes the API schema, calls `peer_send("API ready at /shared/auth/routes.py — endpoints: POST /login, POST /register, GET /me. Schema: {username: str, password: str}")`
4. A's turn ends. Orchestrator sees the message, queues it for B.
5. B's turn ends. Orchestrator delivers A's message as B's next prompt.
6. B integrates the API schema into its fetch calls, calls `peer_send("Frontend integrated. Can you add CORS headers? I'm calling from localhost:3000")`
7. Orchestrator delivers to A. A adds CORS, calls `peer_done("Auth API complete with CORS.")`
8. B finishes integration, calls `peer_done("Frontend login complete.")`
9. Orchestrator sees both done, reports final summary and total cost.
