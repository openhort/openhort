"""Vue SFC loader — compiles .vue files to LlmingClient JS at serve time.

Parses <template>, <script>, <style> from .vue files and generates
a cards.js-compatible module that the existing infrastructure loads.

The $llming API is injected into every component:
  this.$llming.vault.get(key)
  this.$llming.vault.set(key, data)
  this.$llming.subscribe(channel, handler)
  this.$llming.call(power, args)
  this.$llming.connected
  this.$llming.name
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cache compiled JS by file hash
_cache: dict[str, str] = {}


def compile_vue(vue_path: Path, llming_name: str) -> str:
    """Compile a .vue file to a LlmingClient JS module.

    Returns JavaScript that registers a LlmingClient with the
    Vue component from the .vue file.
    """
    content = vue_path.read_text()
    file_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

    cache_key = f"{vue_path}:{file_hash}"
    if cache_key in _cache:
        return _cache[cache_key]

    template, script, style, script_body = _parse_sfc(content)

    # Component ID (kebab-case)
    component_id = llming_name
    # Panel component name
    panel_name = f"{component_id}-panel"
    # CSS class name
    css_class = f"llming-{component_id}"

    js = _generate_js(component_id, panel_name, css_class, template, script_body, style)
    _cache[cache_key] = js
    return js


def _parse_sfc(content: str) -> tuple[str, str, str, str]:
    """Parse a Vue SFC into template, script, style, and script body.

    Returns (template_html, full_script_tag, style_css, script_body).
    script_body is the JS inside <script>...</script> without the tags.
    """
    template = _extract_block(content, "template") or "<div>No template</div>"
    script = _extract_block(content, "script") or ""
    style = _extract_block(content, "style") or ""

    return template, script, style, script


def _extract_block(content: str, tag: str) -> str:
    """Extract content between <tag>...</tag> or <tag ...>...</tag>."""
    pattern = rf"<{tag}[^>]*>(.*?)</{tag}>"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _generate_js(
    component_id: str,
    panel_name: str,
    css_class: str,
    template: str,
    script_body: str,
    style: str,
) -> str:
    """Generate a LlmingClient JS module from parsed SFC parts."""

    # Parse the export default { ... } from script body
    # Extract the object literal content
    export_match = re.search(r"export\s+default\s*\{", script_body)
    if export_match:
        # Find the matching closing brace
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

    # Escape template for JS string
    template_escaped = template.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    # Escape style for JS string
    style_escaped = style.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    # Scope CSS: replace selectors to be scoped to this component
    if style:
        style_scoped = style_escaped.replace(
            "scoped", ""
        )  # Remove scoped attribute remnants
    else:
        style_scoped = ""

    return f"""/* Auto-generated from {component_id}.vue — do not edit */
/* global LlmingClient, Vue, Quasar */

(function () {{
  'use strict';

  // Inject scoped styles
  {"" if not style_scoped else f'''
  (function() {{
    const style = document.createElement('style');
    style.textContent = `{style_scoped}`;
    document.head.appendChild(style);
  }})();
  '''}

  class {_to_class_name(component_id)}Card extends LlmingClient {{
    static id = '{component_id}';
    static name = '{_to_title(component_id)}';
    static llmingTitle = '{_to_title(component_id)}';
    static llmingIcon = 'ph ph-puzzle-piece';
    static llmingDescription = '';

    onConnect() {{
      // Vault + pulse handled by the Vue component via $llming
    }}

    renderThumbnail(ctx, w, h) {{
      // Default thumbnail — Vue component renders in panel
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

        // Inject $llming API before component creation
        beforeCreate() {{
          this.$llming = {{
            name: '{component_id}',
            vault: card.vault,
            subscribe: (ch, fn) => card.subscribe(ch, fn),
            call: (power, args) => card.call(power, args),
            callOn: (llming, power, args) => card.call(power, args, llming),
            get connected() {{ return window.hortWS != null; }},
            close: () => {{}},
          }};
        }},

        {component_options}
      }});
    }}
  }}

  LlmingClient.register({_to_class_name(component_id)}Card);
}})();
"""


def _to_class_name(kebab: str) -> str:
    """Convert kebab-case to PascalCase: 'my-widget' → 'MyWidget'."""
    return "".join(word.capitalize() for word in kebab.replace("-", "_").split("_"))


def _to_title(kebab: str) -> str:
    """Convert kebab-case to title: 'my-widget' → 'My Widget'."""
    return " ".join(word.capitalize() for word in kebab.replace("-", "_").split("_"))
