"""Tests for hort.containers — base types, registry, and Docker provider."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from hort.containers.base import (
    ContainerConfig,
    ContainerInfo,
    ContainerProvider,
    ExecResult,
    MountConfig,
)
from hort.containers.docker import DockerProvider, _run
from hort.containers.registry import ContainerRegistry


# ===== Data model tests =====


class TestDataModels:
    def test_mount_config(self) -> None:
        m = MountConfig(host_path="/host", container_path="/app")
        assert m.host_path == "/host"
        assert m.read_only is False

    def test_mount_config_readonly(self) -> None:
        m = MountConfig(host_path="/h", container_path="/c", read_only=True)
        assert m.read_only is True

    def test_container_config_defaults(self) -> None:
        c = ContainerConfig(name="test", image="python:3.12")
        assert c.name == "test"
        assert c.command is None
        assert c.ports == {}
        assert c.env == {}
        assert c.mounts == []
        assert c.working_dir == "/app"
        assert c.memory_mb == 512
        assert c.cpu_count == 1.0

    def test_container_config_full(self) -> None:
        c = ContainerConfig(
            name="app",
            image="node:20",
            command="npm start",
            ports={3000: 3000},
            env={"NODE_ENV": "production"},
            mounts=[MountConfig("/src", "/app")],
            working_dir="/app",
            memory_mb=1024,
            cpu_count=2.0,
        )
        assert c.command == "npm start"
        assert c.ports == {3000: 3000}
        assert len(c.mounts) == 1

    def test_container_info(self) -> None:
        i = ContainerInfo(
            container_id="abc123",
            name="test",
            status="running",
            image="python:3.12",
            ports={8000: 9000},
            provider="docker",
            url="http://localhost:9000",
        )
        assert i.container_id == "abc123"
        assert i.url == "http://localhost:9000"

    def test_container_info_defaults(self) -> None:
        i = ContainerInfo(
            container_id="x", name="y", status="created", image="z"
        )
        assert i.ports == {}
        assert i.provider == "docker"
        assert i.url is None

    def test_exec_result(self) -> None:
        r = ExecResult(exit_code=0, stdout="hello", stderr="")
        assert r.exit_code == 0
        assert r.stdout == "hello"


# ===== Registry tests =====


class TestContainerRegistry:
    def setup_method(self) -> None:
        ContainerRegistry.reset()

    def test_singleton(self) -> None:
        r1 = ContainerRegistry.get()
        r2 = ContainerRegistry.get()
        assert r1 is r2

    def test_reset(self) -> None:
        r1 = ContainerRegistry.get()
        ContainerRegistry.reset()
        r2 = ContainerRegistry.get()
        assert r1 is not r2

    def test_track_and_get(self) -> None:
        reg = ContainerRegistry.get()
        info = ContainerInfo(
            container_id="c1", name="test", status="running", image="img"
        )
        reg.track(info)
        assert reg.get_container("c1") is info

    def test_get_missing(self) -> None:
        assert ContainerRegistry.get().get_container("nope") is None

    def test_untrack(self) -> None:
        reg = ContainerRegistry.get()
        info = ContainerInfo(
            container_id="c1", name="t", status="running", image="i"
        )
        reg.track(info)
        removed = reg.untrack("c1")
        assert removed is info
        assert reg.get_container("c1") is None

    def test_untrack_missing(self) -> None:
        assert ContainerRegistry.get().untrack("nope") is None

    def test_list_all(self) -> None:
        reg = ContainerRegistry.get()
        reg.track(ContainerInfo(
            container_id="c1", name="a", status="running", image="i"
        ))
        reg.track(ContainerInfo(
            container_id="c2", name="b", status="stopped", image="i"
        ))
        assert len(reg.list_all()) == 2

    def test_register_provider(self) -> None:
        reg = ContainerRegistry.get()
        provider = DockerProvider()
        reg.register_provider(provider)
        assert reg.get_provider("docker") is provider
        assert reg.get_provider("azure") is None

    def test_provider_for(self) -> None:
        reg = ContainerRegistry.get()
        provider = DockerProvider()
        reg.register_provider(provider)
        info = ContainerInfo(
            container_id="c1", name="t", status="running",
            image="i", provider="docker",
        )
        reg.track(info)
        assert reg.provider_for("c1") is provider

    def test_provider_for_missing(self) -> None:
        assert ContainerRegistry.get().provider_for("nope") is None

    def test_provider_for_unknown_provider(self) -> None:
        reg = ContainerRegistry.get()
        info = ContainerInfo(
            container_id="c1", name="t", status="running",
            image="i", provider="unknown",
        )
        reg.track(info)
        assert reg.provider_for("c1") is None


# ===== Docker provider tests =====


def _mock_run(exit_code: int = 0, stdout: str = "", stderr: str = "") -> Any:
    """Create an async mock for _run."""
    return AsyncMock(return_value=ExecResult(
        exit_code=exit_code, stdout=stdout, stderr=stderr
    ))


class TestDockerProvider:
    def test_provider_name(self) -> None:
        assert DockerProvider().provider_name == "docker"

    @pytest.mark.asyncio
    async def test_create(self) -> None:
        mock = _mock_run(stdout="abc123def456\n")
        with patch("hort.containers.docker._run", mock):
            provider = DockerProvider()
            info = await provider.create(ContainerConfig(
                name="test-app",
                image="python:3.12",
                ports={8000: 0},  # 0 = auto-offset
                env={"DEBUG": "1"},
                mounts=[MountConfig("/src", "/app")],
            ))
        assert info.container_id == "abc123def456"
        assert info.name == "test-app"
        assert info.status == "created"
        assert info.ports == {8000: 9000}  # 8000 + 1000 offset
        assert info.provider == "docker"

        # Verify docker create was called with correct args
        call_args = mock.call_args[0][0]
        assert "docker" in call_args
        assert "create" in call_args
        assert "--name" in call_args
        assert "test-app" in call_args
        assert "python:3.12" in call_args

    @pytest.mark.asyncio
    async def test_create_with_explicit_port(self) -> None:
        mock = _mock_run(stdout="abc123\n")
        with patch("hort.containers.docker._run", mock):
            provider = DockerProvider()
            info = await provider.create(ContainerConfig(
                name="t", image="i", ports={3000: 3000}
            ))
        assert info.ports == {3000: 3000}

    @pytest.mark.asyncio
    async def test_create_with_command(self) -> None:
        mock = _mock_run(stdout="abc123\n")
        with patch("hort.containers.docker._run", mock):
            provider = DockerProvider()
            await provider.create(ContainerConfig(
                name="t", image="i", command="npm start"
            ))
        call_args = mock.call_args[0][0]
        assert "sh" in call_args
        assert "-c" in call_args
        assert "npm start" in call_args

    @pytest.mark.asyncio
    async def test_create_readonly_mount(self) -> None:
        mock = _mock_run(stdout="abc123\n")
        with patch("hort.containers.docker._run", mock):
            provider = DockerProvider()
            await provider.create(ContainerConfig(
                name="t", image="i",
                mounts=[MountConfig("/h", "/c", read_only=True)],
            ))
        call_args = mock.call_args[0][0]
        assert any(":ro" in a for a in call_args)

    @pytest.mark.asyncio
    async def test_start(self) -> None:
        mock = _mock_run()
        with patch("hort.containers.docker._run", mock):
            assert await DockerProvider().start("abc") is True

    @pytest.mark.asyncio
    async def test_start_failure(self) -> None:
        mock = _mock_run(exit_code=1)
        with patch("hort.containers.docker._run", mock):
            assert await DockerProvider().start("abc") is False

    @pytest.mark.asyncio
    async def test_stop(self) -> None:
        mock = _mock_run()
        with patch("hort.containers.docker._run", mock):
            assert await DockerProvider().stop("abc") is True

    @pytest.mark.asyncio
    async def test_destroy(self) -> None:
        mock = _mock_run()
        with patch("hort.containers.docker._run", mock):
            assert await DockerProvider().destroy("abc") is True
        assert mock.call_count == 2  # stop + rm

    @pytest.mark.asyncio
    async def test_exec(self) -> None:
        mock = _mock_run(stdout="hello world\n")
        with patch("hort.containers.docker._run", mock):
            result = await DockerProvider().exec("abc", "echo hello world")
        assert result.stdout == "hello world\n"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_get_info(self) -> None:
        inspect_data = {
            "State": {"Running": True},
            "Name": "/my-app",
            "Config": {"Image": "python:3.12"},
            "HostConfig": {
                "PortBindings": {
                    "8000/tcp": [{"HostPort": "9000"}]
                }
            },
        }
        mock = _mock_run(stdout=json.dumps(inspect_data))
        with patch("hort.containers.docker._run", mock):
            info = await DockerProvider().get_info("abc")
        assert info is not None
        assert info.status == "running"
        assert info.name == "my-app"
        assert info.ports == {8000: 9000}

    @pytest.mark.asyncio
    async def test_get_info_stopped(self) -> None:
        inspect_data = {
            "State": {"Running": False},
            "Name": "/stopped",
            "Config": {"Image": "img"},
            "HostConfig": {"PortBindings": None},
        }
        mock = _mock_run(stdout=json.dumps(inspect_data))
        with patch("hort.containers.docker._run", mock):
            info = await DockerProvider().get_info("abc")
        assert info is not None
        assert info.status == "stopped"
        assert info.ports == {}

    @pytest.mark.asyncio
    async def test_get_info_not_found(self) -> None:
        mock = _mock_run(exit_code=1)
        with patch("hort.containers.docker._run", mock):
            assert await DockerProvider().get_info("nope") is None

    @pytest.mark.asyncio
    async def test_get_info_bad_json(self) -> None:
        mock = _mock_run(stdout="not json")
        with patch("hort.containers.docker._run", mock):
            assert await DockerProvider().get_info("abc") is None

    @pytest.mark.asyncio
    async def test_list_containers(self) -> None:
        output = "abc123\tmy-app\tUp 5 minutes\tpython:3.12\ndef456\tother\tExited (0)\tnode:20\n"
        mock = _mock_run(stdout=output)
        with patch("hort.containers.docker._run", mock):
            containers = await DockerProvider().list_containers()
        assert len(containers) == 2
        assert containers[0].status == "running"
        assert containers[1].status == "stopped"

    @pytest.mark.asyncio
    async def test_list_containers_malformed_line(self) -> None:
        output = "abc123\tmy-app\tUp 5 minutes\tpython:3.12\nbadline\n"
        mock = _mock_run(stdout=output)
        with patch("hort.containers.docker._run", mock):
            containers = await DockerProvider().list_containers()
        assert len(containers) == 1

    @pytest.mark.asyncio
    async def test_list_containers_empty(self) -> None:
        mock = _mock_run(stdout="")
        with patch("hort.containers.docker._run", mock):
            assert await DockerProvider().list_containers() == []

    @pytest.mark.asyncio
    async def test_list_containers_error(self) -> None:
        mock = _mock_run(exit_code=1)
        with patch("hort.containers.docker._run", mock):
            assert await DockerProvider().list_containers() == []

    @pytest.mark.asyncio
    async def test_get_url(self) -> None:
        inspect_data = {
            "State": {"Running": True},
            "Name": "/app",
            "Config": {"Image": "img"},
            "HostConfig": {
                "PortBindings": {"8000/tcp": [{"HostPort": "9000"}]}
            },
        }
        mock = _mock_run(stdout=json.dumps(inspect_data))
        with patch("hort.containers.docker._run", mock):
            url = await DockerProvider().get_url("abc", 8000)
        assert url == "http://localhost:9000"

    @pytest.mark.asyncio
    async def test_get_url_no_port(self) -> None:
        inspect_data = {
            "State": {"Running": True},
            "Name": "/app",
            "Config": {"Image": "img"},
            "HostConfig": {"PortBindings": None},
        }
        mock = _mock_run(stdout=json.dumps(inspect_data))
        with patch("hort.containers.docker._run", mock):
            assert await DockerProvider().get_url("abc", 8000) is None

    @pytest.mark.asyncio
    async def test_get_url_not_found(self) -> None:
        mock = _mock_run(exit_code=1)
        with patch("hort.containers.docker._run", mock):
            assert await DockerProvider().get_url("nope", 8000) is None


class TestRunHelper:
    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        result = await _run(["sleep", "100"], timeout=0.1)
        assert result.exit_code == -1
        assert "timed out" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_command_not_found(self) -> None:
        result = await _run(["nonexistent_binary_xyz"])
        assert result.exit_code == -1
        assert "not found" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        result = await _run(["echo", "hello"])
        assert result.exit_code == 0
        assert result.stdout.strip() == "hello"
