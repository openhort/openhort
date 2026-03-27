"""Reusable isolated execution sessions backed by Docker.

Provides create / resume / destroy lifecycle for sandboxed environments
with resource limits, persistent workspace (volumes), and metadata
tracking for automatic cleanup.

Architecture::

    SessionManager         Session (one per invocation)
    ┌──────────────┐      ┌──────────────────────────────────┐
    │ create()     │─────►│ Container: ohsb-<id>             │
    │ get()        │      │ Volume:    ohvol-<id> → /workspace│
    │ list()       │      │ Meta:      ~/.openhort/sessions/ │
    │ destroy()    │      │                                  │
    │ image_ready()│      │ start() / stop() / destroy()     │
    │ build_image()│      │ exec() / exec_streaming()        │
    └──────────────┘      │ write_file()                     │
                          └──────────────────────────────────┘

State persistence:
    Container filesystem is ephemeral.  All durable state lives in
    the named volume mounted at ``/workspace``.  Stopping a container
    preserves the volume; destroying removes both.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

CONTAINER_PREFIX = "ohsb"
VOLUME_PREFIX = "ohvol"
BASE_IMAGE = "openhort-sandbox-base:latest"
BASE_DOCKERFILE_DIR = str(Path(__file__).resolve().parent)
DEFAULT_IMAGE = BASE_IMAGE
DEFAULT_STORE = Path.home() / ".openhort" / "sessions"


class SessionConfig(BaseModel):
    """Resource and environment configuration for a sandbox session."""

    image: str = DEFAULT_IMAGE
    memory: str | None = None
    cpus: float | None = None
    disk: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    secret_env: dict[str, str] = Field(
        default_factory=dict,
        exclude=True,
    )
    timeout_minutes: int = 60


class SessionMeta(BaseModel):
    """Persisted metadata for a sandbox session."""

    id: str
    container_name: str
    volume_name: str
    config: SessionConfig
    created_at: str
    last_active: str
    user_data: dict[str, Any] = Field(default_factory=dict)


class Session:
    """A single isolated execution session.

    Each session owns one Docker container and one named volume.
    The container can be stopped and re-started (resume); the volume
    survives across restarts.  ``destroy()`` removes everything.
    """

    def __init__(self, meta: SessionMeta, store_dir: Path) -> None:
        self.meta = meta
        self._store_dir = store_dir
        self._meta_path = store_dir / f"{meta.id}.json"

    @property
    def id(self) -> str:
        return self.meta.id

    @property
    def container_name(self) -> str:
        return self.meta.container_name

    @property
    def volume_name(self) -> str:
        return self.meta.volume_name

    # ── State queries ──────────────────────────────────────────────

    def is_running(self) -> bool:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}",
             self.container_name],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"

    def container_exists(self) -> bool:
        result = subprocess.run(
            ["docker", "inspect", self.container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self) -> None:
        """Start (or create) the container."""
        if self.is_running():
            self._touch()
            return

        if self.container_exists():
            subprocess.run(
                ["docker", "start", self.container_name],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        else:
            cmd = self._build_run_cmd()
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)

        self._touch()

    def stop(self) -> None:
        """Stop the container.  Volume and metadata are preserved."""
        if self.is_running():
            subprocess.run(
                ["docker", "stop", "-t", "5", self.container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        self._touch()

    def destroy(self) -> None:
        """Remove container, volume, and metadata file."""
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["docker", "volume", "rm", "-f", self.volume_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._meta_path.unlink(missing_ok=True)

    # ── Execution ──────────────────────────────────────────────────

    def _exec_prefix(self) -> list[str]:
        """Build ``docker exec`` prefix with per-process secret injection.

        Secrets from ``SessionConfig.secret_env`` are injected via
        ``docker exec -e KEY=VAL`` so they're only visible to the
        spawned process — NOT in the container environment, NOT in
        ``docker inspect``, and NOT readable from ``/proc/1/environ``
        by MCP servers or other processes in the container.
        """
        prefix = ["docker", "exec"]
        for key, val in self.meta.config.secret_env.items():
            prefix.extend(["-e", f"{key}={val}"])
        prefix.extend(["-i", self.container_name])
        return prefix

    def exec(
        self, cmd: list[str], **kwargs: Any,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run a command and wait for it to finish."""
        self._ensure_running()
        result = subprocess.run(
            [*self._exec_prefix(), *cmd],
            **kwargs,
        )
        self._touch()
        return result

    def exec_streaming(self, cmd: list[str]) -> subprocess.Popen[bytes]:
        """Run a command with stdout piped for streaming reads."""
        self._ensure_running()
        proc = subprocess.Popen(
            [*self._exec_prefix(), *cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        self._touch()
        return proc

    # ── File I/O ───────────────────────────────────────────────────

    def write_file(self, path: str, content: str | bytes) -> None:
        """Write a file inside the container."""
        self._ensure_running()
        data = content.encode() if isinstance(content, str) else content
        subprocess.run(
            ["docker", "exec", "-i", self.container_name,
             "bash", "-c", f"cat > {path}"],
            input=data,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # ── Internals ──────────────────────────────────────────────────

    def _ensure_running(self) -> None:
        if not self.is_running():
            self.start()

    def _build_run_cmd(self) -> list[str]:
        cfg = self.meta.config
        cmd = [
            "docker", "run", "-d",
            "--name", self.container_name,
            "-v", f"{self.volume_name}:/workspace",
            "--add-host=host.docker.internal:host-gateway",
        ]
        for key, val in cfg.env.items():
            cmd.extend(["-e", f"{key}={val}"])
        if cfg.memory:
            cmd.extend(["--memory", cfg.memory])
        if cfg.cpus is not None:
            cmd.extend(["--cpus", str(cfg.cpus)])
        if cfg.disk:
            cmd.extend(["--storage-opt", f"size={cfg.disk}"])
        cmd.append(cfg.image)
        return cmd

    def _touch(self) -> None:
        self.meta.last_active = datetime.now(timezone.utc).isoformat()
        self._save()

    def _save(self) -> None:
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._meta_path.write_text(self.meta.model_dump_json(indent=2))


class SessionManager:
    """Registry and factory for sandbox sessions."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self.store_dir = store_dir or DEFAULT_STORE
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def create(self, config: SessionConfig | None = None) -> Session:
        """Create a new session (does not start the container)."""
        config = config or SessionConfig()
        sid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        meta = SessionMeta(
            id=sid,
            container_name=f"{CONTAINER_PREFIX}-{sid}",
            volume_name=f"{VOLUME_PREFIX}-{sid}",
            config=config,
            created_at=now,
            last_active=now,
        )
        session = Session(meta, self.store_dir)
        session._save()
        return session

    def get(self, session_id: str) -> Session | None:
        """Load a session by ID.  Returns None if not found."""
        path = self.store_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            meta = SessionMeta.model_validate(data)
            return Session(meta, self.store_dir)
        except (json.JSONDecodeError, Exception):
            return None

    def list_sessions(self) -> list[Session]:
        """Return all known sessions, newest first."""
        sessions: list[Session] = []
        for path in self.store_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                meta = SessionMeta.model_validate(data)
                sessions.append(Session(meta, self.store_dir))
            except (json.JSONDecodeError, Exception):
                continue
        sessions.sort(key=lambda s: s.meta.last_active, reverse=True)
        return sessions

    def destroy(self, session_id: str) -> bool:
        """Destroy a session by ID.  Returns True if it existed."""
        session = self.get(session_id)
        if session is None:
            return False
        session.destroy()
        return True

    # ── Image management ───────────────────────────────────────────

    @staticmethod
    def image_ready(image: str = DEFAULT_IMAGE) -> bool:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    @staticmethod
    def ensure_base_image() -> None:
        """Build the sandbox base image if it doesn't exist."""
        if not SessionManager.image_ready(BASE_IMAGE):
            SessionManager.build_image(BASE_IMAGE, BASE_DOCKERFILE_DIR)

    @staticmethod
    def build_image(
        image: str,
        dockerfile_dir: str,
    ) -> None:
        print(f"Building {image} ...", flush=True)
        subprocess.run(
            ["docker", "build", "-t", image, dockerfile_dir],
            check=True,
        )
        print("Image ready.\n")
