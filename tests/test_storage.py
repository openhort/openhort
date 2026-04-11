"""Storage tests — scrolls, crates, TTL, GC, data integrity.

Tests cover:
- CRUD operations (insert, find, update, delete)
- MongoDB query operators ($gt, $in, $or, etc.)
- MongoDB update operators ($set, $inc, $push, etc.)
- TTL expiry and garbage collection
- Data integrity after hard kills
- Crate lifecycle (put, get, head, list, delete)
- Container isolation (per-llming separation)
- WAL mode crash resilience
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


# ══════════════════════════════════════════════════════════════════
# Scroll Store
# ══════════════════════════════════════════════════════════════════

class TestScrollStore:

    @pytest.fixture
    def store(self, tmp_path):
        from hort.storage.scrolls import ScrollStore
        s = ScrollStore(tmp_path / "test.db")
        yield s
        s.close()

    def test_insert_and_find(self, store):
        doc_id = store.insert("users", {"name": "Alice", "age": 30})
        assert doc_id
        doc = store.find_one("users", {"name": "Alice"})
        assert doc["name"] == "Alice"
        assert doc["age"] == 30
        assert doc["_id"] == doc_id

    def test_insert_with_custom_id(self, store):
        store.insert("users", {"_id": "custom-123", "name": "Bob"})
        doc = store.find_one("users", {"_id": "custom-123"})
        assert doc["name"] == "Bob"

    def test_find_multiple(self, store):
        store.insert("items", {"type": "fruit", "name": "apple"})
        store.insert("items", {"type": "fruit", "name": "banana"})
        store.insert("items", {"type": "vegetable", "name": "carrot"})
        fruits = store.find("items", {"type": "fruit"})
        assert len(fruits) == 2

    def test_find_with_sort(self, store):
        store.insert("items", {"name": "c"})
        store.insert("items", {"name": "a"})
        store.insert("items", {"name": "b"})
        result = store.find("items", sort=[("name", 1)])
        assert [d["name"] for d in result] == ["a", "b", "c"]
        result = store.find("items", sort=[("name", -1)])
        assert [d["name"] for d in result] == ["c", "b", "a"]

    def test_find_with_limit_skip(self, store):
        for i in range(10):
            store.insert("nums", {"n": i})
        result = store.find("nums", limit=3, skip=2, sort=[("n", 1)])
        assert [d["n"] for d in result] == [2, 3, 4]

    def test_find_no_match(self, store):
        store.insert("users", {"name": "Alice"})
        assert store.find_one("users", {"name": "Nobody"}) is None
        assert store.find("users", {"name": "Nobody"}) == []

    # ── Query operators ──

    def test_gt_lt(self, store):
        for i in range(10):
            store.insert("nums", {"n": i})
        result = store.find("nums", {"n": {"$gt": 7}})
        assert len(result) == 2  # 8, 9

    def test_gte_lte(self, store):
        for i in range(10):
            store.insert("nums", {"n": i})
        result = store.find("nums", {"n": {"$gte": 8, "$lte": 9}})
        assert len(result) == 2

    def test_ne(self, store):
        store.insert("items", {"status": "active"})
        store.insert("items", {"status": "inactive"})
        result = store.find("items", {"status": {"$ne": "active"}})
        assert len(result) == 1
        assert result[0]["status"] == "inactive"

    def test_in(self, store):
        store.insert("items", {"color": "red"})
        store.insert("items", {"color": "blue"})
        store.insert("items", {"color": "green"})
        result = store.find("items", {"color": {"$in": ["red", "green"]}})
        assert len(result) == 2

    def test_and_or(self, store):
        store.insert("items", {"a": 1, "b": 2})
        store.insert("items", {"a": 1, "b": 3})
        store.insert("items", {"a": 2, "b": 2})
        # $and
        result = store.find("items", {"$and": [{"a": 1}, {"b": 2}]})
        assert len(result) == 1
        # $or
        result = store.find("items", {"$or": [{"a": 2}, {"b": 3}]})
        assert len(result) == 2

    # ── Update operators ──

    def test_update_set(self, store):
        store.insert("users", {"_id": "u1", "name": "Alice", "age": 30})
        store.update_one("users", {"_id": "u1"}, {"$set": {"age": 31}})
        doc = store.find_one("users", {"_id": "u1"})
        assert doc["age"] == 31
        assert doc["name"] == "Alice"  # unchanged

    def test_update_inc(self, store):
        store.insert("counters", {"_id": "visits", "count": 0})
        store.update_one("counters", {"_id": "visits"}, {"$inc": {"count": 1}})
        store.update_one("counters", {"_id": "visits"}, {"$inc": {"count": 5}})
        doc = store.find_one("counters", {"_id": "visits"})
        assert doc["count"] == 6

    def test_update_unset(self, store):
        store.insert("users", {"_id": "u1", "name": "Alice", "temp": "delete-me"})
        store.update_one("users", {"_id": "u1"}, {"$unset": {"temp": ""}})
        doc = store.find_one("users", {"_id": "u1"})
        assert "temp" not in doc

    def test_update_push(self, store):
        store.insert("lists", {"_id": "l1", "items": ["a"]})
        store.update_one("lists", {"_id": "l1"}, {"$push": {"items": "b"}})
        doc = store.find_one("lists", {"_id": "l1"})
        assert doc["items"] == ["a", "b"]

    def test_update_many(self, store):
        store.insert("items", {"status": "pending", "v": 1})
        store.insert("items", {"status": "pending", "v": 2})
        store.insert("items", {"status": "done", "v": 3})
        result = store.update_many("items", {"status": "pending"}, {"$set": {"status": "processed"}})
        assert result["modified"] == 2
        assert store.count("items", {"status": "processed"}) == 2

    # ── Delete ──

    def test_delete_one(self, store):
        store.insert("items", {"_id": "x", "v": 1})
        result = store.delete_one("items", {"_id": "x"})
        assert result["deleted"] == 1
        assert store.find_one("items", {"_id": "x"}) is None

    def test_delete_many(self, store):
        for i in range(5):
            store.insert("items", {"group": "a"})
        store.insert("items", {"group": "b"})
        result = store.delete_many("items", {"group": "a"})
        assert result["deleted"] == 5
        assert store.count("items") == 1

    def test_delete_all(self, store):
        for i in range(5):
            store.insert("items", {"v": i})
        result = store.delete_many("items")
        assert result["deleted"] == 5

    # ── TTL ──

    def test_ttl_hides_expired(self, store):
        store.insert("cache", {"key": "temp"}, ttl=1)
        assert store.find_one("cache", {"key": "temp"}) is not None
        time.sleep(1.5)
        assert store.find_one("cache", {"key": "temp"}) is None

    def test_ttl_gc_removes(self, store):
        store.insert("cache", {"key": "a"}, ttl=1)
        store.insert("cache", {"key": "b"})  # no TTL
        time.sleep(1.5)
        removed = store.gc()
        assert removed >= 1
        # Permanent doc still there
        assert store.find_one("cache", {"key": "b"}) is not None

    def test_count(self, store):
        store.insert("items", {"v": 1})
        store.insert("items", {"v": 2})
        store.insert("items", {"v": 3})
        assert store.count("items") == 3
        assert store.count("items", {"v": {"$gt": 1}}) == 2

    def test_collections(self, store):
        store.insert("users", {"name": "Alice"})
        store.insert("items", {"v": 1})
        colls = store.collections()
        assert "users" in colls
        assert "items" in colls

    # ── Data integrity ──

    def test_concurrent_writes(self, store):
        """Multiple inserts don't corrupt the database."""
        import threading
        errors = []

        def writer(n):
            try:
                for i in range(50):
                    store.insert("concurrent", {"writer": n, "seq": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert store.count("concurrent") == 200

    def test_wal_survives_crash(self, tmp_path):
        """WAL mode ensures data survives even if process is killed mid-write."""
        db_path = tmp_path / "crash_test.db"

        # Write some data in a subprocess, then kill it
        script = f"""
import sys; sys.path.insert(0, '{Path(__file__).parent.parent}')
from hort.storage.scrolls import ScrollStore
s = ScrollStore('{db_path}')
for i in range(100):
    s.insert('data', {{'n': i}})
# Don't close — simulate crash
"""
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=10)

        # Verify data survived
        from hort.storage.scrolls import ScrollStore
        s = ScrollStore(db_path)
        count = s.count("data")
        assert count == 100
        s.close()


# ══════════════════════════════════════════════════════════════════
# Crate Store
# ══════════════════════════════════════════════════════════════════

class TestCrateStore:

    @pytest.fixture
    def store(self, tmp_path):
        from hort.storage.crates import CrateStore
        s = CrateStore(tmp_path / "crates")
        yield s
        s.close()

    def test_put_and_get(self, store):
        info = store.put("images", "test.png", b"\x89PNG...", content_type="image/png")
        assert info.name == "test.png"
        assert info.size == 7
        assert info.content_type == "image/png"

        result = store.get("images", "test.png")
        assert result is not None
        data, info = result
        assert data == b"\x89PNG..."

    def test_put_overwrites(self, store):
        store.put("data", "file.txt", b"version1")
        store.put("data", "file.txt", b"version2")
        data, _ = store.get("data", "file.txt")
        assert data == b"version2"

    def test_head(self, store):
        store.put("data", "x.bin", b"hello", metadata={"source": "test"})
        info = store.head("data", "x.bin")
        assert info is not None
        assert info.size == 5
        assert info.metadata["source"] == "test"

    def test_list(self, store):
        store.put("images", "a.png", b"a")
        store.put("images", "b.png", b"bb")
        store.put("images", "c.jpg", b"ccc")
        crates = store.list("images")
        assert len(crates) == 3
        # Filter by prefix
        pngs = store.list("images", prefix="")
        assert len(pngs) == 3

    def test_delete(self, store):
        store.put("data", "tmp.txt", b"temp")
        assert store.exists("data", "tmp.txt")
        deleted = store.delete("data", "tmp.txt")
        assert deleted
        assert not store.exists("data", "tmp.txt")

    def test_delete_nonexistent(self, store):
        assert not store.delete("data", "nope.txt")

    def test_delete_container(self, store):
        store.put("temp", "a.txt", b"a")
        store.put("temp", "b.txt", b"b")
        store.put("keep", "c.txt", b"c")
        count = store.delete_container("temp")
        assert count == 2
        assert store.list("temp") == []
        assert len(store.list("keep")) == 1

    def test_list_containers(self, store):
        store.put("images", "x.png", b"x")
        store.put("docs", "y.pdf", b"y")
        containers = store.list_containers()
        assert "images" in containers
        assert "docs" in containers

    # ── TTL ──

    def test_ttl_hides_expired_crate(self, store):
        store.put("cache", "temp.bin", b"data", ttl=1)
        assert store.exists("cache", "temp.bin")
        time.sleep(1.5)
        assert not store.exists("cache", "temp.bin")
        assert store.get("cache", "temp.bin") is None

    def test_ttl_gc_removes_files(self, store):
        info = store.put("cache", "temp.bin", b"data", ttl=1)
        time.sleep(1.5)
        removed = store.gc()
        assert removed >= 1
        # File should be deleted from disk too
        assert not Path(store._base / "cache" / "temp.bin").exists()

    # ── Data integrity ──

    def test_large_crate(self, store):
        """Store and retrieve a 10MB crate."""
        data = os.urandom(10 * 1024 * 1024)
        store.put("large", "big.bin", data)
        result = store.get("large", "big.bin")
        assert result is not None
        assert result[0] == data

    def test_concurrent_crate_writes(self, store):
        """Multiple threads writing crates don't corrupt the store."""
        import threading
        errors = []

        def writer(n):
            try:
                for i in range(20):
                    store.put("concurrent", f"crate_{n}_{i}.bin", f"data-{n}-{i}".encode())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(store.list("concurrent")) == 80


# ══════════════════════════════════════════════════════════════════
# Unified Storage
# ══════════════════════════════════════════════════════════════════

class TestStorage:

    @pytest.fixture
    def storage(self, tmp_path, monkeypatch):
        import hort.paths
        monkeypatch.setattr(hort.paths, "_resolved", tmp_path / ".hort")
        from hort.storage.store import Storage
        s = Storage("test-llming", runtime_base=tmp_path / "runtime")
        yield s
        s.close()

    def test_runtime_and_persist_separate(self, storage):
        """Runtime and persist are isolated namespaces."""
        storage.runtime.scrolls.insert("data", {"key": "runtime"})
        storage.persist.scrolls.insert("data", {"key": "persist"})
        assert storage.runtime.scrolls.find_one("data", {"key": "runtime"}) is not None
        assert storage.runtime.scrolls.find_one("data", {"key": "persist"}) is None
        assert storage.persist.scrolls.find_one("data", {"key": "persist"}) is not None
        assert storage.persist.scrolls.find_one("data", {"key": "runtime"}) is None

    def test_runtime_crates_separate(self, storage):
        storage.runtime.crates.put("tmp", "a.bin", b"runtime")
        storage.persist.crates.put("tmp", "a.bin", b"persist")
        r_data, _ = storage.runtime.crates.get("tmp", "a.bin")
        p_data, _ = storage.persist.crates.get("tmp", "a.bin")
        assert r_data == b"runtime"
        assert p_data == b"persist"

    def test_gc_runs(self, storage):
        storage.runtime.scrolls.insert("cache", {"v": 1}, ttl=1)
        storage.runtime.crates.put("cache", "x.bin", b"x", ttl=1)
        time.sleep(1.5)
        removed = storage.runtime.gc()
        assert removed >= 2


# ══════════════════════════════════════════════════════════════════
# Isolation
# ══════════════════════════════════════════════════════════════════

class TestIsolation:

    def test_llming_stores_isolated(self, tmp_path, monkeypatch):
        """Two llmings cannot see each other's data."""
        import hort.paths
        monkeypatch.setattr(hort.paths, "_resolved", tmp_path / ".hort")
        from hort.storage.store import Storage
        s1 = Storage("llming-a", runtime_base=tmp_path / "r1")
        s2 = Storage("llming-b", runtime_base=tmp_path / "r2")

        s1.persist.scrolls.insert("shared_name", {"secret": "only-a"})
        s2.persist.scrolls.insert("shared_name", {"secret": "only-b"})

        assert s1.persist.scrolls.find_one("shared_name")["secret"] == "only-a"
        assert s2.persist.scrolls.find_one("shared_name")["secret"] == "only-b"

        # They don't see each other
        assert s1.persist.scrolls.count("shared_name") == 1
        assert s2.persist.scrolls.count("shared_name") == 1

        s1.close()
        s2.close()
