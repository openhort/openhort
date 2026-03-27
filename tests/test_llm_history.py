"""Tests for the LLM conversation history store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hort.llm.history import ConversationStore


def test_create_and_get(tmp_path: Path) -> None:
    store = ConversationStore(store_dir=tmp_path)
    cid = store.create("anthropic", "sonnet")
    conv = store.get(cid)
    assert conv is not None
    assert conv.provider == "anthropic"
    assert conv.model == "sonnet"
    assert conv.messages == []


def test_add_and_get_messages(tmp_path: Path) -> None:
    store = ConversationStore(store_dir=tmp_path)
    cid = store.create("openai", "gpt-4")
    store.add_message(cid, "user", "Hello")
    store.add_message(cid, "assistant", "Hi there!")
    store.add_message(cid, "user", "How are you?")

    msgs = store.get_messages(cid)
    assert len(msgs) == 3
    assert msgs[0].role == "user"
    assert msgs[0].content == "Hello"
    assert msgs[1].role == "assistant"
    assert msgs[2].content == "How are you?"


def test_add_message_missing_conversation(tmp_path: Path) -> None:
    store = ConversationStore(store_dir=tmp_path)
    with pytest.raises(ValueError, match="not found"):
        store.add_message("nonexistent", "user", "hello")


def test_get_messages_missing(tmp_path: Path) -> None:
    store = ConversationStore(store_dir=tmp_path)
    assert store.get_messages("nonexistent") == []


def test_delete(tmp_path: Path) -> None:
    store = ConversationStore(store_dir=tmp_path)
    cid = store.create("test", "model")
    assert store.delete(cid) is True
    assert store.get(cid) is None
    assert store.delete(cid) is False


def test_list_conversations(tmp_path: Path) -> None:
    store = ConversationStore(store_dir=tmp_path)
    store.create("a", "m1")
    store.create("b", "m2")
    store.create("c", "m3")

    convos = store.list_conversations()
    assert len(convos) == 3


def test_list_order_newest_first(tmp_path: Path) -> None:
    store = ConversationStore(store_dir=tmp_path)
    c1 = store.create("a", "m")
    c2 = store.create("b", "m")

    # Make c1 older
    conv = store.get(c1)
    assert conv is not None
    conv.last_active = "2025-01-01T00:00:00+00:00"
    store._save(conv)

    convos = store.list_conversations()
    assert convos[0].id == c2
    assert convos[1].id == c1


def test_cleanup_expired(tmp_path: Path) -> None:
    store = ConversationStore(store_dir=tmp_path)

    # Create an expired conversation
    old_id = store.create("test", "m", timeout_minutes=30)
    conv = store.get(old_id)
    assert conv is not None
    conv.last_active = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat()
    store._save(conv)

    # Create a fresh conversation
    new_id = store.create("test", "m", timeout_minutes=60)

    destroyed = store.cleanup_expired()
    assert old_id in destroyed
    assert new_id not in destroyed
    assert store.get(old_id) is None
    assert store.get(new_id) is not None


def test_cleanup_respects_timeout(tmp_path: Path) -> None:
    store = ConversationStore(store_dir=tmp_path)

    # 20 min ago, 60 min timeout → NOT expired
    cid = store.create("test", "m", timeout_minutes=60)
    conv = store.get(cid)
    assert conv is not None
    conv.last_active = (
        datetime.now(timezone.utc) - timedelta(minutes=20)
    ).isoformat()
    store._save(conv)

    assert store.cleanup_expired() == []


def test_add_message_updates_last_active(tmp_path: Path) -> None:
    store = ConversationStore(store_dir=tmp_path)
    cid = store.create("test", "m")
    conv1 = store.get(cid)
    assert conv1 is not None
    old_active = conv1.last_active

    store.add_message(cid, "user", "ping")
    conv2 = store.get(cid)
    assert conv2 is not None
    assert conv2.last_active >= old_active


def test_custom_timeout(tmp_path: Path) -> None:
    store = ConversationStore(store_dir=tmp_path)
    cid = store.create("test", "m", timeout_minutes=120)
    conv = store.get(cid)
    assert conv is not None
    assert conv.timeout_minutes == 120
