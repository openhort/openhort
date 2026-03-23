"""Tests for PluginFileStore — LocalFileStore backend."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hort.ext.file_store import FileInfo, LocalFileStore


@pytest.fixture
def store(tmp_path: Path) -> LocalFileStore:
    return LocalFileStore("test-plugin", base_dir=tmp_path)


class TestLocalFileStoreCRUD:
    async def test_save_and_load(self, store: LocalFileStore) -> None:
        uri = await store.save("photo.jpg", b"\xff\xd8\xff", mime_type="image/jpeg")
        assert uri == "file://photo.jpg"
        result = await store.load("photo.jpg")
        assert result is not None
        data, mime = result
        assert data == b"\xff\xd8\xff"
        assert mime == "image/jpeg"

    async def test_load_missing_returns_none(self, store: LocalFileStore) -> None:
        assert await store.load("nope.txt") is None

    async def test_save_overwrites(self, store: LocalFileStore) -> None:
        await store.save("f.txt", b"v1", mime_type="text/plain")
        await store.save("f.txt", b"v2", mime_type="text/plain")
        result = await store.load("f.txt")
        assert result is not None
        assert result[0] == b"v2"

    async def test_delete_existing(self, store: LocalFileStore) -> None:
        await store.save("f.txt", b"data")
        assert await store.delete("f.txt") is True
        assert await store.load("f.txt") is None

    async def test_delete_missing(self, store: LocalFileStore) -> None:
        assert await store.delete("nope") is False


class TestLocalFileStoreListing:
    async def test_list_files_all(self, store: LocalFileStore) -> None:
        await store.save("a.txt", b"a", mime_type="text/plain")
        await store.save("b.jpg", b"b", mime_type="image/jpeg")
        files = await store.list_files()
        assert len(files) == 2
        names = {f.name for f in files}
        assert names == {"a.txt", "b.jpg"}

    async def test_list_files_prefix(self, store: LocalFileStore) -> None:
        await store.save("photo/1.jpg", b"a")
        await store.save("photo/2.jpg", b"b")
        await store.save("doc/1.pdf", b"c")
        files = await store.list_files(prefix="photo/")
        assert len(files) == 2

    async def test_list_files_empty(self, store: LocalFileStore) -> None:
        assert await store.list_files() == []

    async def test_file_info_fields(self, store: LocalFileStore) -> None:
        await store.save("test.bin", b"hello", mime_type="application/octet-stream")
        files = await store.list_files()
        assert len(files) == 1
        f = files[0]
        assert f.name == "test.bin"
        assert f.mime_type == "application/octet-stream"
        assert f.size == 5
        assert f.created_at > 0
        assert f.expires_at is None


class TestLocalFileStoreTTL:
    async def test_load_expired_returns_none(self, store: LocalFileStore) -> None:
        with patch("hort.ext.file_store.time") as mock_time:
            mock_time.time.return_value = 1000.0
            await store.save("temp.txt", b"data", ttl_seconds=60)

            mock_time.time.return_value = 1050.0
            result = await store.load("temp.txt")
            assert result is not None

            mock_time.time.return_value = 1061.0
            assert await store.load("temp.txt") is None

    async def test_list_excludes_expired(self, store: LocalFileStore) -> None:
        with patch("hort.ext.file_store.time") as mock_time:
            mock_time.time.return_value = 1000.0
            await store.save("keep.txt", b"a")
            await store.save("expire.txt", b"b", ttl_seconds=10)

            mock_time.time.return_value = 1011.0
            files = await store.list_files()
            assert len(files) == 1
            assert files[0].name == "keep.txt"

    async def test_cleanup_expired(self, store: LocalFileStore) -> None:
        with patch("hort.ext.file_store.time") as mock_time:
            mock_time.time.return_value = 1000.0
            await store.save("keep.txt", b"a")
            await store.save("exp1.txt", b"b", ttl_seconds=10)
            await store.save("exp2.txt", b"c", ttl_seconds=20)

            mock_time.time.return_value = 1025.0
            removed = await store.cleanup_expired()
            assert removed == 2
            files = await store.list_files()
            assert len(files) == 1

    async def test_cleanup_nothing(self, store: LocalFileStore) -> None:
        await store.save("a.txt", b"data")
        assert await store.cleanup_expired() == 0


class TestLocalFileStoreEdgeCases:
    async def test_default_base_dir(self) -> None:
        store = LocalFileStore("test-default")
        # Just verify it doesn't crash; uses ~/.hort/plugins/
        assert store._dir.name == "files"

    async def test_corrupt_meta(self, tmp_path: Path) -> None:
        store = LocalFileStore("bad", base_dir=tmp_path)
        (tmp_path / "bad" / "files" / "_meta.json").write_text("not json")
        assert await store.list_files() == []

    async def test_load_file_missing_on_disk(self, store: LocalFileStore) -> None:
        """Meta has entry but actual file was deleted externally."""
        await store.save("ghost.txt", b"data")
        # Delete the file but leave meta
        (store._dir / "ghost.txt").unlink()
        assert await store.load("ghost.txt") is None


class TestLocalFileStoreIsolation:
    async def test_separate_plugins(self, tmp_path: Path) -> None:
        store_a = LocalFileStore("plugin-a", base_dir=tmp_path)
        store_b = LocalFileStore("plugin-b", base_dir=tmp_path)
        await store_a.save("shared-name.txt", b"from-a")
        await store_b.save("shared-name.txt", b"from-b")
        result_a = await store_a.load("shared-name.txt")
        result_b = await store_b.load("shared-name.txt")
        assert result_a is not None and result_a[0] == b"from-a"
        assert result_b is not None and result_b[0] == b"from-b"
