"""openhort CLI — professional command-line interface.

Provides commands for server management, extension discovery,
terminal sessions, and interactive mode.

Entry point: ``hort`` (registered in pyproject.toml).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

console = Console()
err_console = Console(stderr=True)

VERSION = "0.1.0"
LOGO = """\
[bold deep_purple]      \u2571\u2572
     \u2571  \u2572     [bold white]openhort[/bold white]
    \u2571 \u2571\u2572 \u2572    [dim]Remote desktop \u00b7 AI agents \u00b7 MCP tools[/dim]
   \u2571 \u2571  \u2572 \u2572
  \u2571 \u2571    \u2572 \u2572   [dim]v{version}[/dim]
 \u2571\u2571      \u2572\u2572[/bold deep_purple]"""


def _logo() -> str:
    return LOGO.format(version=VERSION)


# ── Main group ────────────────────────────────────────────────────


@click.group(invoke_without_command=True)
@click.option("--version", is_flag=True, help="Show version and exit.")
@click.pass_context
def cli(ctx: click.Context, version: bool) -> None:
    """openhort — remote desktop viewer and AI agent framework."""
    if version:
        console.print(f"openhort {VERSION}")
        return
    if ctx.invoked_subcommand is None:
        console.print()
        console.print(_logo())
        console.print()
        console.print("  Run [bold]hort --help[/] for commands.")
        console.print()


# ── Server commands ───────────────────────────────────────────────


@cli.command()
@click.option("--dev", is_flag=True, help="Developer mode (auto-reload).")
@click.option("--port", default=8940, help="HTTP port (default: 8940).")
def start(dev: bool, port: int) -> None:
    """Start the openhort server."""
    if dev:
        os.environ["LLMING_DEV"] = "1"
    os.environ["HORT_HTTP_PORT"] = str(port)

    console.print(_logo())

    from hort.network import get_lan_ip
    lan_ip = get_lan_ip()

    mode = "[bold yellow]DEVELOPER[/] (auto-reload)" if dev else "[bold green]PRODUCTION[/]"
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Mode", mode)
    table.add_row("HTTP", f"[link]http://{lan_ip}:{port}[/link]")
    table.add_row("HTTPS", f"[link]https://{lan_ip}:{port + 10}[/link]")
    console.print(table)
    console.print()

    from hort.app import main as app_main
    app_main()


@cli.command()
def stop() -> None:
    """Stop the running openhort server."""
    result = subprocess.run(
        ["pgrep", "-f", "uvicorn hort.app"],
        capture_output=True, text=True,
    )
    pids = result.stdout.strip().splitlines()
    if not pids:
        console.print("[yellow]No openhort server running.[/]")
        return

    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    console.print(f"[green]Stopped openhort server[/] (PIDs: {', '.join(pids)})")


@cli.command()
def status() -> None:
    """Show server status and system info."""
    import platform

    import psutil
    from rich.bar import Bar
    from rich.columns import Columns

    # Check if server is running
    result = subprocess.run(
        ["pgrep", "-f", "uvicorn hort.app"],
        capture_output=True, text=True,
    )
    pids = result.stdout.strip().splitlines()
    running = len(pids) > 0

    console.print()

    # Server status panel
    if running:
        from hort.network import get_lan_ip
        lan_ip = get_lan_ip()
        server_lines = [
            "[bold green]\u25cf  Running[/]",
            "",
            f"  HTTP   [link]http://{lan_ip}:8940[/link]",
            f"  HTTPS  [link]https://{lan_ip}:8950[/link]",
            f"  PIDs   [dim]{', '.join(pids)}[/]",
        ]
    else:
        server_lines = [
            "[bold red]\u25cf  Stopped[/]",
            "",
            "  [dim]Run[/] [bold]hort start[/] [dim]to launch the server.[/]",
        ]

    console.print(Panel(
        "\n".join(server_lines),
        title="[bold]openhort[/]",
        subtitle=f"[dim]v{VERSION}[/]",
        border_style="purple",
        padding=(1, 3),
    ))

    # System metrics
    cpu = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    mem_used_gb = (mem.total - mem.available) / (1024**3)
    mem_total_gb = mem.total / (1024**3)
    mem_pct = (mem.total - mem.available) / mem.total * 100
    disk = psutil.disk_usage("/")
    disk_used_gb = disk.used / (1024**3)
    disk_total_gb = disk.total / (1024**3)
    uptime_secs = psutil.boot_time()
    import time
    uptime_h = int((time.time() - uptime_secs) / 3600)

    def _bar(pct: float) -> str:
        """Render a percentage as a colored bar."""
        filled = int(pct / 5)
        empty = 20 - filled
        if pct > 80:
            color = "red"
        elif pct > 60:
            color = "yellow"
        else:
            color = "green"
        return f"[{color}]{'━' * filled}[/][dim]{'━' * empty}[/] {pct:.0f}%"

    sys_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
    sys_table.add_column(style="bold", width=8)
    sys_table.add_column(width=35)
    sys_table.add_column(style="dim")

    sys_table.add_row("CPU", _bar(cpu), f"{psutil.cpu_count()} cores")
    sys_table.add_row("Memory", _bar(mem_pct), f"{mem_used_gb:.1f} / {mem_total_gb:.0f} GB")
    sys_table.add_row("Disk", _bar(disk.percent), f"{disk_used_gb:.0f} / {disk_total_gb:.0f} GB")

    console.print(Panel(
        sys_table,
        title="[bold]System[/]",
        border_style="dim",
        padding=(1, 1),
    ))

    # Platform info
    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column(style="dim", width=10)
    info_table.add_column()
    info_table.add_row("Host", platform.node())
    info_table.add_row("Platform", f"{platform.system()} {platform.machine()}")
    info_table.add_row("Python", sys.version.split()[0])
    info_table.add_row("Uptime", f"{uptime_h}h")

    console.print(Panel(
        info_table,
        title="[bold]Platform[/]",
        border_style="dim",
        padding=(0, 1),
    ))
    console.print()


@cli.command()
def open() -> None:
    """Open openhort in the default browser."""
    import webbrowser

    from hort.network import get_lan_ip
    lan_ip = get_lan_ip()
    url = f"http://{lan_ip}:8940"

    result = subprocess.run(
        ["pgrep", "-f", "uvicorn hort.app"],
        capture_output=True, text=True,
    )
    if not result.stdout.strip():
        err_console.print("[yellow]Server not running.[/] Start it with [bold]hort start[/]")
        return

    console.print(f"Opening [link]{url}[/link]")
    webbrowser.open(url)


# ── Extension commands ────────────────────────────────────────────


@cli.command(name="llmings")
def list_llmings() -> None:
    """List all installed llmings (extensions)."""
    ext_dir = Path(__file__).parent.parent / "llmings" / "core"

    table = Table(title="Installed Llmings", border_style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Type", style="dim")
    table.add_column("Version")
    table.add_column("Description")
    table.add_column("MCP", justify="center")
    table.add_column("Platform")

    if not ext_dir.exists():
        console.print("[yellow]No extensions directory found.[/]")
        return

    import json

    for ext_path in sorted(ext_dir.iterdir()):
        manifest_path = ext_path / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        name = f"openhort/{manifest.get('name', ext_path.name)}"
        ptype = manifest.get("llming_type", "")
        version = manifest.get("version", "")
        desc = manifest.get("description", "")
        has_mcp = "[green]yes[/]" if manifest.get("mcp") else "[dim]-[/]"
        platforms = ", ".join(manifest.get("platforms", []))

        table.add_row(name, ptype, version, desc, has_mcp, platforms)

    console.print(table)
    console.print()

    # Also check LLM extensions
    llm_dir = Path(__file__).parent.parent / "llmings" / "llms"
    if llm_dir.exists():
        llm_table = Table(title="LLM Providers", border_style="dim")
        llm_table.add_column("Name", style="bold")
        llm_table.add_column("Description")

        for ext_path in sorted(llm_dir.iterdir()):
            manifest_path = ext_path / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            name = f"openhort/{manifest.get('name', ext_path.name)}"
            desc = manifest.get("description", "")
            llm_table.add_row(name, desc)

        if llm_table.row_count:
            console.print(llm_table)
            console.print()


# ── Terminal / Watch commands ─────────────────────────────────────


@cli.command(name="watch", context_settings={"ignore_unknown_options": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def watch(args: tuple[str, ...]) -> None:
    """Manage tmux code sessions.

    \b
    hort watch                      list sessions
    hort watch claude               create/attach (runs claude)
    hort watch clauded              create/attach (dangerous mode)
    hort watch shell [cwd]          create/attach shell
    hort watch <name> [cwd]         create/attach (shell)
    hort watch read <name>          read output
    hort watch send <name> "text"   send text
    hort watch stop <name>          kill session
    """
    if not args:
        _watch_list()
        return

    sub = args[0]

    if sub in ("list", "ls"):
        _watch_list()
    elif sub == "read" and len(args) >= 2:
        _watch_read(args[1], int(args[2]) if len(args) > 2 else 30)
    elif sub == "send" and len(args) >= 3:
        _watch_send(args[1], args[2], enter="--no-enter" not in args)
    elif sub == "stop" and len(args) >= 2:
        _watch_stop(args[1])
    else:
        # Default: create/attach to session
        name = sub
        cwd = args[1] if len(args) > 1 else None
        _watch_start(name, cwd)


def _watch_list() -> None:
    from hort.tmux import list_sessions, is_busy

    sessions = list_sessions()
    if not sessions:
        console.print("[yellow]No active code sessions.[/]")
        console.print("[dim]Create one: hort watch <name>[/]")
        return

    table = Table(title="Code Sessions", border_style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Command", style="dim")
    table.add_column("Attached")

    for s in sessions:
        busy = is_busy(s.short_name)
        status = "[yellow]busy[/]" if busy else "[green]idle[/]"
        attached = "[cyan]yes[/]" if s.attached else "[dim]-[/]"
        table.add_row(s.short_name, status, s.current_command, attached)

    console.print(table)
    console.print()


def _watch_start(name: str, cwd: str | None) -> None:
    from hort.tmux import PREFIX, PRESETS, session_exists, create_session

    if session_exists(name):
        console.print(f"Attaching to [bold]{PREFIX}{name}[/]")
    else:
        # create_session resolves presets (command + permissions) internally
        session = create_session(name, cwd=cwd or os.getcwd())
        if session is None:
            err_console.print(f"[red]Failed to create session {PREFIX}{name}[/]")
            sys.exit(1)
        preset = PRESETS.get(name)
        what = (preset[0] if preset else None) or "shell"
        console.print(f"Created [bold]{PREFIX}{name}[/] ({what})")

    os.execvp("tmux", ["tmux", "attach", "-t", f"{PREFIX}{name}"])


def _watch_stop(name: str) -> None:
    from hort.tmux import kill_session, session_exists

    if not session_exists(name):
        err_console.print(f"[yellow]Session '{name}' not found.[/]")
        return

    kill_session(name)
    console.print(f"[green]Session '{name}' terminated.[/]")


def _watch_read(name: str, lines: int = 30) -> None:
    from hort.tmux import read_output, session_exists

    if not session_exists(name):
        err_console.print(f"[yellow]Session '{name}' not found.[/]")
        return

    output = read_output(name, lines=lines)
    if output:
        panel = Panel(
            output.rstrip(),
            title=f"[bold]{name}[/]",
            border_style="dim",
            expand=False,
        )
        console.print(panel)


def _watch_send(name: str, text: str, enter: bool = True) -> None:
    from hort.tmux import send_text, session_exists

    if not session_exists(name):
        err_console.print(f"[yellow]Session '{name}' not found.[/]")
        return

    ok = send_text(name, text, enter=enter)
    if ok:
        console.print(f"[green]Sent to '{name}'[/]")
    else:
        err_console.print(f"[red]Failed to send to '{name}'[/]")


# ── Hort topology ────────────────────────────────────────────────


@cli.command()
def topology() -> None:
    """Show the hort topology (wiring model)."""
    from hort.config import get_store

    tree = Tree("[bold]🏠 Root Hort[/]")

    # Show agent config
    agent_cfg = get_store().get("agent")
    if agent_cfg:
        agent_node = tree.add("[bold cyan]🤖 Agent[/]")
        agent_node.add(f"[dim]provider:[/] {agent_cfg.get('provider', 'claude-code')}")
        agent_node.add(f"[dim]model:[/] {agent_cfg.get('model', 'default')}")
        agent_node.add(f"[dim]container:[/] {agent_cfg.get('container', True)}")
        agent_node.add(f"[dim]dangerous_mode:[/] {agent_cfg.get('dangerous_mode', False)}")

    # Show connectors
    connectors_node = tree.add("[bold]📡 Connectors[/]")
    for key in ["connector.telegram", "connector.lan", "connector.cloud"]:
        cfg = get_store().get(key)
        if cfg:
            name = key.split(".")[-1]
            enabled = cfg.get("enabled", False)
            status = "[green]enabled[/]" if enabled else "[dim]disabled[/]"
            connectors_node.add(f"📦 {name} — {status}")

    # Show extensions
    import json
    ext_dir = Path(__file__).parent.parent / "llmings" / "core"
    if ext_dir.exists():
        ext_node = tree.add("[bold]📦 Llmings[/]")
        for ext_path in sorted(ext_dir.iterdir()):
            manifest_path = ext_path / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                m = json.loads(manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            icon = "🔧" if m.get("mcp") else "📦"
            ext_node.add(f"{icon} openhort/{m.get('name', ext_path.name)}")

    # Show code sessions
    try:
        from hort.tmux import list_sessions, is_busy
        sessions = list_sessions()
        if sessions:
            term_node = tree.add("[bold]🖥 Code Sessions[/]")
            for s in sessions:
                busy = is_busy(s.short_name)
                status = "[yellow]busy[/]" if busy else "[green]idle[/]"
                term_node.add(f"📟 {s.short_name} — {status}")
    except Exception:
        pass

    console.print()
    console.print(tree)
    console.print()


# ── Config commands ───────────────────────────────────────────────


@cli.command()
@click.argument("key", required=False)
def config(key: str | None) -> None:
    """Show configuration (all or specific key).

    \b
    Examples:
      hort config                  # show all
      hort config agent            # show agent config
      hort config connector.telegram
    """
    from hort.config import get_store
    import yaml

    store = get_store()

    if key:
        data = store.get(key)
        if not data:
            console.print(f"[yellow]No config for '{key}'[/]")
            return
        console.print(Panel(
            yaml.dump(data, default_flow_style=False).rstrip(),
            title=f"[bold]{key}[/]",
            border_style="dim",
        ))
    else:
        # Show all config
        config_path = Path("hort-config.yaml")
        if config_path.exists():
            console.print(Panel(
                config_path.read_text().rstrip(),
                title="[bold]hort-config.yaml[/]",
                border_style="dim",
            ))
        else:
            console.print("[yellow]No hort-config.yaml found.[/]")


# ── Interactive mode ──────────────────────────────────────────────


@cli.command()
def interactive() -> None:
    """Start interactive mode (REPL)."""
    console.print(_logo())
    console.print("  [dim]Type 'help' for commands, 'quit' to exit.[/]\n")

    commands = {
        "help": "Show available commands",
        "status": "Server status and system info",
        "llmings": "List installed llmings",
        "watch": "List code sessions",
        "watch <name>": "Create/attach to a session",
        "watch read <name>": "Read session output",
        "watch send <name> text": "Send text to session",
        "watch stop <name>": "Kill session",
        "topology": "Show hort topology",
        "config [key]": "Show configuration",
        "open": "Open browser",
        "stop": "Stop server",
        "quit": "Exit interactive mode",
    }

    while True:
        try:
            raw = console.input("[bold purple]hort>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye![/]")
            break

        if not raw:
            continue

        if raw in ("quit", "exit", "q"):
            console.print("[dim]Bye![/]")
            break

        if raw == "help":
            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column(style="bold")
            table.add_column(style="dim")
            for cmd, desc in commands.items():
                table.add_row(cmd, desc)
            console.print(table)
            console.print()
            continue

        parts = raw.split()
        try:
            if parts[0] == "status":
                status.invoke(click.Context(status))
            elif parts[0] == "llmings":
                list_llmings.invoke(click.Context(list_llmings))
            elif parts[0] == "topology":
                topology.invoke(click.Context(topology))
            elif parts[0] == "config":
                key_arg = parts[1] if len(parts) > 1 else None
                ctx = click.Context(config)
                ctx.params["key"] = key_arg
                config.invoke(ctx)
            elif parts[0] == "watch":
                if len(parts) == 1:
                    _watch_list()
                elif parts[1] == "list":
                    _watch_list()
                elif parts[1] == "read" and len(parts) >= 3:
                    _watch_read(parts[2])
                elif parts[1] == "send" and len(parts) >= 4:
                    _watch_send(parts[2], " ".join(parts[3:]))
                elif parts[1] == "stop" and len(parts) >= 3:
                    _watch_stop(parts[2])
                else:
                    console.print(f"[dim]Use: hort watch {parts[1]} (exits interactive mode)[/]")
            elif parts[0] == "open":
                open.invoke(click.Context(open))
            elif parts[0] == "stop":
                stop.invoke(click.Context(stop))
            elif parts[0] == "start":
                console.print("[dim]Use: hort start (exits interactive mode)[/]")
            else:
                console.print(f"[yellow]Unknown command: {raw}[/]  Type 'help' for commands.")
        except SystemExit:
            pass
        except Exception as exc:
            err_console.print(f"[red]Error: {exc}[/]")


# ── Entry point ───────────────────────────────────────────────────


def main() -> None:
    """CLI entry point (registered in pyproject.toml)."""
    cli()


if __name__ == "__main__":
    main()
