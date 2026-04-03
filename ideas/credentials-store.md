# Credentials Store

Shared authentication credentials that any Llming or Circuit node
can use. Authenticate once, use everywhere.

## The "sync once" problem

When a user sets up Office 365, they authenticate once. That token
should be usable by:
- The Office 365 Llming's Powers
- Any Circuit that uses Office 365 nodes
- The chat backend when the agent needs email access
- Future Llmings that also need Office 365

Currently each extension would manage its own tokens independently.
Credentials should be a shared, first-class concept.

## What it stores

- OAuth 2.0 tokens (access + refresh)
- API keys
- Device codes
- Service accounts
- Per-user multi-account tokens (work + personal)

## Requirements

- Encrypted at rest (keychain on macOS, encrypted file on Linux)
- Automatic token refresh with retry
- UI: "Connect Account" flow in settings
- Credential sharing across Llmings and Circuit nodes
- Revocation on extension unload (optional, configurable)
- Audit log: which Llming/Circuit used which credential when

## API for extensions

```python
# In a Power
token = await self.credentials.get("microsoft", account="work")
response = requests.get("https://graph.microsoft.com/...",
                        headers={"Authorization": f"Bearer {token}"})

# In a Circuit node
# Credential is selected in the node config UI, resolved at runtime
```

## Priority

Blocker — nothing external works without this. Must come before
any service integration (Office 365, Google, Slack, etc.).
