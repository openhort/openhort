from __future__ import annotations

from hort.peer2peer.device_tokens import DeviceTokenStore


def test_device_token_store_defaults_to_local_json(tmp_path) -> None:
    path = tmp_path / "tokens.json"
    store = DeviceTokenStore(path=path)

    token = store.create(label="Phone", app_name="App A", icon="https://example.com/icon.png")
    token_hash = store.hash_token(token)

    assert path.exists()
    assert store.verify_hash(token_hash)
    store.mark_seen(token_hash)
    devices = store.list_devices()
    assert devices == [
        {
            "token_hash": token_hash,
            "label": "Phone",
            "app_name": "App A",
            "icon": "https://example.com/icon.png",
            "created_at": devices[0]["created_at"],
            "last_seen": devices[0]["last_seen"],
        }
    ]
    assert devices[0]["last_seen"]
    assert store.revoke(token_hash)
    assert not store.verify_hash(token_hash)


def test_device_token_store_revoke_all(tmp_path) -> None:
    store = DeviceTokenStore(path=tmp_path / "tokens.json")
    store.create(label="A")
    store.create(label="B")

    assert len(store.list_devices()) == 2
    assert store.revoke_all() == 2
    assert store.list_devices() == []
