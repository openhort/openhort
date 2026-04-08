# Credential Provisioning

How credentials (API keys, OAuth tokens, secrets) flow between horts — from the host OS credential store down to sandboxed containers and remote machines.

## Principle: Credentials Flow Downward

Credentials are owned by the root hort and provisioned **downward** to children via the H2H `auth` channel. A child hort never has credentials of its own — it receives what the parent grants.

```mermaid
graph TD
    subgraph root ["🏠 Root Hort (macOS/Linux/Windows)"]
        STORE["🔐 OS Credential Store"]
        AGENT["🤖 Agent"]
    end
    
    subgraph child1 ["🏠 Sandbox Container"]
        C1["🤖 Claude"]
    end
    
    subgraph child2 ["🏠 Hosted App"]
        C2["📦 App"]
    end
    
    STORE -->|"read"| AGENT
    AGENT -->|"auth/set_credential<br/>(H2H, in-memory only)"| child1
    AGENT -->|"auth/set_credential<br/>(H2H, in-memory only)"| child2
    
    child1 -.->|"❌ cannot read store"| STORE
    child2 -.->|"❌ cannot read store"| STORE
```

### Security Properties

- Credentials are **never persisted to disk** inside containers
- Credentials are **never in container environment variables** (`docker inspect` shows nothing)
- Credentials are **never in process arguments** (`ps aux` shows nothing)
- Credentials are provisioned **per-session** — container restart = credentials gone
- The parent decides **which** credentials each child receives
- Children cannot request credentials — only the parent pushes them

## OS Credential Store (Cross-Platform)

The root hort reads credentials from the host OS native credential store:

| OS | Store | CLI Tool | Service Name |
|---|---|---|---|
| **macOS** | Keychain | `security find-generic-password` | `Claude Code-credentials` |
| **Linux** | libsecret (GNOME Keyring / KDE Wallet) | `secret-tool lookup` | `Claude Code-credentials` |
| **Windows** | Credential Manager | PowerShell `Get-StoredCredential` | `Claude Code-credentials` |

### Credential Structure

The store contains a JSON blob with all auth methods:

```json
{
  "claudeAiOauth": {
    "accessToken": "sk-ant-oat01-...",
    "refreshToken": "sk-ant-ort01-...",
    "expiresAt": 1775656655494,
    "scopes": ["user:inference", "user:sessions:claude_code"],
    "subscriptionType": "max"
  }
}
```

### Extraction

```python
def get_api_key() -> str:
    """Try (in order):
    1. ANTHROPIC_API_KEY environment variable
    2. OAuth token from OS credential store
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        return api_key
    creds = _read_credential_store()  # OS-specific
    return creds["claudeAiOauth"]["accessToken"]
```

## Container Credential Injection

### Current: apiKeyHelper Pattern

Claude Code CLI in `--bare` mode accepts credentials via a `settings.json` file with an `apiKeyHelper` command:

```json
{"apiKeyHelper": "cat /home/sandbox/.claude/api_key"}
```

The parent writes the key file and settings into the container before launching Claude:

```mermaid
sequenceDiagram
    participant Host as 🏠 Host (macOS)
    participant Store as 🔐 Keychain
    participant Container as 🏠 Container
    participant Claude as 🤖 Claude CLI
    
    Host->>Store: Read OAuth token
    Store-->>Host: sk-ant-oat01-...
    Host->>Container: Write /home/sandbox/.claude/api_key
    Host->>Container: Write /home/sandbox/.claude/settings.json<br/>{"apiKeyHelper": "cat .../api_key"}
    Host->>Container: Launch claude --bare --settings .../settings.json
    Claude->>Claude: Reads apiKeyHelper → cat api_key → token
    Claude->>Claude: Authenticates with Anthropic API
```

### Target: H2H Auth Channel

With the H2H agent, credential injection becomes a protocol message:

```mermaid
sequenceDiagram
    participant Host as 🏠 Host
    participant Agent as 🤖 H2H Agent (PID 1)
    participant Claude as 🤖 Claude CLI
    
    Host->>Agent: {"channel":"auth","method":"set_credential",<br/>"params":{"name":"claude_api","value":"sk-ant-..."}}
    Note over Agent: Stored in memory only.<br/>Never touches disk.
    Agent-->>Host: {"status":"ok"}
    
    Host->>Agent: {"channel":"process","method":"start",<br/>"params":{"cmd":"claude","args":["-p","hello"]}}
    Note over Agent: Injects credential into<br/>process environment.<br/>Not visible in /proc/1/environ.
    Agent-->>Host: {"pid":42,"status":"running"}
```

No files on disk. No env vars in the container. The H2H agent holds credentials in memory and injects them per-process.

## Credential Sharing Between Horts

### Parent → Child (Default)

The parent explicitly provisions credentials to each child. Different children can receive different credentials:

```yaml
hort:
  name: "Root"
  credentials:
    anthropic: { source: keychain, service: "Claude Code-credentials" }
    github: { source: env, var: GITHUB_TOKEN }
    
  sub_horts:
    sandbox:
      credentials:
        anthropic: inherit     # receives the same Anthropic key
        # github: NOT listed → sandbox never gets GitHub token
    
    code-runner:
      credentials:
        github: inherit        # receives GitHub token
        # anthropic: NOT listed → code-runner never gets Anthropic key
```

### Credential Scoping Rules

```mermaid
flowchart TD
    ROOT["🏠 Root Hort<br/>Has: anthropic, github, sap"] 
    
    ROOT -->|"inherit: anthropic"| SANDBOX["🏠 Sandbox<br/>Has: anthropic"]
    ROOT -->|"inherit: github"| CODE["🏠 Code Runner<br/>Has: github"]
    ROOT -->|"inherit: anthropic, sap"| WORK["🏠 Work VM<br/>Has: anthropic, sap"]
    
    WORK -->|"inherit: sap"| SAP_C["🏠 SAP Container<br/>Has: sap"]
    WORK -->|"(none)"| TEMP["🏠 Temp Container<br/>Has: nothing"]
```

- A child **never** inherits credentials automatically — the parent must explicitly list each one
- A child **cannot** request credentials it wasn't granted
- A child **can** pass inherited credentials further down (if its wire rules allow the `auth` channel)
- Credential inheritance is **transitive but explicit** at each hop

### Neighbor Horts

Neighbor horts (same level) **never** share credentials directly. Credentials always flow through the parent:

```mermaid
graph TD
    subgraph parent ["🏠 Parent"]
        P["🤖 Agent"]
    end
    
    subgraph a ["🏠 Neighbor A"]
        A["📦 App A"]
    end
    
    subgraph b ["🏠 Neighbor B"]
        B["📦 App B"]
    end
    
    P -->|"auth: anthropic"| a
    P -->|"auth: github"| b
    a -.->|"❌ cannot share with B"| b
```

If both neighbors need the same credential, the parent provisions it to each independently.

### Credential Rotation

When a credential is rotated (e.g., OAuth token refresh), the parent re-provisions all children that hold it:

```mermaid
sequenceDiagram
    participant Store as 🔐 Credential Store
    participant Root as 🏠 Root Hort
    participant A as 🏠 Child A
    participant B as 🏠 Child B
    
    Store-->>Root: Token refreshed (new value)
    Root->>A: auth/set_credential {name: "api", value: "new-token"}
    Root->>B: auth/set_credential {name: "api", value: "new-token"}
    A-->>Root: ok
    B-->>Root: ok
    Note over Root: All children updated atomically
```

### Credential Types

| Type | Example | Lifetime | Rotation |
|---|---|---|---|
| **OAuth token** | Claude Code access token | Hours (auto-refresh) | Parent refreshes, re-provisions |
| **API key** | `ANTHROPIC_API_KEY` | Permanent until revoked | Manual rotation |
| **Session token** | Hosted app login cookie | Session-scoped | Re-created on container restart |
| **Certificate** | TLS client cert | Months | Parent re-provisions on renewal |
| **Vault secret** | Database password | TTL-based | Parent leases from vault, provisions to children |

## Platform-Specific Implementation

### macOS Host

```python
# Read from Keychain
raw = subprocess.check_output(
    ["security", "find-generic-password",
     "-s", "Claude Code-credentials", "-w"],
    stderr=subprocess.DEVNULL, text=True,
).strip()
creds = json.loads(raw)
token = creds["claudeAiOauth"]["accessToken"]
```

### Linux Host

```python
# Read from libsecret (GNOME Keyring / KDE Wallet)
raw = subprocess.check_output(
    ["secret-tool", "lookup", "service", "Claude Code-credentials"],
    stderr=subprocess.DEVNULL, text=True,
).strip()
creds = json.loads(raw)
token = creds["claudeAiOauth"]["accessToken"]
```

!!! note "Linux prerequisites"
    Requires `libsecret-tools` package and a running secret service (GNOME Keyring or KDE Wallet). Headless servers use `gnome-keyring-daemon` with `--unlock` from a PAM module or systemd service.

### Windows Host

```python
# Read from Credential Manager via PowerShell
ps_script = (
    '[System.Runtime.InteropServices.Marshal]::'
    'PtrToStringAuto([System.Runtime.InteropServices.Marshal]::'
    'SecureStringToBSTR((Get-StoredCredential -Target '
    '"Claude Code-credentials").Password))'
)
raw = subprocess.check_output(
    ["powershell", "-NoProfile", "-Command", ps_script],
    stderr=subprocess.DEVNULL, text=True,
).strip()
creds = json.loads(raw)
token = creds["claudeAiOauth"]["accessToken"]
```

!!! note "Windows prerequisites"
    Requires the `CredentialManager` PowerShell module. Credentials are stored per-user in the Windows Credential Vault.

### Fallback Chain

If the OS credential store is unavailable (headless server, CI, Docker host):

```mermaid
flowchart TD
    START["Need API key"] --> ENV{"ANTHROPIC_API_KEY<br/>env var set?"}
    ENV -->|"Yes"| USE_ENV["Use env var"]
    ENV -->|"No"| OS{"OS credential<br/>store available?"}
    OS -->|"Yes"| USE_OS["Read from Keychain /<br/>libsecret / CredMan"]
    OS -->|"No"| FILE{"~/.hort/credentials<br/>file exists?"}
    FILE -->|"Yes"| USE_FILE["Read from file<br/>(chmod 600, owner-only)"]
    FILE -->|"No"| FAIL["❌ RuntimeError:<br/>No credentials found"]
    
    style FAIL fill:#f44336,color:#fff
```

## Threat Mitigations

| Threat | Mitigation |
|---|---|
| Container reads host Keychain | Not mounted. No `security` binary in container. |
| Container reads /proc/1/environ | Credentials not in PID 1 env. Injected per-process. |
| Container reads credential file on disk | H2H agent stores in memory only. apiKeyHelper file is tmpfs. |
| `docker inspect` shows secrets | `secret_env` excluded from serialization (`exclude=True`). |
| `ps aux` on host shows key in args | H2H agent receives key via stdin, not command args. |
| Child provisions credentials upward | H2H direction: `parent_only`. Auth channel is parent→child only. |
| Sibling steals neighbor's credentials | Neighbors have no direct connection. All credentials via parent. |
| Credential persists after container stop | In-memory only. Container restart = clean slate. |
| OAuth token expires in long-running container | Parent monitors expiry, re-provisions via `auth/set_credential`. |
