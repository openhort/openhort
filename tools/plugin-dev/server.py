"""Plugin Debugger — standalone app to develop and test plugins in isolation.

Usage:
    poetry run python tools/plugin-dev/server.py <plugin_path>

Example:
    poetry run python tools/plugin-dev/server.py hort/extensions/core/system_monitor

Features:
- Loads a single plugin from disk (Python + JS)
- Provides real adapters (FilePluginStore, LocalFileStore, config, scheduler)
- Shows debug logs in browser via WebSocket
- Renders plugin UI with all shared components (hort-ext, hort-widgets, Quasar)
- Allows simulating states via API
- Hot-reloads on file changes
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from hort.ext.file_store import LocalFileStore
from hort.ext.manifest import ExtensionManifest
from hort.ext.plugin import PluginBase, PluginConfig, PluginContext
from hort.ext.scheduler import JobSpec, PluginScheduler, ScheduledMixin
from hort.ext.store import FilePluginStore

logger = logging.getLogger("plugin-dev")

# ===== Log capture for browser streaming =====

_log_buffer: list[dict[str, Any]] = []
_log_ws_clients: list[WebSocket] = []


class BrowserLogHandler(logging.Handler):
    """Captures log records and sends them to connected browser WebSockets."""

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "time": time.strftime("%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "name": record.name,
            "msg": self.format(record),
        }
        _log_buffer.append(entry)
        if len(_log_buffer) > 500:
            _log_buffer.pop(0)
        for ws in list(_log_ws_clients):
            try:
                asyncio.get_event_loop().create_task(
                    ws.send_text(json.dumps({"type": "log", **entry}))
                )
            except Exception:
                pass


# ===== Plugin loading =====


def load_plugin(
    plugin_dir: Path, data_dir: Path
) -> tuple[ExtensionManifest, object | None, PluginContext]:
    """Load a plugin from a directory. Returns (manifest, instance, context)."""
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.json in {plugin_dir}")

    manifest_data = json.loads(manifest_path.read_text())
    manifest_data["path"] = str(plugin_dir)
    manifest = ExtensionManifest(**manifest_data)

    # Create context
    plugin_id = manifest.name
    store = FilePluginStore(plugin_id, base_dir=data_dir)
    files = LocalFileStore(plugin_id, base_dir=data_dir)
    config_raw: dict[str, Any] = {}
    config_path = data_dir / plugin_id / "config.json"
    if config_path.exists():
        try:
            config_raw = json.loads(config_path.read_text())
        except Exception:
            pass

    feature_defaults = {
        name: ft.default for name, ft in manifest.features.items()
    }
    config = PluginConfig(
        plugin_id=plugin_id, _raw=config_raw, _feature_defaults=feature_defaults
    )
    scheduler = PluginScheduler(plugin_id)
    plugin_logger = logging.getLogger(f"hort.plugin.{plugin_id}")

    context = PluginContext(
        plugin_id=plugin_id,
        store=store,
        files=files,
        config=config,
        scheduler=scheduler,
        logger=plugin_logger,
    )

    # Load Python module if entry_point is set
    instance = None
    if manifest.entry_point:
        module_name, class_name = manifest.entry_point.split(":")
        module_path = plugin_dir / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(
            f"plugin.{plugin_id}.{module_name}", str(module_path)
        )
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            cls = getattr(module, class_name)
            instance = cls()
            if isinstance(instance, PluginBase):
                instance._ctx = context
            instance.activate(config_raw)

    return manifest, instance, context


def start_jobs(
    manifest: ExtensionManifest, instance: object, context: PluginContext
) -> None:
    """Start scheduled jobs. Must be called from within a running event loop."""
    if instance is None:
        return
    jobs: list[JobSpec] = []
    for jm in manifest.jobs:
        jobs.append(
            JobSpec(
                id=jm.id,
                fn_name=jm.method,
                interval_seconds=jm.interval_seconds,
                run_on_activate=jm.run_on_activate,
                enabled_feature=jm.enabled_feature,
            )
        )
    if isinstance(instance, ScheduledMixin):
        jobs.extend(instance.get_jobs())
    for job in jobs:
        if job.enabled_feature and not context.config.is_feature_enabled(
            job.enabled_feature
        ):
            logger.info("Skipping job %s (feature %s disabled)", job.id, job.enabled_feature)
            continue
        fn = getattr(instance, job.fn_name, None)
        if fn:
            context.scheduler.start_job(job, fn)


# ===== App factory =====


def create_app(plugin_dir: Path) -> FastAPI:
    """Create the debugger FastAPI app for a specific plugin."""
    data_dir = Path("/tmp/hort-plugin-dev")
    data_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Plugin Debugger")

    # Mount openhort static files (vendor libs)
    vendor_dir = PROJECT_ROOT / "hort" / "static" / "vendor"
    app.mount("/static/vendor", StaticFiles(directory=str(vendor_dir)), name="vendor")

    # Mount plugin static files
    plugin_static = plugin_dir / "static"
    if plugin_static.is_dir():
        app.mount(
            "/ext/plugin/static",
            StaticFiles(directory=str(plugin_static)),
            name="plugin-static",
        )

    # Load plugin
    manifest, instance, context = load_plugin(plugin_dir, data_dir)
    app.state.manifest = manifest
    app.state.instance = instance
    app.state.context = context

    # Start scheduler jobs on app startup (needs running event loop)
    @app.on_event("startup")
    async def _start_jobs() -> None:
        start_jobs(manifest, instance, context)

    # Mount plugin router if available (both prefixed and root for debugger convenience)
    if instance and hasattr(instance, "get_router"):
        router = instance.get_router()
        if router:
            app.include_router(router, prefix=f"/api/plugins/{manifest.name}")
            app.include_router(router)  # also mount at root for debugger

    # ===== API routes =====

    @app.get("/api/plugin/info")
    async def plugin_info() -> Response:
        m = app.state.manifest
        return Response(
            content=json.dumps({
                "name": m.name,
                "version": m.version,
                "description": m.description,
                "icon": m.icon,
                "llming_type": m.llming_type,
                "features": {
                    k: {"description": v.description, "default": v.default, "enabled": context.config.is_feature_enabled(k)}
                    for k, v in m.features.items()
                },
                "jobs": [{"id": j.id, "method": j.method, "interval": j.interval_seconds} for j in m.jobs],
                "mcp": m.mcp,
                "documents": m.documents,
                "ui_widgets": m.ui_widgets,
                "capabilities": m.capabilities,
                "running_jobs": context.scheduler.running_jobs,
            }),
            media_type="application/json",
        )

    @app.get("/api/plugin/store")
    async def list_store() -> Response:
        keys = await context.store.list_keys()
        items = {}
        for k in keys[:100]:
            items[k] = await context.store.get(k)
        return Response(content=json.dumps(items, default=str), media_type="application/json")

    @app.post("/api/plugin/store/{key}")
    async def put_store(key: str, request: Request) -> Response:
        data = await request.json()
        await context.store.put(key, data)
        return Response(content=json.dumps({"ok": True}), media_type="application/json")

    @app.delete("/api/plugin/store/{key}")
    async def delete_store(key: str) -> Response:
        ok = await context.store.delete(key)
        return Response(content=json.dumps({"deleted": ok}), media_type="application/json")

    @app.get("/api/plugin/files")
    async def list_files() -> Response:
        files = await context.files.list_files()
        return Response(
            content=json.dumps([{"name": f.name, "mime": f.mime_type, "size": f.size} for f in files]),
            media_type="application/json",
        )

    @app.post("/api/plugin/features/{feature}")
    async def toggle_feature(feature: str, request: Request) -> Response:
        data = await request.json()
        context.config.set_feature(feature, data.get("enabled", True))
        return Response(content=json.dumps({"ok": True}), media_type="application/json")

    @app.post("/api/plugin/simulate")
    async def simulate_state(request: Request) -> Response:
        """Inject data into the plugin store to simulate states."""
        data = await request.json()
        for key, value in data.items():
            await context.store.put(key, value)
        return Response(content=json.dumps({"ok": True, "keys": list(data.keys())}), media_type="application/json")

    @app.post("/api/plugin/trigger-job/{job_id}")
    async def trigger_job(job_id: str) -> Response:
        """Manually trigger a job."""
        inst = app.state.instance
        if inst is None:
            return Response(content=json.dumps({"error": "No plugin instance"}), media_type="application/json", status_code=400)
        for jm in app.state.manifest.jobs:
            if jm.id == job_id:
                fn = getattr(inst, jm.method, None)
                if fn:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, fn)
                    return Response(content=json.dumps({"ok": True, "job": job_id}), media_type="application/json")
        if isinstance(inst, ScheduledMixin):
            for js in inst.get_jobs():
                if js.id == job_id:
                    fn = getattr(inst, js.fn_name, None)
                    if fn:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, fn)
                        return Response(content=json.dumps({"ok": True, "job": job_id}), media_type="application/json")
        return Response(content=json.dumps({"error": f"Job {job_id} not found"}), media_type="application/json", status_code=404)

    # MCP tool testing
    @app.get("/api/plugin/mcp/tools")
    async def mcp_tools() -> Response:
        from hort.ext.mcp import MCPMixin
        inst = app.state.instance
        if inst and isinstance(inst, MCPMixin):
            tools = inst.get_mcp_tools()
            return Response(
                content=json.dumps([{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]),
                media_type="application/json",
            )
        return Response(content="[]", media_type="application/json")

    @app.post("/api/plugin/mcp/execute/{tool_name}")
    async def mcp_execute(tool_name: str, request: Request) -> Response:
        from hort.ext.mcp import MCPMixin
        inst = app.state.instance
        if inst and isinstance(inst, MCPMixin):
            data = await request.json()
            result = await inst.execute_mcp_tool(tool_name, data.get("arguments", {}))
            return Response(
                content=json.dumps({"content": result.content, "is_error": result.is_error}),
                media_type="application/json",
            )
        return Response(content=json.dumps({"error": "Plugin has no MCP tools"}), media_type="application/json", status_code=400)

    # Document testing
    @app.get("/api/plugin/documents")
    async def list_documents() -> Response:
        from hort.ext.documents import DocumentMixin
        inst = app.state.instance
        if inst and isinstance(inst, DocumentMixin):
            docs = inst.get_documents()
            results = []
            for d in docs:
                content = d.content
                if d.content_fn:
                    fn = getattr(inst, d.content_fn, None)
                    if fn:
                        loop = asyncio.get_event_loop()
                        content = await loop.run_in_executor(None, fn)
                results.append({"uri": d.uri, "name": d.name, "description": d.description, "content": content})
            return Response(content=json.dumps(results), media_type="application/json")
        return Response(content="[]", media_type="application/json")

    # Log streaming
    @app.websocket("/ws/logs")
    async def log_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        _log_ws_clients.append(websocket)
        try:
            # Send buffered logs
            for entry in _log_buffer[-50:]:
                await websocket.send_text(json.dumps({"type": "log", **entry}))
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            _log_ws_clients.remove(websocket)

    # Main debugger UI
    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(_debugger_html(manifest))

    return app


def _debugger_html(manifest: ExtensionManifest) -> str:
    """Generate the debugger HTML page."""
    ui_script = ""
    if manifest.ui_script:
        ui_script = f'<script src="/ext/plugin/static/{manifest.ui_script.replace("static/", "")}"></script>'

    widgets_str = json.dumps(manifest.ui_widgets)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Plugin Debugger — {manifest.name}</title>
<link rel="stylesheet" href="/static/vendor/phosphor/regular.css">
<link rel="stylesheet" href="/static/vendor/phosphor/bold.css">
<link rel="stylesheet" href="/static/vendor/phosphor/fill.css">
<link rel="stylesheet" href="/static/vendor/material-icons.css">
<link rel="stylesheet" href="/static/vendor/quasar.prod.css">
<link rel="stylesheet" href="/static/vendor/xterm.css">
<style>
:root {{
  --el-bg: #0a0e1a; --el-surface: #111827; --el-surface-elevated: #1a2436;
  --el-border: #1e3a5f; --el-primary: #3b82f6; --el-accent: #6366f1;
  --el-text: #f0f4ff; --el-text-dim: #94a3b8;
  --el-danger: #ef4444; --el-success: #22c55e; --el-warning: #f59e0b;
  --el-widget-radius: 10px; --el-widget-padding: 16px;
}}
body {{ background: var(--el-bg); color: var(--el-text); font-family: system-ui; margin: 0; }}
.debugger {{ display: flex; height: 100vh; }}
.sidebar {{ width: 320px; background: var(--el-surface); border-right: 1px solid var(--el-border); overflow-y: auto; padding: 16px; flex-shrink: 0; }}
.main {{ flex: 1; overflow-y: auto; padding: 16px; }}
.sidebar h3 {{ color: var(--el-primary); margin: 0 0 8px 0; font-size: 14px; }}
.sidebar .section {{ margin-bottom: 16px; }}
.log-panel {{ background: #0d1117; border: 1px solid var(--el-border); border-radius: 8px; padding: 8px; font-family: monospace; font-size: 11px; max-height: 300px; overflow-y: auto; }}
.log-entry {{ padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }}
.log-entry .level {{ font-weight: bold; min-width: 50px; display: inline-block; }}
.log-entry .level-ERROR {{ color: var(--el-danger); }}
.log-entry .level-WARNING {{ color: var(--el-warning); }}
.log-entry .level-INFO {{ color: var(--el-success); }}
.log-entry .level-DEBUG {{ color: var(--el-text-dim); }}
.btn {{ padding: 6px 12px; border: 1px solid var(--el-border); border-radius: 6px; background: var(--el-surface-elevated); color: var(--el-text); cursor: pointer; font-size: 12px; }}
.btn:hover {{ background: var(--el-primary); }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; background: var(--el-surface-elevated); color: var(--el-text-dim); margin: 2px; }}
.badge.on {{ background: var(--el-success); color: #fff; }}
.store-viewer {{ font-family: monospace; font-size: 11px; background: #0d1117; padding: 8px; border-radius: 6px; max-height: 200px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }}
.plugin-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }}
.plugin-header i {{ font-size: 32px; color: var(--el-primary); }}
.plugin-header h1 {{ margin: 0; font-size: 20px; }}
.plugin-header .version {{ color: var(--el-text-dim); font-size: 13px; }}
</style>
</head>
<body>
<script src="/static/vendor/vue.global.prod.js"></script>
<script src="/static/vendor/quasar.umd.prod.js"></script>
<script src="/static/vendor/plotly.min.js"></script>
<script src="/static/vendor/hort-ext.js"></script>
<script src="/static/vendor/hort-widgets.js"></script>
{ui_script}
<div id="app">
  <div class="debugger">
    <!-- Sidebar: Plugin info, controls, logs -->
    <div class="sidebar">
      <div class="plugin-header">
        <i :class="info.icon || 'ph ph-puzzle-piece'"></i>
        <div>
          <h1>{{{{ info.name }}}}</h1>
          <div class="version">v{{{{ info.version }}}} &middot; {{{{ info.llming_type || 'llming' }}}}</div>
        </div>
      </div>
      <div style="color:var(--el-text-dim);font-size:12px;margin-bottom:12px">{{{{ info.description }}}}</div>

      <!-- Features -->
      <div class="section" v-if="Object.keys(info.features || {{}}).length">
        <h3><i class="ph ph-toggle-right"></i> Features</h3>
        <div v-for="(ft, name) in info.features" :key="name" style="display:flex;align-items:center;gap:8px;margin:4px 0">
          <input type="checkbox" :checked="ft.enabled" @change="toggleFeature(name, $event.target.checked)">
          <span style="font-size:12px">{{{{ name }}}} <span style="color:var(--el-text-dim)">— {{{{ ft.description }}}}</span></span>
        </div>
      </div>

      <!-- Jobs -->
      <div class="section" v-if="info.jobs && info.jobs.length">
        <h3><i class="ph ph-clock"></i> Jobs</h3>
        <div v-for="j in info.jobs" :key="j.id" style="display:flex;align-items:center;gap:6px;margin:4px 0">
          <span class="badge" :class="{{on: (info.running_jobs||[]).includes(j.id)}}">{{{{ j.id }}}}</span>
          <span style="font-size:11px;color:var(--el-text-dim)">{{{{ j.interval }}}}s</span>
          <button class="btn" @click="triggerJob(j.id)" style="padding:2px 8px;font-size:11px">Run</button>
        </div>
      </div>

      <!-- MCP Tools -->
      <div class="section" v-if="mcpTools.length">
        <h3><i class="ph ph-wrench"></i> MCP Tools</h3>
        <div v-for="t in mcpTools" :key="t.name" style="margin:4px 0">
          <span style="font-size:12px;font-weight:600">{{{{ t.name }}}}</span>
          <div style="font-size:11px;color:var(--el-text-dim)">{{{{ t.description }}}}</div>
          <button class="btn" @click="executeTool(t.name)" style="margin-top:2px;padding:2px 8px;font-size:11px">Execute</button>
          <div v-if="toolResults[t.name]" style="font-size:11px;color:var(--el-success);margin-top:2px">{{{{ toolResults[t.name] }}}}</div>
        </div>
      </div>

      <!-- Documents -->
      <div class="section" v-if="documents.length">
        <h3><i class="ph ph-file-text"></i> Documents</h3>
        <div v-for="d in documents" :key="d.uri" style="margin:4px 0">
          <span style="font-size:12px;font-weight:600">{{{{ d.name }}}}</span>
          <div style="font-size:11px;color:var(--el-text-dim)">{{{{ d.content ? d.content.substring(0, 100) + '...' : d.description }}}}</div>
        </div>
      </div>

      <!-- Store Viewer -->
      <div class="section">
        <h3><i class="ph ph-database"></i> Store <button class="btn" @click="refreshStore" style="padding:2px 8px;font-size:11px;float:right">Refresh</button></h3>
        <div class="store-viewer">{{{{ JSON.stringify(storeData, null, 2) }}}}</div>
      </div>

      <!-- Logs -->
      <div class="section">
        <h3><i class="ph ph-terminal"></i> Logs <button class="btn" @click="logs=[]" style="padding:2px 8px;font-size:11px;float:right">Clear</button></h3>
        <div class="log-panel" ref="logPanel">
          <div v-for="(log, i) in logs" :key="i" class="log-entry">
            <span class="level" :class="'level-'+log.level">{{{{ log.level }}}}</span>
            <span style="color:var(--el-text-dim)">{{{{ log.time }}}}</span>
            <span>{{{{ log.msg }}}}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Main: Plugin UI rendering -->
    <div class="main">
      <div style="margin-bottom:12px;display:flex;gap:8px;align-items:center">
        <h2 style="margin:0;font-size:16px"><i class="ph ph-monitor"></i> Plugin UI</h2>
        <span v-for="w in info.ui_widgets || []" :key="w" class="badge">{{{{ w }}}}</span>
      </div>
      <div id="plugin-render">
        <component v-for="w in (info.ui_widgets || [])" :key="w" :is="w" />
      </div>
      <div v-if="!(info.ui_widgets || []).length" style="color:var(--el-text-dim);text-align:center;padding:40px">
        No UI widgets defined in this plugin.
      </div>
    </div>
  </div>
</div>

<script>
const {{ createApp, ref, reactive, onMounted, nextTick }} = Vue;

const app = createApp({{
  setup() {{
    const info = ref({{}});
    const storeData = ref({{}});
    const mcpTools = ref([]);
    const documents = ref([]);
    const toolResults = reactive({{}});
    const logs = ref([]);
    const logPanel = ref(null);

    async function refresh() {{
      info.value = await fetch('/api/plugin/info').then(r => r.json());
      await refreshStore();
      mcpTools.value = await fetch('/api/plugin/mcp/tools').then(r => r.json());
      documents.value = await fetch('/api/plugin/documents').then(r => r.json());
    }}

    async function refreshStore() {{
      storeData.value = await fetch('/api/plugin/store').then(r => r.json());
    }}

    async function toggleFeature(name, enabled) {{
      await fetch('/api/plugin/features/' + name, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{enabled}}),
      }});
      await refresh();
    }}

    async function triggerJob(id) {{
      await fetch('/api/plugin/trigger-job/' + id, {{method: 'POST'}});
      await refreshStore();
      await refresh();
    }}

    async function executeTool(name) {{
      const resp = await fetch('/api/plugin/mcp/execute/' + name, {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{arguments: {{}}}}),
      }});
      const data = await resp.json();
      toolResults[name] = data.content?.map(c => c.text || JSON.stringify(c)).join(' ') || JSON.stringify(data);
    }}

    // Log WebSocket
    onMounted(() => {{
      refresh();
      setInterval(refresh, 5000);
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(proto + '://' + location.host + '/ws/logs');
      ws.onmessage = (e) => {{
        const msg = JSON.parse(e.data);
        if (msg.type === 'log') {{
          logs.value.push(msg);
          if (logs.value.length > 200) logs.value.shift();
          nextTick(() => {{ if (logPanel.value) logPanel.value.scrollTop = logPanel.value.scrollHeight; }});
        }}
      }};
    }});

    return {{ info, storeData, mcpTools, documents, toolResults, logs, logPanel,
              refresh, refreshStore, toggleFeature, triggerJob, executeTool }};
  }},
}});

app.use(Quasar, {{ config: {{ dark: true }} }});
if (typeof LlmingClient !== 'undefined') {{
  LlmingClient.activateAll(app, Quasar, {{}});
}}
app.mount('#app');
</script>
</body>
</html>"""


# ===== Main =====


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tools/plugin-dev/server.py <plugin_path>")
        print("Example: python tools/plugin-dev/server.py hort/extensions/core/system_monitor")
        sys.exit(1)

    plugin_dir = Path(sys.argv[1]).resolve()
    if not (plugin_dir / "manifest.json").exists():
        print(f"Error: No manifest.json in {plugin_dir}")
        sys.exit(1)

    # Set up logging
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    root_logger = logging.getLogger()
    root_logger.addHandler(BrowserLogHandler())

    print(f"\n  Plugin Debugger")
    print(f"  Loading: {plugin_dir}")
    print(f"  URL: http://localhost:8941\n")

    app = create_app(plugin_dir)
    uvicorn.run(app, host="0.0.0.0", port=8941, log_level="info")


if __name__ == "__main__":
    main()
