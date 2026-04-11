"""Integration tests for the llming-models API provider.

Run explicitly with an API key:

    ANTHROPIC_API_KEY=sk-... poetry run pytest \
        hort/extensions/llms/llming_models_ext/tests/ -v -m integration
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hort.llm.history import ConversationStore

pytestmark = pytest.mark.integration


def _has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.fixture
def store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(store_dir=tmp_path)


@pytest.fixture
def provider(store: ConversationStore):
    from llmings.llms.llming_models_ext.provider import LlmingProvider

    return LlmingProvider(
        model="claude_haiku",
        system_prompt="Reply in exactly one short sentence.",
        store=store,
    )


# ── Local mode: basic API calls ───────────────────────────────────


@pytest.mark.skipif(not _has_api_key(), reason="ANTHROPIC_API_KEY not set")
def test_send_single_message(provider: object, store: ConversationStore) -> None:
    """Send one message, verify non-empty response + history persisted."""
    response = provider.send("What is 2+2? Just the number.")  # type: ignore[union-attr]

    assert response.text.strip()
    assert "4" in response.text
    assert response.conversation_id is not None

    msgs = store.get_messages(response.conversation_id)
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"


@pytest.mark.skipif(not _has_api_key(), reason="ANTHROPIC_API_KEY not set")
def test_stream_response(provider: object) -> None:
    """Stream a response, verify chunks arrive."""
    chunks = list(provider.stream("Say hello."))  # type: ignore[union-attr]

    text_chunks = [c for c in chunks if c.kind == "text"]
    meta_chunks = [c for c in chunks if c.kind == "meta"]

    assert len(text_chunks) > 0
    full_text = "".join(c.data for c in text_chunks)
    assert len(full_text) > 0
    assert len(meta_chunks) == 1
    assert "conversation_id" in meta_chunks[0].data


@pytest.mark.skipif(not _has_api_key(), reason="ANTHROPIC_API_KEY not set")
def test_multi_turn_conversation(
    provider: object, store: ConversationStore,
) -> None:
    """Two messages in same conversation — model remembers context."""
    r1 = provider.send("Remember the number 42.")  # type: ignore[union-attr]
    conv_id = r1.conversation_id

    r2 = provider.send(  # type: ignore[union-attr]
        "What number did I ask you to remember?",
        conversation_id=conv_id,
    )

    assert "42" in r2.text
    assert r2.conversation_id == conv_id
    msgs = store.get_messages(conv_id)
    assert len(msgs) == 4


# ── Session persistence & resume ──────────────────────────────────


@pytest.mark.skipif(not _has_api_key(), reason="ANTHROPIC_API_KEY not set")
def test_conversation_persist_and_resume(tmp_path: Path) -> None:
    """Create a conversation, destroy the provider, resume from store."""
    from llmings.llms.llming_models_ext.provider import LlmingProvider

    store = ConversationStore(store_dir=tmp_path)
    p1 = LlmingProvider(
        model="claude_haiku",
        system_prompt="Reply in one sentence.",
        store=store,
    )

    r1 = p1.send("My secret code is PINEAPPLE.")
    conv_id = r1.conversation_id
    assert conv_id is not None

    # Destroy provider (simulates process restart)
    del p1

    # Resume with a new provider instance
    p2 = LlmingProvider(
        model="claude_haiku",
        system_prompt="Reply in one sentence.",
        store=store,
    )

    r2 = p2.send(
        "What is my secret code?", conversation_id=conv_id,
    )
    assert "PINEAPPLE" in r2.text.upper()


# ── Cleanup ───────────────────────────────────────────────────────


@pytest.mark.skipif(not _has_api_key(), reason="ANTHROPIC_API_KEY not set")
def test_conversation_cleanup(
    provider: object, store: ConversationStore,
) -> None:
    """Verify cleanup removes the conversation."""
    r = provider.send("Hello")  # type: ignore[union-attr]
    conv_id = r.conversation_id
    assert store.get(conv_id) is not None

    provider.cleanup(conv_id)  # type: ignore[union-attr]
    assert store.get(conv_id) is None


def test_expired_cleanup(tmp_path: Path) -> None:
    """Verify timeout-based cleanup works without API calls."""
    from datetime import datetime, timedelta, timezone

    store = ConversationStore(store_dir=tmp_path)
    cid = store.create("test", "model", timeout_minutes=1)

    # Backdate
    conv = store.get(cid)
    assert conv is not None
    conv.last_active = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    store._save(conv)

    destroyed = store.cleanup_expired()
    assert cid in destroyed
    assert store.get(cid) is None


# ── API key isolation ─────────────────────────────────────────────


def test_secret_env_not_persisted(tmp_path: Path) -> None:
    """Verify secret_env is excluded from serialized metadata."""
    import json

    from hort.sandbox import SessionConfig, SessionManager

    mgr = SessionManager(store_dir=tmp_path)
    session = mgr.create(SessionConfig(
        secret_env={"ANTHROPIC_API_KEY": "sk-secret-test"},
        env={"SAFE_VAR": "visible"},
    ))

    # Read the persisted JSON
    meta_file = tmp_path / f"{session.id}.json"
    data = json.loads(meta_file.read_text())

    # secret_env must NOT appear in the file
    config = data["config"]
    assert "secret_env" not in config
    assert "sk-secret-test" not in meta_file.read_text()

    # Regular env IS persisted
    assert config["env"]["SAFE_VAR"] == "visible"


def test_secret_env_in_exec_prefix(tmp_path: Path) -> None:
    """Verify _exec_prefix includes secret env vars."""
    from hort.sandbox import SessionConfig, SessionManager

    mgr = SessionManager(store_dir=tmp_path)
    session = mgr.create(SessionConfig(
        secret_env={"API_KEY": "secret123", "OTHER": "val"},
    ))

    prefix = session._exec_prefix()
    assert "-e" in prefix
    assert "API_KEY=secret123" in prefix
    assert "OTHER=val" in prefix


def test_secret_env_not_in_docker_run(tmp_path: Path) -> None:
    """Verify _build_run_cmd does NOT include secret_env."""
    from hort.sandbox import SessionConfig, SessionManager

    mgr = SessionManager(store_dir=tmp_path)
    session = mgr.create(SessionConfig(
        secret_env={"API_KEY": "secret123"},
        env={"SAFE": "yes"},
    ))

    cmd = session._build_run_cmd()
    cmd_str = " ".join(cmd)

    # secret must not appear in docker run
    assert "secret123" not in cmd_str
    # regular env should appear
    assert "SAFE=yes" in cmd_str
