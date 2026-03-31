"""Standalone MCP server — discovers MCPMixin extensions and serves their tools.

Usage::

    # Stdio mode (for local Claude Code)
    python -m hort.mcp.server

    # SSE mode (for containerized Claude Code)
    python -m hort.mcp.server --sse --port 9100

    # With app filter for screen tools
    python -m hort.mcp.server --app-filter "Chrome*,iTerm*"
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from hort.ext.mcp import MCPMixin
from hort.ext.plugin import PluginBase, PluginConfig, PluginContext
from hort.ext.scheduler import PluginScheduler
from hort.ext.store import FilePluginStore
from hort.ext.file_store import LocalFileStore
from hort.mcp.bridge import MCPBridge, MCPSseServer, run_stdio

logger = logging.getLogger(__name__)


def _load_mcp_extensions(app_filter: str | None = None) -> list[Any]:
    """Discover and load all MCPMixin extensions. Returns provider instances."""
    from hort.ext.registry import _parse_manifest

    extensions_dir = Path(__file__).parent.parent / "extensions"
    providers: list[Any] = []

    if not extensions_dir.exists():
        return providers

    for manifest_path in extensions_dir.rglob("extension.json"):
        ext_dir = manifest_path.parent
        manifest = _parse_manifest(manifest_path, ext_dir)
        if manifest is None or not manifest.mcp:
            continue
        if manifest.platforms and sys.platform not in manifest.platforms:
            continue

        entry = manifest.entry_point
        if not entry or ":" not in entry:
            continue
        module_name, class_name = entry.split(":", 1)
        module_file = ext_dir / f"{module_name}.py"
        if not module_file.exists():
            continue

        spec = importlib.util.spec_from_file_location(
            f"hort.extensions.{manifest.name}.{module_name}", module_file
        )
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            logger.exception("Failed to load %s", manifest.name)
            continue
        cls = getattr(mod, class_name, None)
        if cls is None:
            continue

        instance = cls()
        config: dict[str, Any] = {}
        if app_filter:
            config["app_filter"] = app_filter

        # Inject plugin context if it's a PluginBase
        if isinstance(instance, PluginBase):
            ctx = PluginContext(
                plugin_id=manifest.name,
                store=FilePluginStore(manifest.name),
                files=LocalFileStore(manifest.name),
                config=PluginConfig(manifest.name, _raw=config),
                scheduler=PluginScheduler(manifest.name),
                logger=logging.getLogger(f"hort.mcp.{manifest.name}"),
            )
            instance._ctx = ctx

        try:
            instance.activate(config)
        except Exception:
            logger.exception("Failed to activate %s", manifest.name)
            continue

        if isinstance(instance, MCPMixin):
            tools = instance.get_mcp_tools()
            if tools:
                providers.append(instance)
                logger.info(
                    "Loaded %s (%d tools)", manifest.name, len(tools)
                )

    return providers


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="openhort MCP bridge server")
    parser.add_argument(
        "--sse", action="store_true", help="Run as SSE server (for containers)"
    )
    parser.add_argument(
        "--port", type=int, default=9100, help="SSE server port (default: 9100)"
    )
    parser.add_argument(
        "--app-filter",
        default=None,
        help="Comma-separated app name patterns (glob) for screen tools",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    providers = _load_mcp_extensions(args.app_filter)
    bridge = MCPBridge(providers)
    total_tools = sum(len(p.get_mcp_tools()) for p in providers)
    logger.info("Bridge ready: %d providers, %d tools", len(providers), total_tools)

    if args.sse:

        async def _run_sse() -> None:
            server = MCPSseServer(bridge, port=args.port)
            await server.start()
            logger.info("SSE server: %s", server.url)
            logger.info("Container URL: %s", server.host_url)
            try:
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                pass
            finally:
                await server.stop()

        asyncio.run(_run_sse())
    else:
        asyncio.run(run_stdio(bridge))


if __name__ == "__main__":
    main()
