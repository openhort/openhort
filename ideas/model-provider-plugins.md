# Model Provider Plugins

Currently the chat backend hardcodes Claude Code CLI. Model providers
should be pluggable so extensions can add support for other backends.

## What this enables

- Ollama / local models (privacy-sensitive setups)
- OpenAI / GPT models
- Mistral / other API providers
- Custom enterprise endpoints
- Switching models per conversation or per connector

## Architecture

A `ModelProvider` interface that the chat backend uses:

```python
class ModelProvider(ABC):
    async def send(self, message: str, system_prompt: str,
                   session_id: str | None, mcp_config: str | None) -> AsyncIterator[ChatEvent]:
        ...
```

The chat backend currently wraps `claude -p`. This would become
the `ClaudeCodeModelProvider`. Others would implement the same
interface with HTTP API calls.

## Registration

Via extension manifest:

```json
{
  "name": "ollama-provider",
  "plugin_type": "model_provider",
  "entry_point": "provider:OllamaProvider"
}
```

## Priority

Medium — Claude Code works well, but lock-in to a single provider
limits flexibility. Important for self-hosted / air-gapped setups.
