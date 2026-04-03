# Model Providers

The framework supports multiple AI providers through a unified
interface. Each provider handles authentication, API calls, and
output parsing.

## Supported Providers

| Provider | `provider` value | Auth | Tool support |
|----------|-----------------|------|-------------|
| Claude Code CLI | `claude-code` | Keychain, env, file | Built-in (Bash, Read, Write, etc.) |
| Anthropic API | `anthropic` | API key | Native tool_use |
| OpenAI API | `openai` | API key | Function calling |
| llming-model | `llming-model` | Session token | llming tool protocol |
| Custom CLI | `custom` | Varies | None (chat only) |

## Configuration

```yaml
model:
  provider: claude-code
  name: sonnet
  api_key_source: keychain
  temperature: 0.7
  max_output_tokens: 4096
```

## API Key Sources

Keys are NEVER stored in the YAML file. The parser rejects
configs containing literal keys.

| Source | Syntax | Resolution |
|--------|--------|-----------|
| macOS Keychain | `keychain` | Reads `Claude Code-credentials` from login keychain |
| Environment var | `env:OPENAI_API_KEY` | `os.environ["OPENAI_API_KEY"]` |
| File | `file:/path/to/key.txt` | First line of file |
| Controller | `controller` | Key sent from controller node (multi-node only) |

### Keychain Details (macOS)

The macOS Keychain entry `Claude Code-credentials` contains:

```json
{
  "claudeAiOauth": {
    "accessToken": "sk-ant-oat01-...",
    "refreshToken": "sk-ant-ort01-...",
    "expiresAt": 1774529896836
  }
}
```

The `accessToken` works as `ANTHROPIC_API_KEY` when Claude CLI
is run with `--bare` mode (which skips keychain reads inside the
container).

## Provider Details

### Claude Code CLI

- Spawns `claude -p --output-format stream-json` per turn
- Container mode adds `--bare` and `--dangerously-skip-permissions`
- Session continuity via `--resume <session_id>`
- Tools filtered via `--allowedTools` / `--disallowedTools`
- Non-root user inside container (required by `--dangerously-skip-permissions`)

### Anthropic API

- Direct `anthropic` Python SDK calls
- No container needed (API calls from host)
- Tools defined in the request body — filtered before sending
- Streaming via SSE

### OpenAI API

- Direct `openai` Python SDK calls
- Function calling for tools
- Response format adapter normalizes output to the common format

### Custom CLI

- Wraps any program that reads stdin and writes stdout
- No built-in tool support (chat only)
- Useful for fine-tuned models or specialized endpoints
