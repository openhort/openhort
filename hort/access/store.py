"""User and host storage — supports JSON file or MongoDB."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hort.access.auth import generate_connection_key, hash_password

logger = logging.getLogger(__name__)


@dataclass
class UserRecord:
    """A registered user."""

    username: str
    password_hash: str
    display_name: str = ""
    created_at: str = ""


@dataclass
class HostRecord:
    """A registered openhort host."""

    host_id: str
    connection_key: str
    owner: str  # username
    display_name: str = ""
    created_at: str = ""


class Store(ABC):
    """Abstract storage backend."""

    @abstractmethod
    def get_user(self, username: str) -> UserRecord | None: ...

    @abstractmethod
    def create_user(self, username: str, password_hash: str, display_name: str = "") -> UserRecord: ...

    @abstractmethod
    def list_users(self) -> list[UserRecord]: ...

    @abstractmethod
    def get_host_by_key(self, connection_key: str) -> HostRecord | None: ...

    @abstractmethod
    def get_hosts_for_user(self, username: str) -> list[HostRecord]: ...

    @abstractmethod
    def create_host(self, owner: str, display_name: str = "") -> HostRecord: ...

    @abstractmethod
    def remove_host(self, host_id: str) -> bool: ...


class FileStore(Store):
    """JSON file-based storage."""

    def __init__(self, path: str | Path = "hort-access.json") -> None:
        self._path = Path(path)
        self._data: dict[str, Any] = {"users": {}, "hosts": {}}
        if self._path.exists():
            self._data = json.loads(self._path.read_text())

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2))

    def get_user(self, username: str) -> UserRecord | None:
        u = self._data["users"].get(username)
        if u is None:
            return None
        return UserRecord(username=username, **u)

    def create_user(self, username: str, password_hash: str, display_name: str = "") -> UserRecord:
        import datetime

        self._data["users"][username] = {
            "password_hash": password_hash,
            "display_name": display_name or username,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        self._save()
        return self.get_user(username)  # type: ignore[return-value]

    def list_users(self) -> list[UserRecord]:
        return [
            UserRecord(username=k, **v) for k, v in self._data["users"].items()
        ]

    def get_host_by_key(self, connection_key: str) -> HostRecord | None:
        for hid, h in self._data["hosts"].items():
            if h.get("connection_key") == connection_key:
                return HostRecord(host_id=hid, **h)
        return None

    def get_hosts_for_user(self, username: str) -> list[HostRecord]:
        return [
            HostRecord(host_id=hid, **h)
            for hid, h in self._data["hosts"].items()
            if h.get("owner") == username
        ]

    def create_host(self, owner: str, display_name: str = "") -> HostRecord:
        import datetime
        import secrets

        host_id = secrets.token_urlsafe(12)
        key = generate_connection_key()
        self._data["hosts"][host_id] = {
            "connection_key": key,
            "owner": owner,
            "display_name": display_name or f"Host {host_id[:6]}",
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        self._save()
        return self.get_host_by_key(key)  # type: ignore[return-value]

    def remove_host(self, host_id: str) -> bool:
        if host_id in self._data["hosts"]:
            del self._data["hosts"][host_id]
            self._save()
            return True
        return False


class MongoStore(Store):
    """MongoDB-based storage (requires pymongo)."""

    def __init__(self, uri: str = "mongodb://localhost:27017", db_name: str = "hort_access") -> None:
        try:
            from pymongo import MongoClient  # type: ignore[import-not-found]

            self._client = MongoClient(uri)
            self._db = self._client[db_name]
            self._users = self._db["users"]
            self._hosts = self._db["hosts"]
        except ImportError:
            raise ImportError("pymongo is required for MongoDB storage: pip install pymongo")

    def get_user(self, username: str) -> UserRecord | None:
        doc = self._users.find_one({"username": username})
        if doc is None:
            return None
        return UserRecord(
            username=doc["username"],
            password_hash=doc["password_hash"],
            display_name=doc.get("display_name", ""),
            created_at=doc.get("created_at", ""),
        )

    def create_user(self, username: str, password_hash: str, display_name: str = "") -> UserRecord:
        import datetime

        self._users.insert_one({
            "username": username,
            "password_hash": password_hash,
            "display_name": display_name or username,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        })
        return self.get_user(username)  # type: ignore[return-value]

    def list_users(self) -> list[UserRecord]:
        return [
            UserRecord(
                username=doc["username"],
                password_hash=doc["password_hash"],
                display_name=doc.get("display_name", ""),
                created_at=doc.get("created_at", ""),
            )
            for doc in self._users.find()
        ]

    def get_host_by_key(self, connection_key: str) -> HostRecord | None:
        doc = self._hosts.find_one({"connection_key": connection_key})
        if doc is None:
            return None
        return HostRecord(
            host_id=str(doc["_id"]),
            connection_key=doc["connection_key"],
            owner=doc["owner"],
            display_name=doc.get("display_name", ""),
            created_at=doc.get("created_at", ""),
        )

    def get_hosts_for_user(self, username: str) -> list[HostRecord]:
        return [
            HostRecord(
                host_id=str(doc["_id"]),
                connection_key=doc["connection_key"],
                owner=doc["owner"],
                display_name=doc.get("display_name", ""),
                created_at=doc.get("created_at", ""),
            )
            for doc in self._hosts.find({"owner": username})
        ]

    def create_host(self, owner: str, display_name: str = "") -> HostRecord:
        import datetime

        key = generate_connection_key()
        self._hosts.insert_one({
            "connection_key": key,
            "owner": owner,
            "display_name": display_name or "My Host",
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        })
        return self.get_host_by_key(key)  # type: ignore[return-value]

    def remove_host(self, host_id: str) -> bool:
        from bson import ObjectId  # type: ignore[import-not-found]

        result = self._hosts.delete_one({"_id": ObjectId(host_id)})
        ok: bool = result.deleted_count > 0
        return ok
