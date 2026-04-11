"""Vault tests — shelves, holds, scopes, cross-llming access, pulse routing."""

from __future__ import annotations

import time

import pytest


@pytest.fixture
def storage(tmp_path, monkeypatch):
    import hort.paths
    monkeypatch.setattr(hort.paths, "_resolved", tmp_path / ".hort")
    from hort.storage.store import Storage
    s = Storage("test-llming", runtime_base=tmp_path / "runtime")
    yield s
    s.close()


@pytest.fixture
def storage_pair(tmp_path, monkeypatch):
    """Two isolated llming storages for cross-llming tests."""
    import hort.paths
    monkeypatch.setattr(hort.paths, "_resolved", tmp_path / ".hort")
    from hort.storage.store import Storage, StorageManager
    # Reset singleton
    StorageManager._instance = None
    mgr = StorageManager.get()
    s1 = mgr.get_storage("llming-a")
    s2 = mgr.get_storage("llming-b")
    yield s1, s2, mgr
    mgr.close_all()
    StorageManager._instance = None


# ══════════════════════════════════════════════════════════════
# Vault basics
# ══════════════════════════════════════════════════════════════

class TestVault:

    def test_create_vault(self, storage):
        v = storage.persist.vault("main")
        assert v.name == "main"
        assert v.group == "private"

    def test_vault_with_metadata(self, storage):
        v = storage.persist.vault("metrics", group="public", description="System metrics")
        assert v.group == "public"
        assert v.description == "System metrics"

    def test_list_vaults(self, storage):
        storage.persist.vault("a", group="public")
        storage.persist.vault("b", group="shared", description="Shared data")
        vaults = storage.persist.list_vaults()
        names = [v["name"] for v in vaults]
        assert "a" in names
        assert "b" in names

    def test_vault_reuse(self, storage):
        v1 = storage.persist.vault("main")
        v2 = storage.persist.vault("main")
        assert v1 is v2


# ══════════════════════════════════════════════════════════════
# Shelves (scroll collections)
# ══════════════════════════════════════════════════════════════

class TestShelf:

    def test_insert_and_find(self, storage):
        shelf = storage.persist.vault("main").shelf("users")
        shelf.insert({"name": "Alice", "age": 30})
        doc = shelf.find_one({"name": "Alice"})
        assert doc["age"] == 30

    def test_multiple_shelves_isolated(self, storage):
        vault = storage.persist.vault("main")
        vault.shelf("users").insert({"name": "Alice"})
        vault.shelf("items").insert({"name": "Sword"})
        assert vault.shelf("users").count() == 1
        assert vault.shelf("items").count() == 1
        assert vault.shelf("users").find_one()["name"] == "Alice"
        assert vault.shelf("items").find_one()["name"] == "Sword"

    def test_multiple_vaults_isolated(self, storage):
        storage.persist.vault("v1").shelf("data").insert({"v": 1})
        storage.persist.vault("v2").shelf("data").insert({"v": 2})
        assert storage.persist.vault("v1").shelf("data").find_one()["v"] == 1
        assert storage.persist.vault("v2").shelf("data").find_one()["v"] == 2

    def test_update_delete(self, storage):
        shelf = storage.persist.vault("main").shelf("items")
        shelf.insert({"_id": "x", "status": "new"})
        shelf.update_one({"_id": "x"}, {"$set": {"status": "done"}})
        assert shelf.find_one({"_id": "x"})["status"] == "done"
        shelf.delete_one({"_id": "x"})
        assert shelf.find_one({"_id": "x"}) is None

    def test_shelf_with_ttl(self, storage):
        shelf = storage.runtime.vault("cache").shelf("temp")
        shelf.insert({"key": "ephemeral"}, ttl=1)
        assert shelf.find_one({"key": "ephemeral"}) is not None
        time.sleep(1.5)
        assert shelf.find_one({"key": "ephemeral"}) is None


# ══════════════════════════════════════════════════════════════
# Scopes (filtered views)
# ══════════════════════════════════════════════════════════════

class TestScope:

    def test_scope_filters(self, storage):
        shelf = storage.persist.vault("main").shelf("tasks")
        shelf.insert({"title": "Fix bug", "status": "done"})
        shelf.insert({"title": "Add feature", "status": "todo"})
        shelf.insert({"title": "Write docs", "status": "todo"})

        todo = shelf.scope("todo", {"status": "todo"})
        assert todo.count() == 2
        assert todo.find_one()["status"] == "todo"

        done = shelf.scope("done", {"status": "done"})
        assert done.count() == 1

    def test_scope_with_extra_filter(self, storage):
        shelf = storage.persist.vault("main").shelf("items")
        shelf.insert({"type": "fruit", "name": "apple"})
        shelf.insert({"type": "fruit", "name": "banana"})
        shelf.insert({"type": "veggie", "name": "carrot"})

        fruits = shelf.scope("fruits", {"type": "fruit"})
        apple = fruits.find_one({"name": "apple"})
        assert apple["name"] == "apple"


# ══════════════════════════════════════════════════════════════
# Holds (crate containers)
# ══════════════════════════════════════════════════════════════

class TestHold:

    def test_put_and_get(self, storage):
        hold = storage.persist.vault("exports").hold("images")
        hold.put("test.png", b"\x89PNG...", content_type="image/png")
        result = hold.get("test.png")
        assert result is not None
        data, info = result
        assert data == b"\x89PNG..."

    def test_multiple_holds_isolated(self, storage):
        vault = storage.persist.vault("data")
        vault.hold("images").put("a.png", b"image")
        vault.hold("docs").put("a.pdf", b"pdf")
        assert vault.hold("images").exists("a.png")
        assert not vault.hold("images").exists("a.pdf")
        assert vault.hold("docs").exists("a.pdf")

    def test_list_and_delete(self, storage):
        hold = storage.persist.vault("tmp").hold("cache")
        hold.put("a.bin", b"a")
        hold.put("b.bin", b"b")
        assert len(hold.list()) == 2
        hold.delete("a.bin")
        assert len(hold.list()) == 1

    def test_hold_with_ttl(self, storage):
        hold = storage.runtime.vault("cache").hold("frames")
        hold.put("frame.webp", b"webp", ttl=1)
        assert hold.exists("frame.webp")
        time.sleep(1.5)
        assert not hold.exists("frame.webp")


# ══════════════════════════════════════════════════════════════
# Cross-llming access
# ══════════════════════════════════════════════════════════════

class TestCrossAccess:

    def test_public_vault_accessible(self, storage_pair):
        s1, s2, mgr = storage_pair
        s1.persist.vault("metrics", group="public").shelf("cpu").insert({"value": 42})

        # Another llming can access public vault
        vault = mgr.get_vault("llming-a", "metrics")
        assert vault is not None
        assert vault.group == "public"

    def test_private_vault_listed(self, storage_pair):
        s1, s2, mgr = storage_pair
        s1.persist.vault("secrets", group="private")
        s1.persist.vault("metrics", group="public")
        vaults = mgr.list_vaults("llming-a")
        groups = {v["name"]: v["group"] for v in vaults}
        assert groups["secrets"] == "private"
        assert groups["metrics"] == "public"

    def test_vaults_per_llming_isolated(self, storage_pair):
        s1, s2, mgr = storage_pair
        s1.persist.vault("data").shelf("items").insert({"owner": "a"})
        s2.persist.vault("data").shelf("items").insert({"owner": "b"})
        assert s1.persist.vault("data").shelf("items").find_one()["owner"] == "a"
        assert s2.persist.vault("data").shelf("items").find_one()["owner"] == "b"


# ══════════════════════════════════════════════════════════════
# Pulse routing
# ══════════════════════════════════════════════════════════════

class TestPulseRouting:

    def test_route_scroll_into_shelf(self, storage):
        from hort.storage.pulses import PulseRouter
        router = PulseRouter()
        shelf = storage.persist.vault("metrics").shelf("history")
        router.route("cpu_load", into_shelf=shelf, ttl=3600)

        router.handle("cpu_load", {"cpu": 42.5, "mem": 80})
        router.handle("cpu_load", {"cpu": 43.0, "mem": 81})

        scrolls = shelf.find()
        assert len(scrolls) == 2
        assert scrolls[0]["cpu"] == 42.5
        assert "_routed_at" in scrolls[0]
        assert scrolls[0]["_pulse"] == "cpu_load"

    def test_route_crate_into_hold(self, storage):
        from hort.storage.pulses import PulseRouter
        router = PulseRouter()
        hold = storage.runtime.vault("feeds").hold("frames")
        router.route("camera_frame", into_hold=hold, ttl=60)

        router.handle("camera_frame", {
            "crate": {"name": "frame_001.webp", "data": b"\x00\x01\x02", "content_type": "image/webp"},
        })

        crates = hold.list()
        assert len(crates) == 1
        assert crates[0].name == "frame_001.webp"

    def test_route_unified_pulse(self, storage):
        """Unified pulse with both scroll and crate data."""
        from hort.storage.pulses import PulseRouter
        router = PulseRouter()
        vault = storage.persist.vault("security")
        router.route("motion_event",
            into_shelf=vault.shelf("events"),
            into_hold=vault.hold("snapshots"),
        )

        router.handle("motion_event", {
            "scroll": {"camera": "front", "motion": True, "confidence": 0.95},
            "crate": {"name": "snap.jpg", "data": b"\xff\xd8\xff", "content_type": "image/jpeg"},
        })

        events = vault.shelf("events").find()
        assert len(events) == 1
        assert events[0]["camera"] == "front"
        assert events[0]["motion"] is True

        snaps = vault.hold("snapshots").list()
        assert len(snaps) == 1
        assert snaps[0].name == "snap.jpg"

    def test_unrouted_pulse_ignored(self, storage):
        from hort.storage.pulses import PulseRouter
        router = PulseRouter()
        router.handle("unknown_pulse", {"data": "ignored"})
        # No error, just ignored

    def test_route_with_ttl(self, storage):
        from hort.storage.pulses import PulseRouter
        router = PulseRouter()
        shelf = storage.runtime.vault("cache").shelf("recent")
        router.route("heartbeat", into_shelf=shelf, ttl=1)

        router.handle("heartbeat", {"alive": True})
        assert shelf.count() == 1
        time.sleep(1.5)
        assert shelf.count() == 0


# ══════════════════════════════════════════════════════════════
# Pulse registry (peek, subscribe, available)
# ══════════════════════════════════════════════════════════════

class TestPulseRegistry:

    def test_register_and_available(self):
        from hort.storage.pulses import PulseRegistry
        reg = PulseRegistry()
        reg.register("system-monitor", "cpu_load", group="public")
        reg.register("system-monitor", "process_list", group="shared")
        reg.register("system-monitor", "internal_debug", group="private")

        # Public viewer sees public + shared, not private
        available = reg.available(viewer_llming="telegram")
        names = [p["name"] for p in available]
        assert "cpu_load" in names
        assert "process_list" in names
        assert "internal_debug" not in names

        # Owner sees everything
        available = reg.available(viewer_llming="system-monitor")
        names = [p["name"] for p in available]
        assert "internal_debug" in names

    def test_peek(self):
        from hort.storage.pulses import PulseRegistry
        reg = PulseRegistry()
        reg.register("system-monitor", "cpu_load")
        reg.update("system-monitor", "cpu_load", 42.5)

        latest = reg.peek("system-monitor", "cpu_load")
        assert latest["value"] == 42.5
        assert "_ts" in latest

    def test_peek_nonexistent(self):
        from hort.storage.pulses import PulseRegistry
        reg = PulseRegistry()
        assert reg.peek("nope", "nope") is None

    def test_subscribe_unsubscribe(self):
        from hort.storage.pulses import PulseRegistry
        reg = PulseRegistry()
        reg.register("llming-cam", "camera_frame")

        assert not reg.subscribed("telegram", "llming-cam", "camera_frame")
        reg.subscribe("telegram", "llming-cam", "camera_frame")
        assert reg.subscribed("telegram", "llming-cam", "camera_frame")
        reg.unsubscribe("telegram", "llming-cam", "camera_frame")
        assert not reg.subscribed("telegram", "llming-cam", "camera_frame")

    def test_available_shows_subscription_status(self):
        from hort.storage.pulses import PulseRegistry
        reg = PulseRegistry()
        reg.register("system-monitor", "cpu_load")
        reg.subscribe("telegram", "system-monitor", "cpu_load")

        available = reg.available(viewer_llming="telegram")
        assert available[0]["subscribed"] is True

        available = reg.available(viewer_llming="other")
        assert available[0]["subscribed"] is False
