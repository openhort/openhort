"""Tests for the extension system (hort.ext)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hort.ext.manifest import ExtensionManifest
from hort.ext.registry import ExtensionRegistry, _load_module, _parse_manifest
from hort.ext.types import (
    ActionInfo,
    ActionProvider,
    ActionResult,
    CaptureProvider,
    CommandResult,
    CommandTarget,
    ExtensionBase,
    InputProvider,
    PlatformProvider,
    UIProvider,
    WindowProvider,
    WorkspaceInfo,
    WorkspaceProvider,
)
from hort.models import InputEvent, WindowBounds, WindowInfo


# ===== Concrete stubs for ABC testing =====


class StubWindowProvider(WindowProvider):
    def __init__(self, windows: list[WindowInfo] | None = None) -> None:
        self._windows = windows or []

    def list_windows(self, app_filter: str | None = None) -> list[WindowInfo]:
        if app_filter:
            return [
                w
                for w in self._windows
                if app_filter.lower() in w.owner_name.lower()
            ]
        return self._windows


class StubCaptureProvider(CaptureProvider):
    def capture_window(
        self, window_id: int, max_width: int = 800, quality: int = 70
    ) -> bytes | None:
        return b"\xff\xd8fake"


class StubInputProvider(InputProvider):
    def __init__(self) -> None:
        self.last_event: InputEvent | None = None
        self.last_pid: int | None = None

    def handle_input(
        self, event: InputEvent, bounds: WindowBounds, pid: int = 0
    ) -> None:
        self.last_event = event

    def activate_app(
        self, pid: int, bounds: WindowBounds | None = None
    ) -> None:
        self.last_pid = pid


class StubWorkspaceProvider(WorkspaceProvider):
    def __init__(self, workspaces: list[WorkspaceInfo] | None = None) -> None:
        self._workspaces = workspaces or []

    def get_workspaces(self) -> list[WorkspaceInfo]:
        return self._workspaces

    def switch_to(self, target_index: int) -> bool:
        return any(w.index == target_index for w in self._workspaces)


class StubActionProvider(ActionProvider):
    def get_actions(self) -> list[ActionInfo]:
        return [ActionInfo(id="test", name="Test Action")]

    def execute(
        self, action_id: str, params: dict[str, Any] | None = None
    ) -> ActionResult:
        return ActionResult(success=True, message="done")


class StubCommandTarget(CommandTarget):
    @property
    def target_name(self) -> str:
        return "test-target"

    async def execute_command(
        self, command: str, timeout: float = 30.0
    ) -> CommandResult:
        return CommandResult(exit_code=0, stdout="ok", stderr="")

    async def is_available(self) -> bool:
        return True


class StubUIProvider(UIProvider):
    pass  # uses defaults


# ===== Manifest tests =====


class TestExtensionManifest:
    def test_minimal(self) -> None:
        m = ExtensionManifest(name="test")
        assert m.name == "test"
        assert m.version == "0.0.0"
        assert m.provider == "core"
        assert m.capabilities == []
        assert m.platforms == ["darwin", "linux", "win32"]
        assert m.entry_point == ""
        assert m.path == ""

    def test_full(self) -> None:
        m = ExtensionManifest(
            name="macos-windows",
            version="0.1.0",
            description="macOS window management",
            provider="core",
            platforms=["darwin"],
            capabilities=["window.list", "window.capture"],
            python_dependencies=["pyobjc-framework-Quartz>=11.0"],
            config_schema={"type": "object"},
            entry_point="provider:MacOSExtension",
            path="/some/path",
        )
        assert m.name == "macos-windows"
        assert m.platforms == ["darwin"]
        assert len(m.capabilities) == 2
        assert m.entry_point == "provider:MacOSExtension"
        assert m.path == "/some/path"
        assert len(m.python_dependencies) == 1

    def test_frozen(self) -> None:
        m = ExtensionManifest(name="test")
        with pytest.raises(Exception):
            m.name = "changed"  # type: ignore[misc]


# ===== Type / ABC tests =====


class TestWindowProvider:
    def test_get_app_names_default(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        windows = [
            WindowInfo(window_id=1, owner_name="Chrome", bounds=bounds),
            WindowInfo(window_id=2, owner_name="Code", bounds=bounds),
            WindowInfo(window_id=3, owner_name="Chrome", bounds=bounds),
        ]
        provider = StubWindowProvider(windows)
        assert provider.get_app_names() == ["Chrome", "Code"]

    def test_get_app_names_empty(self) -> None:
        assert StubWindowProvider([]).get_app_names() == []

    def test_list_windows_filter(self) -> None:
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        windows = [
            WindowInfo(window_id=1, owner_name="Chrome", bounds=bounds),
            WindowInfo(window_id=2, owner_name="Code", bounds=bounds),
        ]
        provider = StubWindowProvider(windows)
        assert len(provider.list_windows("chrome")) == 1
        assert len(provider.list_windows()) == 2


class TestCaptureProvider:
    def test_capture(self) -> None:
        result = StubCaptureProvider().capture_window(1)
        assert result == b"\xff\xd8fake"


class TestInputProvider:
    def test_handle_input(self) -> None:
        provider = StubInputProvider()
        event = InputEvent(type="click", nx=0.5, ny=0.5)
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        provider.handle_input(event, bounds, pid=1)
        assert provider.last_event is event

    def test_activate_app(self) -> None:
        provider = StubInputProvider()
        provider.activate_app(1234)
        assert provider.last_pid == 1234


class TestWorkspaceProvider:
    def test_get_current_index_found(self) -> None:
        workspaces = [
            WorkspaceInfo(index=1, is_current=False),
            WorkspaceInfo(index=2, is_current=True),
        ]
        assert StubWorkspaceProvider(workspaces).get_current_index() == 2

    def test_get_current_index_empty(self) -> None:
        assert StubWorkspaceProvider([]).get_current_index() == 1

    def test_switch_to(self) -> None:
        workspaces = [WorkspaceInfo(index=1, is_current=True)]
        provider = StubWorkspaceProvider(workspaces)
        assert provider.switch_to(1) is True
        assert provider.switch_to(99) is False


class TestActionProvider:
    def test_get_actions(self) -> None:
        actions = StubActionProvider().get_actions()
        assert len(actions) == 1
        assert actions[0].id == "test"

    def test_execute(self) -> None:
        result = StubActionProvider().execute("test")
        assert result.success is True
        assert result.message == "done"


class TestCommandTarget:
    @pytest.mark.asyncio
    async def test_execute_command(self) -> None:
        result = await StubCommandTarget().execute_command("echo hi")
        assert result.exit_code == 0
        assert result.stdout == "ok"

    @pytest.mark.asyncio
    async def test_is_available(self) -> None:
        assert await StubCommandTarget().is_available() is True

    def test_target_name(self) -> None:
        assert StubCommandTarget().target_name == "test-target"


class TestUIProvider:
    def test_defaults(self) -> None:
        provider = StubUIProvider()
        assert provider.get_static_dir() is None
        assert provider.get_routes() == []


class TestDataclasses:
    def test_workspace_info(self) -> None:
        ws = WorkspaceInfo(index=1, is_current=True, name="Desktop 1")
        assert ws.index == 1
        assert ws.is_current is True
        assert ws.name == "Desktop 1"

    def test_workspace_info_defaults(self) -> None:
        ws = WorkspaceInfo(index=1, is_current=False)
        assert ws.name == ""

    def test_action_info(self) -> None:
        a = ActionInfo(id="reload", name="Reload", description="Reload page")
        assert a.id == "reload"
        assert a.params_schema is None

    def test_action_info_defaults(self) -> None:
        a = ActionInfo(id="x", name="X")
        assert a.description == ""
        assert a.params_schema is None

    def test_action_result(self) -> None:
        r = ActionResult(success=True, message="ok", data={"key": "val"})
        assert r.success is True
        assert r.data == {"key": "val"}

    def test_action_result_defaults(self) -> None:
        r = ActionResult(success=False)
        assert r.message == ""
        assert r.data is None

    def test_command_result(self) -> None:
        r = CommandResult(exit_code=0, stdout="hello", stderr="")
        assert r.exit_code == 0
        assert r.stdout == "hello"


# ===== Unified base class tests =====


class StubPlatformProvider(PlatformProvider):
    """Minimal concrete PlatformProvider for testing."""

    def list_windows(self, app_filter: str | None = None) -> list[WindowInfo]:
        return []

    def capture_window(
        self, window_id: int, max_width: int = 800, quality: int = 70
    ) -> bytes | None:
        return b"\xff\xd8stub"

    def handle_input(
        self, event: InputEvent, bounds: WindowBounds, pid: int = 0
    ) -> None:
        pass

    def activate_app(
        self, pid: int, bounds: WindowBounds | None = None
    ) -> None:
        pass

    def get_workspaces(self) -> list[WorkspaceInfo]:
        return [WorkspaceInfo(index=1, is_current=True)]

    def switch_to(self, target_index: int) -> bool:
        return target_index == 1


class TestPlatformProvider:
    def test_is_window_provider(self) -> None:
        p = StubPlatformProvider()
        assert isinstance(p, WindowProvider)

    def test_is_capture_provider(self) -> None:
        p = StubPlatformProvider()
        assert isinstance(p, CaptureProvider)

    def test_is_input_provider(self) -> None:
        p = StubPlatformProvider()
        assert isinstance(p, InputProvider)

    def test_is_workspace_provider(self) -> None:
        p = StubPlatformProvider()
        assert isinstance(p, WorkspaceProvider)

    def test_all_methods_work(self) -> None:
        p = StubPlatformProvider()
        assert p.list_windows() == []
        assert p.get_app_names() == []
        assert p.capture_window(1) == b"\xff\xd8stub"
        assert p.get_workspaces()[0].is_current is True
        assert p.get_current_index() == 1
        assert p.switch_to(1) is True

        event = InputEvent(type="click", nx=0.5, ny=0.5)
        bounds = WindowBounds(x=0, y=0, width=100, height=100)
        p.handle_input(event, bounds)
        p.activate_app(1)


class TestExtensionBase:
    def test_default_activate_is_noop(self) -> None:
        class Minimal(ExtensionBase):
            pass

        ext = Minimal()
        ext.activate({"key": "val"})  # should not raise

    def test_default_deactivate_is_noop(self) -> None:
        class Minimal(ExtensionBase):
            pass

        ext = Minimal()
        ext.deactivate()  # should not raise

    def test_custom_lifecycle(self) -> None:
        class Custom(ExtensionBase):
            def __init__(self) -> None:
                self.cfg: dict[str, Any] = {}
                self.stopped = False

            def activate(self, config: dict[str, Any]) -> None:
                self.cfg = config

            def deactivate(self) -> None:
                self.stopped = True

        ext = Custom()
        ext.activate({"port": 8080})
        assert ext.cfg == {"port": 8080}
        ext.deactivate()
        assert ext.stopped is True


# ===== Registry tests — helpers =====


def _make_ext_dir(
    tmp_path: Path,
    provider: str,
    name: str,
    manifest: dict[str, Any],
    *,
    py_code: str = "",
) -> Path:
    """Create an extension directory with manifest and optional Python code."""
    ext_dir = tmp_path / provider / name
    ext_dir.mkdir(parents=True)
    (ext_dir / "extension.json").write_text(json.dumps(manifest))
    (ext_dir / "__init__.py").write_text("")
    if py_code:
        module_name = manifest.get("entry_point", "").partition(":")[0] or "provider"
        (ext_dir / f"{module_name}.py").write_text(py_code)
    return ext_dir


# ===== Registry tests — discover =====


class TestDiscover:
    def test_discovers_valid_extension(self, tmp_path: Path) -> None:
        _make_ext_dir(
            tmp_path,
            "core",
            "test-ext",
            {"name": "test-ext", "version": "0.1.0", "capabilities": ["window.list"]},
        )
        registry = ExtensionRegistry()
        manifests = registry.discover(tmp_path)
        assert len(manifests) == 1
        assert manifests[0].name == "test-ext"

    def test_discovers_multiple_providers(self, tmp_path: Path) -> None:
        _make_ext_dir(tmp_path, "core", "ext-a", {"name": "ext-a"})
        _make_ext_dir(tmp_path, "core", "ext-b", {"name": "ext-b"})
        _make_ext_dir(tmp_path, "community", "ext-c", {"name": "ext-c"})
        manifests = ExtensionRegistry().discover(tmp_path)
        assert len(manifests) == 3

    def test_skips_invalid_manifest(self, tmp_path: Path) -> None:
        ext_dir = tmp_path / "core" / "broken"
        ext_dir.mkdir(parents=True)
        (ext_dir / "extension.json").write_text("not valid json{{{")
        assert ExtensionRegistry().discover(tmp_path) == []

    def test_skips_missing_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "core" / "no-manifest").mkdir(parents=True)
        assert ExtensionRegistry().discover(tmp_path) == []

    def test_empty_dir(self, tmp_path: Path) -> None:
        assert ExtensionRegistry().discover(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert ExtensionRegistry().discover(tmp_path / "nope") == []

    def test_skips_dotdirs(self, tmp_path: Path) -> None:
        _make_ext_dir(tmp_path, ".hidden", "ext", {"name": "ext"})
        _make_ext_dir(tmp_path, "core", ".hidden-ext", {"name": "hidden"})
        assert ExtensionRegistry().discover(tmp_path) == []

    def test_skips_files_in_provider_dir(self, tmp_path: Path) -> None:
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "README.md").write_text("not a dir")
        assert ExtensionRegistry().discover(tmp_path) == []

    def test_sets_path_on_manifest(self, tmp_path: Path) -> None:
        ext_dir = _make_ext_dir(tmp_path, "core", "my-ext", {"name": "my-ext"})
        manifests = ExtensionRegistry().discover(tmp_path)
        assert manifests[0].path == str(ext_dir)


# ===== Registry tests — is_compatible =====


class TestIsCompatible:
    def test_compatible_current_platform(self) -> None:
        m = ExtensionManifest(name="t", platforms=[sys.platform])
        assert ExtensionRegistry.is_compatible(m) is True

    def test_incompatible(self) -> None:
        m = ExtensionManifest(name="t", platforms=["not-a-platform"])
        assert ExtensionRegistry.is_compatible(m) is False

    def test_multi_platform(self) -> None:
        m = ExtensionManifest(name="t", platforms=["darwin", "linux", "win32"])
        assert ExtensionRegistry.is_compatible(m) is True


# ===== Registry tests — load_extension =====


class TestLoadExtension:
    def test_load_with_activate(self, tmp_path: Path) -> None:
        code = (
            "class TestExt:\n"
            "    activated = False\n"
            "    def activate(self, config):\n"
            "        self.activated = True\n"
            "        self.config = config\n"
        )
        (tmp_path / "provider.py").write_text(code)
        m = ExtensionManifest(
            name="t",
            entry_point="provider:TestExt",
            path=str(tmp_path),
            capabilities=["window.list"],
        )
        registry = ExtensionRegistry()
        instance = registry.load_extension(m, config={"key": "val"})
        assert instance is not None
        assert instance.activated is True
        assert instance.config == {"key": "val"}

    def test_load_without_config(self, tmp_path: Path) -> None:
        code = (
            "class Ext:\n"
            "    def activate(self, config):\n"
            "        self.config = config\n"
        )
        (tmp_path / "provider.py").write_text(code)
        m = ExtensionManifest(
            name="t", entry_point="provider:Ext", path=str(tmp_path)
        )
        instance = ExtensionRegistry().load_extension(m)
        assert instance is not None
        assert instance.config == {}  # activate always called with empty dict if no config

    def test_load_without_activate_method(self, tmp_path: Path) -> None:
        (tmp_path / "provider.py").write_text("class NoActivate: pass\n")
        m = ExtensionManifest(
            name="t", entry_point="provider:NoActivate", path=str(tmp_path)
        )
        instance = ExtensionRegistry().load_extension(m, config={"a": 1})
        assert instance is not None

    def test_load_no_entry_point(self) -> None:
        m = ExtensionManifest(name="t", path="/some/path")
        assert ExtensionRegistry().load_extension(m) is None

    def test_load_no_path(self) -> None:
        m = ExtensionManifest(name="t", entry_point="mod:Cls")
        assert ExtensionRegistry().load_extension(m) is None

    def test_load_no_class_in_entry_point(self) -> None:
        m = ExtensionManifest(name="t", entry_point="mod_only", path="/p")
        assert ExtensionRegistry().load_extension(m) is None

    def test_load_missing_module_file(self, tmp_path: Path) -> None:
        m = ExtensionManifest(
            name="t", entry_point="nonexistent:Cls", path=str(tmp_path)
        )
        assert ExtensionRegistry().load_extension(m) is None

    def test_load_missing_class(self, tmp_path: Path) -> None:
        (tmp_path / "provider.py").write_text("class Other: pass\n")
        m = ExtensionManifest(
            name="t", entry_point="provider:Missing", path=str(tmp_path)
        )
        assert ExtensionRegistry().load_extension(m) is None

    def test_load_bad_spec(self, tmp_path: Path) -> None:
        (tmp_path / "provider.py").write_text("class Ext: pass\n")
        m = ExtensionManifest(
            name="t", entry_point="provider:Ext", path=str(tmp_path)
        )
        with patch(
            "hort.ext.registry.importlib.util.spec_from_file_location",
            return_value=None,
        ):
            assert ExtensionRegistry().load_extension(m) is None

    def test_registers_capabilities(self, tmp_path: Path) -> None:
        (tmp_path / "provider.py").write_text("class Ext: pass\n")
        m = ExtensionManifest(
            name="t",
            entry_point="provider:Ext",
            path=str(tmp_path),
            capabilities=["window.list", "window.capture"],
        )
        registry = ExtensionRegistry()
        registry.load_extension(m)
        assert registry._capability_map.get("window.list") == "t"
        assert registry._capability_map.get("window.capture") == "t"

    def test_first_loaded_wins_capability(self, tmp_path: Path) -> None:
        (tmp_path / "provider.py").write_text("class Ext: pass\n")
        m1 = ExtensionManifest(
            name="first",
            entry_point="provider:Ext",
            path=str(tmp_path),
            capabilities=["window.list"],
        )
        m2 = ExtensionManifest(
            name="second",
            entry_point="provider:Ext",
            path=str(tmp_path),
            capabilities=["window.list"],
        )
        registry = ExtensionRegistry()
        registry.load_extension(m1)
        registry.load_extension(m2)
        assert registry._capability_map["window.list"] == "first"


# ===== Registry tests — load_compatible =====


class TestLoadCompatible:
    def test_loads_compatible_skips_incompatible(self, tmp_path: Path) -> None:
        code = "class Ext: pass\n"
        _make_ext_dir(
            tmp_path,
            "core",
            "good",
            {
                "name": "good",
                "platforms": [sys.platform],
                "entry_point": "provider:Ext",
                "capabilities": ["window.list"],
            },
            py_code=code,
        )
        _make_ext_dir(
            tmp_path,
            "core",
            "bad",
            {
                "name": "bad",
                "platforms": ["not-a-platform"],
                "entry_point": "provider:Ext",
            },
            py_code=code,
        )
        registry = ExtensionRegistry()
        registry.discover(tmp_path)
        registry.load_compatible()
        assert "good" in registry._instances
        assert "bad" not in registry._instances

    def test_passes_per_extension_config(self, tmp_path: Path) -> None:
        code = (
            "class Ext:\n"
            "    def activate(self, config):\n"
            "        self.config = config\n"
        )
        _make_ext_dir(
            tmp_path,
            "core",
            "my-ext",
            {
                "name": "my-ext",
                "platforms": [sys.platform],
                "entry_point": "provider:Ext",
            },
            py_code=code,
        )
        registry = ExtensionRegistry()
        registry.discover(tmp_path)
        registry.load_compatible(config={"my-ext": {"key": "val"}})
        assert registry._instances["my-ext"].config == {"key": "val"}


# ===== Registry tests — get_provider =====


class TestGetProvider:
    def test_found(self, tmp_path: Path) -> None:
        code = (
            "from hort.ext.types import WindowProvider\n"
            "from hort.models import WindowInfo\n"
            "class Win(WindowProvider):\n"
            "    def list_windows(self, app_filter=None):\n"
            "        return []\n"
        )
        (tmp_path / "provider.py").write_text(code)
        m = ExtensionManifest(
            name="t",
            entry_point="provider:Win",
            path=str(tmp_path),
            capabilities=["window.list"],
        )
        registry = ExtensionRegistry()
        registry.load_extension(m)
        provider = registry.get_provider("window.list", WindowProvider)
        assert provider is not None
        assert isinstance(provider, WindowProvider)
        assert provider.list_windows() == []

    def test_not_found(self) -> None:
        assert ExtensionRegistry().get_provider("nope", WindowProvider) is None

    def test_wrong_type(self, tmp_path: Path) -> None:
        (tmp_path / "provider.py").write_text("class NotAProvider: pass\n")
        m = ExtensionManifest(
            name="t",
            entry_point="provider:NotAProvider",
            path=str(tmp_path),
            capabilities=["window.list"],
        )
        registry = ExtensionRegistry()
        registry.load_extension(m)
        assert registry.get_provider("window.list", WindowProvider) is None

    def test_no_instance_loaded(self) -> None:
        registry = ExtensionRegistry()
        registry._capability_map["window.list"] = "ghost"
        assert registry.get_provider("window.list", WindowProvider) is None


# ===== Helpers =====


class TestParseManifest:
    def test_valid(self, tmp_path: Path) -> None:
        f = tmp_path / "extension.json"
        f.write_text(json.dumps({"name": "hello"}))
        m = _parse_manifest(f, tmp_path)
        assert m is not None
        assert m.name == "hello"
        assert m.path == str(tmp_path)

    def test_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "extension.json"
        f.write_text("{{bad")
        assert _parse_manifest(f, tmp_path) is None

    def test_missing_required_field(self, tmp_path: Path) -> None:
        f = tmp_path / "extension.json"
        f.write_text(json.dumps({"version": "1.0"}))  # missing 'name'
        assert _parse_manifest(f, tmp_path) is None


class TestPluginContextInjection:
    """Tests for PluginBase context injection in load_extension."""

    def test_injects_context_for_plugin_base(self, tmp_path: Path) -> None:
        code = (
            "from hort.ext.plugin import PluginBase\n"
            "class MyPlugin(PluginBase):\n"
            "    def activate(self, config):\n"
            "        self.log.info('activated with %s', config)\n"
        )
        _make_ext_dir(
            tmp_path, "core", "test-plugin",
            {"name": "test-plugin", "platforms": [sys.platform],
             "entry_point": "provider:MyPlugin", "capabilities": ["test"],
             "features": {"alerts": {"description": "Alert", "default": True}}},
            py_code=code,
        )
        registry = ExtensionRegistry()
        registry.discover(tmp_path)
        registry.load_compatible()
        instance = registry._instances.get("test-plugin")
        assert instance is not None
        assert hasattr(instance, "_ctx")
        assert instance.plugin_id == "test-plugin"
        assert instance.config.is_feature_enabled("alerts") is True

    def test_no_context_for_extension_base(self, tmp_path: Path) -> None:
        code = "class OldExt:\n    def activate(self, config): self.cfg = config\n"
        _make_ext_dir(
            tmp_path, "core", "old-ext",
            {"name": "old-ext", "platforms": [sys.platform],
             "entry_point": "provider:OldExt"},
            py_code=code,
        )
        registry = ExtensionRegistry()
        registry.discover(tmp_path)
        registry.load_compatible(config={"old-ext": {"key": "val"}})
        instance = registry._instances.get("old-ext")
        assert instance is not None
        assert instance.cfg == {"key": "val"}
        assert not hasattr(instance, "_ctx")


class TestUnloadExtension:
    def test_unload_stops_and_removes(self, tmp_path: Path) -> None:
        code = (
            "from hort.ext.plugin import PluginBase\n"
            "class MyPlugin(PluginBase):\n"
            "    stopped = False\n"
            "    def deactivate(self):\n"
            "        self.stopped = True\n"
        )
        _make_ext_dir(
            tmp_path, "core", "unload-test",
            {"name": "unload-test", "platforms": [sys.platform],
             "entry_point": "provider:MyPlugin", "capabilities": ["x"]},
            py_code=code,
        )
        registry = ExtensionRegistry()
        registry.discover(tmp_path)
        registry.load_compatible()
        assert "unload-test" in registry._instances
        assert registry._capability_map.get("x") == "unload-test"

        instance = registry._instances["unload-test"]
        assert registry.unload_extension("unload-test") is True
        assert "unload-test" not in registry._instances
        assert "x" not in registry._capability_map
        assert instance.stopped is True

    def test_unload_nonexistent(self) -> None:
        assert ExtensionRegistry().unload_extension("nope") is False

    def test_unload_deactivate_error(self, tmp_path: Path) -> None:
        code = (
            "from hort.ext.plugin import PluginBase\n"
            "class Bad(PluginBase):\n"
            "    def deactivate(self):\n"
            "        raise RuntimeError('boom')\n"
        )
        _make_ext_dir(
            tmp_path, "core", "bad-deactivate",
            {"name": "bad-deactivate", "platforms": [sys.platform],
             "entry_point": "provider:Bad"},
            py_code=code,
        )
        registry = ExtensionRegistry()
        registry.discover(tmp_path)
        registry.load_compatible()
        assert registry.unload_extension("bad-deactivate") is True  # should not raise


class TestListPlugins:
    def test_lists_all(self, tmp_path: Path) -> None:
        code = (
            "from hort.ext.plugin import PluginBase\n"
            "class P(PluginBase): pass\n"
        )
        _make_ext_dir(
            tmp_path, "core", "p1",
            {"name": "p1", "platforms": [sys.platform],
             "entry_point": "provider:P", "capabilities": ["mon"],
             "features": {"f1": {"description": "F1", "default": True}}},
            py_code=code,
        )
        _make_ext_dir(
            tmp_path, "core", "p2",
            {"name": "p2", "platforms": ["not-real"],
             "entry_point": "provider:P"},
            py_code=code,
        )
        registry = ExtensionRegistry()
        registry.discover(tmp_path)
        registry.load_compatible()
        plugins = registry.list_plugins()
        assert len(plugins) == 2
        p1 = next(p for p in plugins if p["name"] == "p1")
        assert p1["loaded"] is True
        assert p1["compatible"] is True
        assert p1["features"]["f1"]["enabled"] is True
        p2 = next(p for p in plugins if p["name"] == "p2")
        assert p2["loaded"] is False
        assert p2["compatible"] is False


class TestSetApp:
    def test_set_app(self) -> None:
        registry = ExtensionRegistry()
        registry.set_app("fake-app")
        assert registry._app == "fake-app"

    def test_router_mounted_when_app_set(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock
        code = (
            "from fastapi import APIRouter\n"
            "from hort.ext.plugin import PluginBase\n"
            "class WithRouter(PluginBase):\n"
            "    def get_router(self):\n"
            "        r = APIRouter()\n"
            "        @r.get('/test')\n"
            "        def test(): return {'ok': True}\n"
            "        return r\n"
        )
        _make_ext_dir(
            tmp_path, "core", "router-test",
            {"name": "router-test", "platforms": [sys.platform],
             "entry_point": "provider:WithRouter"},
            py_code=code,
        )
        app = MagicMock()
        registry = ExtensionRegistry()
        registry.set_app(app)
        registry.discover(tmp_path)
        registry.load_compatible()
        app.include_router.assert_called_once()

    def test_router_mount_failure_logged(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock
        code = (
            "from fastapi import APIRouter\n"
            "from hort.ext.plugin import PluginBase\n"
            "class Bad(PluginBase):\n"
            "    def get_router(self):\n"
            "        return APIRouter()\n"
        )
        _make_ext_dir(
            tmp_path, "core", "bad-router",
            {"name": "bad-router", "platforms": [sys.platform],
             "entry_point": "provider:Bad"},
            py_code=code,
        )
        app = MagicMock()
        app.include_router.side_effect = RuntimeError("mount failed")
        registry = ExtensionRegistry()
        registry.set_app(app)
        registry.discover(tmp_path)
        registry.load_compatible()  # should not raise

    def test_unload_removes_routes(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock
        code = (
            "from hort.ext.plugin import PluginBase\n"
            "class P(PluginBase): pass\n"
        )
        _make_ext_dir(
            tmp_path, "core", "rt",
            {"name": "rt", "platforms": [sys.platform],
             "entry_point": "provider:P"},
            py_code=code,
        )
        # Simulate app with routes
        route1 = MagicMock()
        route1.path = "/api/plugins/rt/test"
        route2 = MagicMock()
        route2.path = "/api/other"
        app = MagicMock()
        app.routes = [route1, route2]
        app.include_router = MagicMock()

        registry = ExtensionRegistry()
        registry.set_app(app)
        registry.discover(tmp_path)
        registry.load_compatible()
        registry.unload_extension("rt")
        # Only the /api/other route should remain
        assert len(app.routes) == 1
        assert app.routes[0].path == "/api/other"


class TestGetters:
    def test_get_instance(self, tmp_path: Path) -> None:
        code = "class E: pass\n"
        (tmp_path / "provider.py").write_text(code)
        m = ExtensionManifest(name="t", entry_point="provider:E", path=str(tmp_path))
        registry = ExtensionRegistry()
        registry.load_extension(m)
        assert registry.get_instance("t") is not None
        assert registry.get_instance("nope") is None

    def test_get_manifest(self, tmp_path: Path) -> None:
        _make_ext_dir(tmp_path, "core", "x", {"name": "x"})
        registry = ExtensionRegistry()
        registry.discover(tmp_path)
        assert registry.get_manifest("x") is not None
        assert registry.get_manifest("nope") is None


class TestLoadModule:
    def test_valid(self, tmp_path: Path) -> None:
        f = tmp_path / "mymod.py"
        f.write_text("X = 42\n")
        mod = _load_module("_test_mod", f)
        assert mod is not None
        assert mod.X == 42

    def test_bad_spec(self, tmp_path: Path) -> None:
        f = tmp_path / "mymod.py"
        f.write_text("X = 1\n")
        with patch(
            "hort.ext.registry.importlib.util.spec_from_file_location",
            return_value=None,
        ):
            assert _load_module("_test", f) is None
