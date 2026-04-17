"""Vue SFC loader — compiles .vue files to LlmingClient JS at serve time.

Supports both Options API (<script>) and Composition API (<script setup>).
Standard Vue/Quasar imports are rewritten to use the global UMD objects.

Llming API is optional — available in <script setup> via:
  const llming = inject('llming')      // standard Vue inject
  const llming = useLlming()           // composable (import from 'llming')
  $llming.vault.get(key)               // closure variable (convenience)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cache compiled JS by file hash
_cache: dict[str, str] = {}


def compile_vue(vue_path: Path, llming_name: str, *, mode: str = "card") -> str:
    """Compile a .vue file to a LlmingClient JS module.

    Args:
        vue_path: Path to the .vue file.
        llming_name: Directory name (e.g. 'system_monitor').
        mode: 'card' (grid card, creates LlmingClient) or 'app' (full app, extends existing).
    """
    content = vue_path.read_text()
    file_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

    cache_key = f"{vue_path}:{file_hash}:{mode}"
    if cache_key in _cache:
        return _cache[cache_key]

    template, script_body, style, is_setup = _parse_sfc(content)

    # Read manifest.json for icon/description if present
    manifest_dir = vue_path.parent
    if manifest_dir.name == "app":
        manifest_dir = manifest_dir.parent  # app/index.vue → look in parent
    manifest_path = manifest_dir / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Use manifest name (hyphenated) if available, else convert underscores
    component_id = manifest.get("name", llming_name.replace("_", "-"))
    icon = manifest.get("icon", "ph ph-puzzle-piece")
    description = manifest.get("description", "")

    if mode == "app":
        app_name = f"{component_id}-app"
        if is_setup:
            js = _generate_app_setup(component_id, app_name, template, script_body, style)
        else:
            js = _generate_app_options(component_id, app_name, template, script_body, style)
    else:
        panel_name = f"{component_id}-card"
        if is_setup:
            js = _generate_setup(component_id, panel_name, template, script_body, style, icon, description)
        else:
            js = _generate_options(component_id, panel_name, template, script_body, style, icon, description)

    _cache[cache_key] = js
    return js


# ---- SFC Parsing ----


def _parse_sfc(content: str) -> tuple[str, str, str, bool]:
    """Parse a Vue SFC into (template, script_body, style_css, is_setup)."""
    template = _extract_block(content, "template") or "<div>No template</div>"
    is_setup = bool(re.search(r"<script\s+setup[^>]*>", content))
    script = _extract_block(content, "script") or ""
    style = _extract_block(content, "style") or ""
    return template, script, style, is_setup


def _extract_block(content: str, tag: str) -> str:
    """Extract content between <tag ...>...</tag>."""
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", content, re.DOTALL)
    return match.group(1).strip() if match else ""


# ---- Import Transformation ----


def _transform_imports(code: str) -> tuple[str, set[str], set[str]]:
    """Remove import statements, collect Vue and Quasar imports.

    Returns (cleaned_code, vue_imports, quasar_imports).
    """
    vue_imports: set[str] = set()
    quasar_imports: set[str] = set()
    lines = []

    for line in code.split("\n"):
        stripped = line.strip()

        # import { ref, computed } from 'vue'
        m = re.match(r"import\s*\{([^}]+)\}\s*from\s*['\"]vue['\"];?\s*$", stripped)
        if m:
            for name in m.group(1).split(","):
                name = name.strip()
                if name:
                    vue_imports.add(name)
            continue

        # import { useQuasar } from 'quasar'
        m = re.match(r"import\s*\{([^}]+)\}\s*from\s*['\"]quasar['\"];?\s*$", stripped)
        if m:
            for name in m.group(1).split(","):
                name = name.strip()
                if name:
                    quasar_imports.add(name)
            continue

        # import { useLlming } from 'llming' — provided in wrapper
        if re.match(r"import\s*\{[^}]*\}\s*from\s*['\"]llming['\"];?\s*$", stripped):
            continue

        # Other imports — warn (no bundler)
        if re.match(r"import\s+", stripped):
            logger.warning("Unsupported import in card.vue (no bundler): %s", stripped)
            continue

        lines.append(line)

    return "\n".join(lines), vue_imports, quasar_imports


# ---- Binding Collection ----


def _collect_setup_bindings(code: str) -> list[str]:
    """Extract top-level const/let/function names from <script setup> body.

    Tracks brace depth to skip nested declarations.
    """
    bindings: list[str] = []
    depth = 0

    for line in code.split("\n"):
        depth_at_start = depth

        # Update depth — skip characters inside string literals
        in_str: str | None = None
        prev = ""
        for ch in line:
            if in_str:
                if ch == in_str and prev != "\\":
                    in_str = None
                prev = ch
                continue
            if ch in ("\"", "'", "`"):
                in_str = ch
                prev = ch
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
            prev = ch

        # Only top-level declarations (depth 0 at line start)
        if depth_at_start != 0:
            continue

        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        # const/let name = ...
        m = re.match(r"(?:const|let)\s+(\w+)\s*=", stripped)
        if m:
            bindings.append(m.group(1))
            continue

        # const { a, b } = ...
        m = re.match(r"(?:const|let)\s+\{([^}]+)\}\s*=", stripped)
        if m:
            for name in m.group(1).split(","):
                name = name.strip()
                if ":" in name:
                    name = name.split(":")[-1].strip()
                if name:
                    bindings.append(name)
            continue

        # const [a, b] = ...
        m = re.match(r"(?:const|let)\s+\[([^\]]+)\]\s*=", stripped)
        if m:
            for name in m.group(1).split(","):
                name = name.strip()
                if name and not name.startswith("..."):
                    bindings.append(name)
            continue

        # function name( / async function name(
        m = re.match(r"(?:async\s+)?function\s+(\w+)\s*\(", stripped)
        if m:
            bindings.append(m.group(1))

    return bindings


# ---- JS Generation: <script setup> ----


def _generate_setup(
    component_id: str,
    panel_name: str,
    template: str,
    script_body: str,
    style: str,
    icon: str,
    description: str,
) -> str:
    """Generate JS for <script setup> components."""
    code, vue_imports, quasar_imports = _transform_imports(script_body)
    bindings = _collect_setup_bindings(code)

    # Vue destructure
    vue_line = ""
    if vue_imports:
        vue_line = f"const {{ {', '.join(sorted(vue_imports))} }} = Vue;"

    # Quasar shims
    quasar_lines = ""
    if "useQuasar" in quasar_imports:
        quasar_lines = (
            "const useQuasar = () => ({\n"
            "            notify: (opts) => Quasar.Notify.create(opts),\n"
            "            dialog: (opts) => Quasar.Dialog.create(opts),\n"
            "            loading: Quasar.Loading,\n"
            "            platform: Quasar.Platform,\n"
            "            screen: Quasar.Screen,\n"
            "            dark: Quasar.Dark,\n"
            "          });"
        )

    # Return statement
    return_stmt = ""
    if bindings:
        return_stmt = f"return {{ {', '.join(bindings)} }};"

    # Indent user code for readability
    user_code = "\n".join(f"          {line}" for line in code.strip().split("\n"))

    template_escaped = _escape_template_literal(template)
    style_block = _make_style_block(style)

    return f"""/* Auto-generated from {component_id}.vue — do not edit */
/* global LlmingClient, Vue, Quasar */

(function () {{
  'use strict';
{style_block}
  class {_to_pascal(component_id)}Card extends LlmingClient {{
    static id = '{component_id}';
    static name = '{_to_title(component_id)}';
    static llmingTitle = '{_to_title(component_id)}';
    static llmingIcon = '{icon}';
    static llmingDescription = '{_escape_single_quote(description)}';
    static llmingWidgets = ['{panel_name}'];
    static cardComponent = '{panel_name}';
    static autoShow = true;

    onConnect() {{}}

    renderThumbnail(ctx, w, h) {{
      ctx.fillStyle = '#111827';
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = '#94a3b8';
      ctx.font = '14px system-ui';
      ctx.textAlign = 'center';
      ctx.fillText('{_to_title(component_id)}', w / 2, h / 2);
    }}

    setup(app, Quasar) {{
      const card = this;

      app.component('{panel_name}', {{
        template: `{template_escaped}`,

        setup() {{
          // Llming API — optional, use via $llming, inject('llming'), or useLlming()
          const $llming = {{
            name: '{component_id}',
            vault: card.vault,
            subscribe: (ch, fn) => card.subscribe(ch, fn),
            call: (power, args) => card.call(power, args),
            callOn: (llming, power, args) => card.call(power, args, llming),
            get connected() {{ return window.hortWS != null; }},
          }};
          const useLlming = () => $llming;
          Vue.provide('llming', $llming);

          // useStream — ACK-based reactive stream (cameras, screen capture, etc.)
          const useStream = window.useStream || function() {{ return {{ frame: Vue.ref(null), active: Vue.ref(false) }}; }};

          // vaultRef — push-based reactive binding to vault values
          function vaultRef(owner, path, defaultValue, options) {{
            const opts = options || {{}};
            const _ref = Vue.ref(defaultValue);
            const dot = path.indexOf('.');
            const vkey = dot >= 0 ? path.slice(0, dot) : path;
            const props = dot >= 0 ? path.slice(dot + 1).split('.') : [];
            function extract(d) {{
              let v = d;
              for (const p of props) {{ if (v == null) return defaultValue; v = v[p]; }}
              return v ?? defaultValue;
            }}
            const entry = {{ ref: _ref, extract, lastJson: JSON.stringify(defaultValue), onChange: opts.onChange || null }};
            // Register for server push notifications
            LlmingClient._watchVault(owner, vkey, entry);
            // Read initial value (the watch response also returns current data)
            (async () => {{
              try {{
                let data;
                if (owner === 'self' || owner === '{component_id}') {{
                  data = await $llming.vault.get(vkey);
                }} else if (window.hortWS) {{
                  const msg = await window.hortWS.request({{ type: 'card.vault.read', owner, key: vkey }});
                  data = msg && msg.data ? msg.data : {{}};
                }} else {{ return; }}
                const nv = extract(data);
                const nj = JSON.stringify(nv);
                if (nj !== entry.lastJson) {{
                  _ref.value = nv;
                  entry.lastJson = nj;
                }}
              }} catch (e) {{}}
            }})();
            Vue.onUnmounted(() => LlmingClient._unwatchVault(owner, vkey, entry));
            return _ref;
          }}

          {vue_line}
          {quasar_lines}

{user_code}

          {return_stmt}
        }}
      }});
    }}
  }}

  LlmingClient.register({_to_pascal(component_id)}Card);
}})();
"""


# ---- JS Generation: Options API (legacy) ----


def _generate_options(
    component_id: str,
    panel_name: str,
    template: str,
    script_body: str,
    style: str,
    icon: str,
    description: str,
) -> str:
    """Generate JS for <script> (Options API) components."""
    # Extract export default { ... } object literal
    export_match = re.search(r"export\s+default\s*\{", script_body)
    if export_match:
        start = export_match.end()
        depth = 1
        i = start
        while i < len(script_body) and depth > 0:
            if script_body[i] == "{":
                depth += 1
            elif script_body[i] == "}":
                depth -= 1
            i += 1
        component_options = script_body[start : i - 1].strip()
    else:
        component_options = ""

    template_escaped = _escape_template_literal(template)
    style_block = _make_style_block(style)

    return f"""/* Auto-generated from {component_id}.vue — do not edit */
/* global LlmingClient, Vue, Quasar */

(function () {{
  'use strict';
{style_block}
  class {_to_pascal(component_id)}Card extends LlmingClient {{
    static id = '{component_id}';
    static name = '{_to_title(component_id)}';
    static llmingTitle = '{_to_title(component_id)}';
    static llmingIcon = '{icon}';
    static llmingDescription = '{_escape_single_quote(description)}';
    static llmingWidgets = ['{panel_name}'];
    static cardComponent = '{panel_name}';
    static autoShow = true;

    onConnect() {{}}

    renderThumbnail(ctx, w, h) {{
      ctx.fillStyle = '#111827';
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = '#94a3b8';
      ctx.font = '14px system-ui';
      ctx.textAlign = 'center';
      ctx.fillText('{_to_title(component_id)}', w / 2, h / 2);
    }}

    setup(app, Quasar) {{
      const card = this;

      app.component('{panel_name}', {{
        template: `{template_escaped}`,

        beforeCreate() {{
          this.$llming = {{
            name: '{component_id}',
            vault: card.vault,
            subscribe: (ch, fn) => card.subscribe(ch, fn),
            call: (power, args) => card.call(power, args),
            callOn: (llming, power, args) => card.call(power, args, llming),
            get connected() {{ return window.hortWS != null; }},
          }};
        }},

        {component_options}
      }});
    }}
  }}

  LlmingClient.register({_to_pascal(component_id)}Card);
}})();
"""


# ---- JS Generation: App (<script setup>) ----


def _generate_app_setup(
    component_id: str,
    app_name: str,
    template: str,
    script_body: str,
    style: str,
) -> str:
    """Generate JS for app.vue — registers component on existing LlmingClient."""
    code, vue_imports, quasar_imports = _transform_imports(script_body)
    bindings = _collect_setup_bindings(code)

    vue_line = ""
    if vue_imports:
        vue_line = f"const {{ {', '.join(sorted(vue_imports))} }} = Vue;"

    quasar_lines = ""
    if "useQuasar" in quasar_imports:
        quasar_lines = (
            "const useQuasar = () => ({\n"
            "            notify: (opts) => Quasar.Notify.create(opts),\n"
            "            dialog: (opts) => Quasar.Dialog.create(opts),\n"
            "            loading: Quasar.Loading,\n"
            "            platform: Quasar.Platform,\n"
            "            screen: Quasar.Screen,\n"
            "            dark: Quasar.Dark,\n"
            "          });"
        )

    return_stmt = ""
    if bindings:
        return_stmt = f"return {{ {', '.join(bindings)} }};"

    user_code = "\n".join(f"          {line}" for line in code.strip().split("\n"))
    template_escaped = _escape_template_literal(template)
    style_block = _make_style_block(style)

    return f"""/* Auto-generated app from {component_id}/app.vue — do not edit */
/* global LlmingClient, Vue, Quasar */

(function () {{
  'use strict';
{style_block}
  // Find the existing card instance
  const card = LlmingClient.get('{component_id}');
  const ExtClass = LlmingClient.getRegistry().get('{component_id}');

  // Register app component on the Vue app
  const appEl = document.querySelector('#q-app');
  const vueApp = appEl && appEl.__vue_app__;
  if (vueApp) {{
    vueApp.component('{app_name}', {{
      template: `{template_escaped}`,

      setup() {{
        const $llming = card ? {{
          name: '{component_id}',
          vault: card.vault,
          subscribe: (ch, fn) => card.subscribe(ch, fn),
          call: (power, args) => card.call(power, args),
          callOn: (llming, power, args) => card.call(power, args, llming),
          get connected() {{ return window.hortWS != null; }},
        }} : {{ name: '{component_id}', vault: {{ async get() {{ return {{}}; }}, async set() {{}} }}, subscribe() {{}}, call() {{}}, callOn() {{}}, connected: false }};
        const useLlming = () => $llming;
        Vue.provide('llming', $llming);

        // useStream — ACK-based reactive stream
        const useStream = window.useStream || function() {{ return {{ frame: Vue.ref(null), active: Vue.ref(false) }}; }};

        // vaultRef — push-based reactive binding to vault values
        function vaultRef(owner, path, defaultValue, options) {{
          const opts = options || {{}};
          const _ref = Vue.ref(defaultValue);
          const dot = path.indexOf('.');
          const vkey = dot >= 0 ? path.slice(0, dot) : path;
          const props = dot >= 0 ? path.slice(dot + 1).split('.') : [];
          function extract(d) {{
            let v = d;
            for (const p of props) {{ if (v == null) return defaultValue; v = v[p]; }}
            return v ?? defaultValue;
          }}
          const entry = {{ ref: _ref, extract, lastJson: JSON.stringify(defaultValue), onChange: opts.onChange || null }};
          LlmingClient._watchVault(owner, vkey, entry);
          (async () => {{
            try {{
              let data;
              if (owner === 'self' || owner === '{component_id}') {{
                data = await $llming.vault.get(vkey);
              }} else if (window.hortWS) {{
                const msg = await window.hortWS.request({{ type: 'card.vault.read', owner, key: vkey }});
                data = msg && msg.data ? msg.data : {{}};
              }} else {{ return; }}
              const nv = extract(data);
              const nj = JSON.stringify(nv);
              if (nj !== entry.lastJson) {{ _ref.value = nv; entry.lastJson = nj; }}
            }} catch (e) {{}}
          }})();
          Vue.onUnmounted(() => LlmingClient._unwatchVault(owner, vkey, entry));
          return _ref;
        }}

        {vue_line}
        {quasar_lines}

{user_code}

        {return_stmt}
      }}
    }});
  }}

  // Update the LlmingClient to use the app as the panel widget
  if (ExtClass) {{
    ExtClass.llmingWidgets = ['{app_name}'];
  }}
}})();
"""


def _generate_app_options(
    component_id: str,
    app_name: str,
    template: str,
    script_body: str,
    style: str,
) -> str:
    """Generate JS for app.vue (Options API) — registers on existing LlmingClient."""
    export_match = re.search(r"export\\s+default\\s*\\{{", script_body)
    if export_match:
        start = export_match.end()
        depth = 1
        i = start
        while i < len(script_body) and depth > 0:
            if script_body[i] == "{{":
                depth += 1
            elif script_body[i] == "}}":
                depth -= 1
            i += 1
        component_options = script_body[start : i - 1].strip()
    else:
        component_options = ""

    template_escaped = _escape_template_literal(template)
    style_block = _make_style_block(style)

    return f"""/* Auto-generated app from {component_id}/app.vue — do not edit */
/* global LlmingClient, Vue, Quasar */

(function () {{
  'use strict';
{style_block}
  const card = LlmingClient.get('{component_id}');
  const ExtClass = LlmingClient.getRegistry().get('{component_id}');
  const appEl = document.querySelector('#q-app');
  const vueApp = appEl && appEl.__vue_app__;
  if (vueApp) {{
    vueApp.component('{app_name}', {{
      template: `{template_escaped}`,
      beforeCreate() {{
        this.$llming = card ? {{
          name: '{component_id}',
          vault: card.vault,
          subscribe: (ch, fn) => card.subscribe(ch, fn),
          call: (power, args) => card.call(power, args),
          callOn: (llming, power, args) => card.call(power, args, llming),
          get connected() {{ return window.hortWS != null; }},
        }} : {{}};
      }},
      {component_options}
    }});
  }}
  if (ExtClass) {{
    ExtClass.llmingWidgets = ['{app_name}'];
  }}
}})();
"""


# ---- Helpers ----


def _escape_template_literal(s: str) -> str:
    """Escape a string for use inside JS backtick template literals."""
    return s.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def _escape_single_quote(s: str) -> str:
    """Escape a string for use inside JS single quotes."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


def _make_style_block(style: str) -> str:
    """Generate JS that injects a <style> element, or empty string."""
    if not style:
        return ""
    escaped = _escape_template_literal(style)
    return (
        "\n  (function() {\n"
        "    const s = document.createElement('style');\n"
        f"    s.textContent = `{escaped}`;\n"
        "    document.head.appendChild(s);\n"
        "  })();\n"
    )


def _to_pascal(kebab: str) -> str:
    """Convert kebab-case to PascalCase: 'my-widget' -> 'MyWidget'."""
    return "".join(word.capitalize() for word in kebab.replace("-", "_").split("_"))


def _to_title(kebab: str) -> str:
    """Convert kebab-case to title: 'my-widget' -> 'My Widget'."""
    return " ".join(word.capitalize() for word in kebab.replace("-", "_").split("_"))
