"""Tests for PluginStore — FilePluginStore backend."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from hort.ext.store import FilePluginStore


@pytest.fixture
def store(tmp_path: Path) -> FilePluginStore:
    return FilePluginStore("test-plugin", base_dir=tmp_path)


class TestFilePluginStoreCRUD:
    async def test_get_missing_returns_none(self, store: FilePluginStore) -> None:
        assert await store.get("nonexistent") is None

    async def test_put_and_get(self, store: FilePluginStore) -> None:
        await store.put("key1", {"value": 42, "name": "test"})
        result = await store.get("key1")
        assert result == {"value": 42, "name": "test"}

    async def test_put_overwrites(self, store: FilePluginStore) -> None:
        await store.put("key1", {"v": 1})
        await store.put("key1", {"v": 2})
        assert await store.get("key1") == {"v": 2}

    async def test_delete_existing(self, store: FilePluginStore) -> None:
        await store.put("key1", {"x": 1})
        assert await store.delete("key1") is True
        assert await store.get("key1") is None

    async def test_delete_missing(self, store: FilePluginStore) -> None:
        assert await store.delete("nope") is False


class TestFilePluginStoreListing:
    async def test_list_keys_all(self, store: FilePluginStore) -> None:
        await store.put("a", {"x": 1})
        await store.put("b", {"x": 2})
        await store.put("c", {"x": 3})
        keys = await store.list_keys()
        assert sorted(keys) == ["a", "b", "c"]

    async def test_list_keys_prefix(self, store: FilePluginStore) -> None:
        await store.put("mail:1", {})
        await store.put("mail:2", {})
        await store.put("chat:1", {})
        assert sorted(await store.list_keys("mail:")) == ["mail:1", "mail:2"]

    async def test_list_keys_empty(self, store: FilePluginStore) -> None:
        assert await store.list_keys() == []


class TestFilePluginStoreQuery:
    async def test_query_all(self, store: FilePluginStore) -> None:
        await store.put("a", {"score": 10})
        await store.put("b", {"score": 20})
        results = await store.query()
        assert len(results) == 2

    async def test_query_with_filter(self, store: FilePluginStore) -> None:
        await store.put("a", {"score": 10})
        await store.put("b", {"score": 20})
        await store.put("c", {"score": 5})
        results = await store.query(filter_fn=lambda d: d.get("score", 0) > 8)
        assert len(results) == 2
        scores = {r["score"] for r in results}
        assert scores == {10, 20}

    async def test_query_with_limit(self, store: FilePluginStore) -> None:
        for i in range(10):
            await store.put(f"k{i}", {"i": i})
        results = await store.query(limit=3)
        assert len(results) == 3


class TestFilePluginStoreTTL:
    async def test_get_expired_returns_none(self, store: FilePluginStore) -> None:
        with patch("hort.ext.blobstore.time") as mock_time:
            mock_time.time.return_value = 1000.0
            await store.put("temp", {"v": 1}, ttl_seconds=60)

            # Not expired yet
            mock_time.time.return_value = 1050.0
            assert await store.get("temp") == {"v": 1}

            # Expired
            mock_time.time.return_value = 1061.0
            assert await store.get("temp") is None

    async def test_list_keys_excludes_expired(self, store: FilePluginStore) -> None:
        with patch("hort.ext.blobstore.time") as mock_time:
            mock_time.time.return_value = 1000.0
            await store.put("keep", {"v": 1})
            await store.put("expire", {"v": 2}, ttl_seconds=10)

            mock_time.time.return_value = 1011.0
            keys = await store.list_keys()
            assert keys == ["keep"]

    async def test_query_excludes_expired(self, store: FilePluginStore) -> None:
        with patch("hort.ext.blobstore.time") as mock_time:
            mock_time.time.return_value = 1000.0
            await store.put("a", {"v": 1})
            await store.put("b", {"v": 2}, ttl_seconds=5)

            mock_time.time.return_value = 1006.0
            results = await store.query()
            assert len(results) == 1
            assert results[0] == {"v": 1}

    async def test_cleanup_expired(self, store: FilePluginStore) -> None:
        with patch("hort.ext.blobstore.time") as mock_time:
            mock_time.time.return_value = 1000.0
            await store.put("keep", {"v": 1})
            await store.put("exp1", {"v": 2}, ttl_seconds=10)
            await store.put("exp2", {"v": 3}, ttl_seconds=20)

            mock_time.time.return_value = 1025.0
            removed = await store.cleanup_expired()
            assert removed == 2
            assert await store.list_keys() == ["keep"]

    async def test_cleanup_nothing_expired(self, store: FilePluginStore) -> None:
        await store.put("a", {"v": 1})
        removed = await store.cleanup_expired()
        assert removed == 0


class TestFilePluginStoreDefaults:
    async def test_default_base_dir(self) -> None:
        store = FilePluginStore("test-default")
        assert store._blobs._dir.name == "test-default.data"


class TestFilePluginStoreEdgeCases:
    async def test_corrupt_file(self, tmp_path: Path) -> None:
        store = FilePluginStore("bad", base_dir=tmp_path)
        # Write a corrupt blob
        blob_dir = tmp_path / "bad.data"
        blob_dir.mkdir(parents=True, exist_ok=True)
        (blob_dir / "x").write_text("not json")
        assert await store.get("x") is None

    async def test_put_no_ttl(self, store: FilePluginStore) -> None:
        await store.put("permanent", {"v": 1})
        result = await store.get("permanent")
        assert result == {"v": 1}

    async def test_separate_plugins_isolated(self, tmp_path: Path) -> None:
        store_a = FilePluginStore("plugin-a", base_dir=tmp_path)
        store_b = FilePluginStore("plugin-b", base_dir=tmp_path)
        await store_a.put("key", {"from": "a"})
        await store_b.put("key", {"from": "b"})
        assert await store_a.get("key") == {"from": "a"}
        assert await store_b.get("key") == {"from": "b"}
