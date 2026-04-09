"""Tests for the extension MCP server and llming-lens MCP tools."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hort.ext.mcp import MCPToolDef, MCPToolResult
from hort.models import WindowBounds, WindowInfo


# ── Filter tests ──────────────────────────────────────────────────────


class TestMatchFilter:
    """Test the app name filter patterns."""

    def test_exact_match(self) -> None:
        from hort.extensions.core.llming_lens.provider import _match_filter

        assert _match_filter("Google Chrome", "Google Chrome")
        assert _match_filter("Google Chrome", "google chrome")  # case-insensitive
        assert not _match_filter("Firefox", "Google Chrome")

    def test_glob_pattern(self) -> None:
        from hort.extensions.core.llming_lens.provider import _match_filter

        assert _match_filter("Google Chrome", "*Chrome*")
        assert _match_filter("Google Chrome", "Google*")
        assert _match_filter("iTerm2", "iTerm*")
        assert not _match_filter("Firefox", "Chrome*")

    def test_regex_pattern(self) -> None:
        from hort.extensions.core.llming_lens.provider import _match_filter

        assert _match_filter("Google Chrome", "/^Google.*/")
        assert _match_filter("google chrome", "/^google.*/i")
        assert not _match_filter("Firefox", "/^Google.*/")

    def test_empty_filter(self) -> None:
        from hort.extensions.core.llming_lens.provider import _match_filter

        assert _match_filter("anything", "")

    def test_matches_any(self) -> None:
        from hort.extensions.core.llming_lens.provider import _matches_any

        assert _matches_any("Google Chrome", ["*Chrome*", "Firefox"])
        assert _matches_any("Firefox", ["Chrome", "Firefox"])
        assert not _matches_any("Safari", ["Chrome", "Firefox"])

    def test_filter_windows(self) -> None:
        from hort.extensions.core.llming_lens.provider import _filter_windows

        windows = [
            WindowInfo(window_id=1, owner_name="Google Chrome", window_name="Tab 1",
                       bounds=WindowBounds(x=0, y=0, width=100, height=100)),
            WindowInfo(window_id=2, owner_name="Firefox", window_name="Tab 2",
                       bounds=WindowBounds(x=0, y=0, width=100, height=100)),
            WindowInfo(window_id=3, owner_name="iTerm2", window_name="Shell",
                       bounds=WindowBounds(x=0, y=0, width=100, height=100)),
        ]

        filtered = _filter_windows(windows, "*Chrome*,iTerm*")
        assert len(filtered) == 2
        assert filtered[0].owner_name == "Google Chrome"
        assert filtered[1].owner_name == "iTerm2"

        # No filter = all windows
        assert len(_filter_windows(windows, None)) == 3
        assert len(_filter_windows(windows, "")) == 3


# ── Grid annotation tests ────────────────────────────────────────────


class TestGridAnnotation:
    """Test the grid overlay feature."""

    def test_annotate_grid(self) -> None:
        from PIL import Image

        from hort.extensions.core.llming_lens.provider import _annotate_grid

        img = Image.new("RGB", (800, 600), (0, 0, 0))
        result = _annotate_grid(img)
        assert result.size == (800, 600)
        # Verify it's now RGBA (due to overlay drawing)
        assert result.mode == "RGB" or result.mode == "RGBA"

    def test_grid_cell_to_region(self) -> None:
        from hort.extensions.core.llming_lens.provider import LlmingLens

        lens = LlmingLens()
        region = lens._grid_cell_to_region("A1")
        assert region == {"x": 0.0, "y": 0.0, "w": 0.25, "h": 0.25}

        region = lens._grid_cell_to_region("D4")
        assert region == {"x": 0.75, "y": 0.75, "w": 0.25, "h": 0.25}

        region = lens._grid_cell_to_region("B2")
        assert region == {"x": 0.25, "y": 0.25, "w": 0.25, "h": 0.25}

    def test_grid_cell_invalid(self) -> None:
        from hort.extensions.core.llming_lens.provider import LlmingLens

        lens = LlmingLens()
        with pytest.raises(ValueError):
            lens._grid_cell_to_region("E1")  # Out of range
        with pytest.raises(ValueError):
            lens._grid_cell_to_region("A5")  # Out of range
        with pytest.raises(ValueError):
            lens._grid_cell_to_region("X")   # Too short


# ── MCP server protocol tests ────────────────────────────────────────


class TestMCPProtocol:
    """Test the MCP stdio server protocol."""

    def test_bridge_handle_tools_list(self) -> None:
        from hort.mcp.bridge import MCPBridge

        class FakePlugin:
            plugin_id = "test"

            def get_mcp_tools(self) -> list[MCPToolDef]:
                return [MCPToolDef(name="my_tool", description="A test tool")]

            async def execute_mcp_tool(self, name: str, args: dict) -> MCPToolResult:
                return MCPToolResult(content=[{"type": "text", "text": "ok"}])

        bridge = MCPBridge([FakePlugin()])
        result = asyncio.get_event_loop().run_until_complete(
            bridge.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        )
        tools = result["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "test__my_tool"

    def test_bridge_tool_call(self) -> None:
        from hort.mcp.bridge import MCPBridge

        class FakePlugin:
            plugin_id = "test"

            def get_mcp_tools(self) -> list[MCPToolDef]:
                return [MCPToolDef(name="greet", description="Say hello")]

            async def execute_mcp_tool(self, name: str, args: dict) -> MCPToolResult:
                return MCPToolResult(content=[{"type": "text", "text": "hello"}])

        bridge = MCPBridge([FakePlugin()])
        result = asyncio.get_event_loop().run_until_complete(
            bridge.handle_message({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "test__greet", "arguments": {}},
            })
        )
        assert result["result"]["content"][0]["text"] == "hello"
        assert not result["result"]["isError"]


# ── LlmingLens tool tests ────────────────────────────────────────────


class TestLlmingLensTools:
    """Test LlmingLens MCP tool implementations."""

    def _make_lens(self, app_filter: str | None = None) -> Any:
        from hort.extensions.core.llming_lens.provider import LlmingLens
        from hort.ext.scheduler import PluginScheduler
        import logging

        lens = LlmingLens()
        # Inject LlmingBase services
        lens._instance_name = "llming-lens-test"
        lens._class_name = "llming-lens-test"
        lens._store = MagicMock()
        lens._files = MagicMock()
        lens._scheduler = PluginScheduler("llming-lens-test")
        lens._logger = logging.getLogger("test.llming-lens")
        lens._config = {}
        config = {"app_filter": app_filter} if app_filter else {}
        lens.activate(config)
        return lens

    def test_get_mcp_tools(self) -> None:
        lens = self._make_lens()
        tools = lens.get_mcp_tools()
        names = {t.name for t in tools}
        assert "list_windows" in names
        assert "get_window_info" in names
        assert "screenshot" in names
        assert "click" in names
        assert "type_text" in names
        assert "press_key" in names

    def test_list_windows_with_mock(self) -> None:
        lens = self._make_lens()
        mock_windows = [
            WindowInfo(window_id=-1, owner_name="Desktop", window_name="Full Screen",
                       bounds=WindowBounds(x=0, y=0, width=1920, height=1080)),
            WindowInfo(window_id=100, owner_name="Google Chrome", window_name="Tab",
                       bounds=WindowBounds(x=0, y=0, width=800, height=600),
                       space_index=1),
        ]
        with patch("hort.extensions.core.llming_lens.provider.list_windows", return_value=mock_windows, create=True):
            with patch("hort.windows.list_windows", return_value=mock_windows):
                result = asyncio.get_event_loop().run_until_complete(
                    lens.execute_mcp_tool("list_windows", {})
                )

        assert not result.is_error
        text = result.content[0]["text"]
        assert "Windows (2)" in text
        assert "Google Chrome" in text

    def test_list_windows_with_filter(self) -> None:
        lens = self._make_lens(app_filter="*Chrome*")
        mock_windows = [
            WindowInfo(window_id=-1, owner_name="Desktop", window_name="Full Screen",
                       bounds=WindowBounds(x=0, y=0, width=1920, height=1080)),
            WindowInfo(window_id=100, owner_name="Google Chrome", window_name="Tab",
                       bounds=WindowBounds(x=0, y=0, width=800, height=600)),
            WindowInfo(window_id=200, owner_name="Firefox", window_name="Page",
                       bounds=WindowBounds(x=0, y=0, width=800, height=600)),
        ]
        with patch("hort.windows.list_windows", return_value=mock_windows):
            result = asyncio.get_event_loop().run_until_complete(
                lens.execute_mcp_tool("list_windows", {})
            )

        text = result.content[0]["text"]
        assert "Google Chrome" in text
        assert "Firefox" not in text

    def test_get_window_info(self) -> None:
        lens = self._make_lens()
        mock_windows = [
            WindowInfo(window_id=100, owner_name="Chrome", window_name="Tab",
                       bounds=WindowBounds(x=10, y=20, width=800, height=600),
                       space_index=1, owner_pid=1234),
        ]
        with patch("hort.windows.list_windows", return_value=mock_windows):
            result = asyncio.get_event_loop().run_until_complete(
                lens.execute_mcp_tool("get_window_info", {})
            )

        assert not result.is_error
        info = json.loads(result.content[0]["text"])
        assert len(info) == 1
        assert info[0]["window_id"] == 100
        assert info[0]["bounds"]["x"] == 10
        assert info[0]["owner_pid"] == 1234

    def test_screenshot_returns_image(self) -> None:
        lens = self._make_lens()
        from PIL import Image

        test_img = Image.new("RGB", (200, 100), (128, 128, 128))

        mock_cg = MagicMock()
        with patch("hort.screen._raw_capture_desktop", return_value=mock_cg):
            with patch("hort.screen._cgimage_to_pil", return_value=test_img.copy()):
                with patch("hort.screen.Quartz") as mock_q:
                    mock_q.CGImageGetWidth.return_value = 200
                    mock_q.CGImageGetHeight.return_value = 100
                    result = asyncio.get_event_loop().run_until_complete(
                        lens.execute_mcp_tool("screenshot", {"target": "desktop"})
                    )

        assert not result.is_error
        assert len(result.content) == 2
        assert result.content[0]["type"] == "text"  # metadata
        assert result.content[1]["type"] == "image"
        # Verify it's valid base64 JPEG
        img_data = base64.b64decode(result.content[1]["data"])
        assert img_data[:2] == b"\xff\xd8"  # JPEG magic bytes

    def test_resolve_target_desktop(self) -> None:
        lens = self._make_lens()
        wid, info = lens._resolve_target("desktop")
        assert wid == -1
        assert info is None

    def test_resolve_target_window_id(self) -> None:
        lens = self._make_lens()
        mock_windows = [
            WindowInfo(window_id=42, owner_name="Chrome", window_name="Tab",
                       bounds=WindowBounds(x=0, y=0, width=800, height=600)),
        ]
        with patch("hort.windows.list_windows", return_value=mock_windows):
            wid, info = lens._resolve_target("42")
        assert wid == 42
        assert info is not None
        assert info.owner_name == "Chrome"

    def test_resolve_target_by_name(self) -> None:
        lens = self._make_lens()
        mock_windows = [
            WindowInfo(window_id=42, owner_name="Chrome", window_name="Tab",
                       bounds=WindowBounds(x=0, y=0, width=800, height=600)),
        ]
        with patch("hort.windows.list_windows", return_value=mock_windows):
            wid, info = lens._resolve_target("chrome")
        assert wid == 42

    def test_unknown_tool(self) -> None:
        lens = self._make_lens()
        result = asyncio.get_event_loop().run_until_complete(
            lens.execute_mcp_tool("nonexistent", {})
        )
        # LlmingBase.execute_mcp_tool wraps None returns as non-error text
        assert result.content[0]["text"] == "None"

    def test_effective_filter_priority(self) -> None:
        """Per-call filter overrides configured default."""
        lens = self._make_lens(app_filter="Firefox")
        assert lens._get_effective_filter({}) == "Firefox"
        assert lens._get_effective_filter({"app_filter": "Chrome"}) == "Chrome"

    def test_grid_cell_zoom_composing(self) -> None:
        """Grid cell zoom composes with previous region."""
        lens = self._make_lens()
        # Simulate having previously captured with grid at full size
        lens._last_grid_region = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}

        # B2 should give the second column, second row
        region = lens._grid_cell_to_region("B2")
        assert region == {"x": 0.25, "y": 0.25, "w": 0.25, "h": 0.25}

        # Now simulate zooming into B2 and then zooming into A1 within that
        lens._last_grid_region = {"x": 0.25, "y": 0.25, "w": 0.25, "h": 0.25}
        # A1 within B2 = top-left quarter of B2
        cell_region = lens._grid_cell_to_region("A1")
        composed = {
            "x": 0.25 + cell_region["x"] * 0.25,
            "y": 0.25 + cell_region["y"] * 0.25,
            "w": cell_region["w"] * 0.25,
            "h": cell_region["h"] * 0.25,
        }
        assert abs(composed["x"] - 0.25) < 0.001
        assert abs(composed["y"] - 0.25) < 0.001
        assert abs(composed["w"] - 0.0625) < 0.001


# ── User activity detection tests ─────────────────────────────────────


class TestUserActivity:
    """Test user input detection."""

    def test_user_recently_active_function_exists(self) -> None:
        from hort.extensions.core.llming_lens.provider import _user_recently_active
        # Just verify it returns a bool (actual behavior depends on macOS state)
        result = _user_recently_active(0.0)
        assert isinstance(result, bool)
