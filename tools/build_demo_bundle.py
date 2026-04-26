"""Build a single-file offline demo bundle.

Produces ``dist/openhort-demo.html`` — a self-contained HTML file that runs
the openhort UI in demo mode with no backend. Vendor JS, CSS, fonts, every
llming's compiled cards/apps, every demo.js, and every per-llming static
asset are inlined; the only network calls the page will make in offline
mode are skipped because ``window.__LLMING_OFFLINE__`` is set.

Auto-discovers llmings — drop a new one under ``llmings/<provider>/<name>/``
with a ``manifest.json`` and a ``card.vue`` (and optionally ``demo.js``,
``app.vue``, ``static/``) and rebuild. No edits to this script needed.

Usage::

    poetry run python tools/build_demo_bundle.py
    open dist/openhort-demo.html
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("build_demo_bundle")

ROOT = Path(__file__).resolve().parent.parent
LLMINGS_DIR = ROOT / "llmings"
SAMPLE_DATA_DIR = ROOT / "sample-data"
STATIC_DIR = ROOT / "hort" / "static"
INDEX_HTML = STATIC_DIR / "index.html"
OUT_DIR = ROOT / "dist"
OUT_FILE = OUT_DIR / "openhort-demo.html"

sys.path.insert(0, str(ROOT))
from hort.ext.vue_loader import compile_vue  # noqa: E402

# Mark these vendor scripts as inlined; anything else still references the
# server. Plotly is huge (~3 MB) and not used by the default desktops, so
# we skip it by default — append "plotly" here if you need it.
INLINE_VENDORS_SKIP: set[str] = {"plotly.min.js"}


# ---- Utilities ----------------------------------------------------------


def _data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "application/octet-stream"
    text_like = mime.startswith("text/") or mime in ("application/json", "image/svg+xml")
    if text_like:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _walk_assets(dir_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not dir_path.is_dir():
        return out
    for f in sorted(dir_path.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(dir_path)).replace("\\", "/")
        out[rel] = _data_url(f)
    return out


def _demo_module_data_url(src: str) -> str:
    """Encode a demo.js source as a ``data:text/javascript;base64,...`` URL.

    Loaded via ``await import(url)`` at runtime — gives us a real ES module
    with full language support (top-level await, async exports, anything
    valid). No regex munging, no constraints on the demo author's syntax.
    """
    encoded = base64.b64encode(src.encode("utf-8")).decode("ascii")
    return f"data:text/javascript;base64,{encoded}"


# ---- Llming discovery ---------------------------------------------------


def discover_llmings() -> list[dict[str, Any]]:
    """Walk ``llmings/<provider>/<name>/`` and gather everything we need.

    Each entry: name, provider, manifest_dict, card_src, app_src, demo_src,
    static_assets (path → data URL).
    """
    llmings: list[dict[str, Any]] = []
    if not LLMINGS_DIR.is_dir():
        return llmings
    for provider_dir in sorted(LLMINGS_DIR.iterdir()):
        if not provider_dir.is_dir() or provider_dir.name.startswith("_"):
            continue
        # Skip top-level non-provider files (e.g. __init__.py)
        for name_dir in sorted(provider_dir.iterdir()):
            if not name_dir.is_dir() or name_dir.name.startswith("_"):
                continue
            manifest_path = name_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
            except json.JSONDecodeError as exc:
                logger.warning("Bad manifest %s: %s", manifest_path, exc)
                continue
            name = manifest.get("name", name_dir.name.replace("_", "-"))

            # Find card.vue / app.vue (or app/index.vue) by directory name
            card_vue = name_dir / f"{name_dir.name}.vue"
            if not card_vue.exists():
                # Some llmings use card.vue directly
                card_vue = name_dir / "card.vue"
            app_vue = name_dir / "app.vue"
            if not app_vue.exists():
                app_index = name_dir / "app" / "index.vue"
                if app_index.exists():
                    app_vue = app_index

            card_src = ""
            if card_vue.exists():
                try:
                    card_src = compile_vue(card_vue, name_dir.name, mode="card")
                except Exception as exc:
                    logger.warning("compile %s failed: %s", card_vue, exc)

            app_src = ""
            if app_vue.exists():
                try:
                    app_src = compile_vue(app_vue, name_dir.name, mode="app")
                except Exception as exc:
                    logger.warning("compile %s failed: %s", app_vue, exc)

            demo_path = name_dir / "demo.js"
            demo_url = ""
            if demo_path.exists():
                demo_url = _demo_module_data_url(demo_path.read_text())

            static_assets = _walk_assets(name_dir / "static")

            llmings.append({
                "name": name,
                "provider": provider_dir.name,
                "dir_name": name_dir.name,
                "manifest": manifest,
                "card_src": card_src,
                "app_src": app_src,
                "demo_url": demo_url,
                "static_assets": static_assets,
            })
    return llmings


# ---- Vendor / CSS inlining ---------------------------------------------


_SCRIPT_TAG = re.compile(r'<script\s+src="([^"]+)"[^>]*></script>', re.IGNORECASE)
_STYLE_TAG = re.compile(r'<link\s+[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*/?>', re.IGNORECASE)


def _resolve_static(src: str) -> Path | None:
    # Strip leading "./", "/", and any cache-busting query
    src = src.split("?", 1)[0].split("#", 1)[0]
    if src.startswith("/"):
        src = src[1:]
    if src.startswith("static/"):
        return STATIC_DIR / src[len("static/"):]
    if src.startswith("ext/"):
        return None  # handled by plugin loader, not inlined here
    if src.startswith("http://") or src.startswith("https://"):
        return None
    return STATIC_DIR / src


def inline_vendor_assets(html: str) -> str:
    """Replace <script src="static/..."> and <link rel="stylesheet" href="static/...">
    with inlined <script>/<style> blocks. External URLs and /ext/ scripts
    are left alone (the plugin loader handles ext/, externals are kept as is)."""

    def script_repl(m: re.Match[str]) -> str:
        src = m.group(1)
        if any(skip in src for skip in INLINE_VENDORS_SKIP):
            return ""  # drop entirely
        path = _resolve_static(src)
        if not path or not path.exists():
            return m.group(0)
        body = path.read_text(encoding="utf-8")
        # Wrap in CDATA-style guard not needed for HTML; close any </script>
        # within content so it doesn't break parsing.
        body = body.replace("</script>", "<\\/script>")
        return f"<script>/* inlined: {src} */\n{body}\n</script>"

    def style_repl(m: re.Match[str]) -> str:
        src = m.group(1)
        path = _resolve_static(src)
        if not path or not path.exists():
            return m.group(0)
        # Inline url(...) references inside the CSS as data URLs (fonts,
        # background images). This keeps the bundle truly self-contained.
        css = path.read_text(encoding="utf-8")
        css = _inline_css_urls(css, path.parent)
        return f"<style>/* inlined: {src} */\n{css}\n</style>"

    html = _SCRIPT_TAG.sub(script_repl, html)
    html = _STYLE_TAG.sub(style_repl, html)
    return html


_CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")


def _inline_css_urls(css: str, base: Path) -> str:
    def repl(m: re.Match[str]) -> str:
        ref = m.group(1).strip()
        if ref.startswith("data:") or ref.startswith("http:") or ref.startswith("https:"):
            return m.group(0)
        ref_clean = ref.split("?", 1)[0].split("#", 1)[0]
        candidate = (base / ref_clean).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return m.group(0)
        if not candidate.exists():
            return m.group(0)
        return f"url('{_data_url(candidate)}')"
    return _CSS_URL.sub(repl, css)


# ---- Bundle assembly ---------------------------------------------------


def build_bundle(llmings: list[dict[str, Any]]) -> str:
    """Build the JS bundle blob that gets injected before </head>."""
    manifests: list[dict[str, Any]] = []
    assets: dict[str, dict[str, str]] = {}
    card_scripts: dict[str, str] = {}
    app_scripts: dict[str, str] = {}
    demo_modules: dict[str, str] = {}  # name → data:text/javascript URL

    for p in llmings:
        m = dict(p["manifest"])
        m.setdefault("name", p["name"])
        m.setdefault("provider", p["provider"])
        m["loaded"] = True
        m["compatible"] = True
        m["ui_widgets"] = m.get("ui_widgets", [])
        m["ui_script_url"] = ""        # offline — script is in cardScripts
        m["app_script_url"] = ""
        m["demo_url"] = "offline" if p["demo_url"] else ""
        manifests.append(m)
        if p["static_assets"]:
            assets[p["name"]] = p["static_assets"]
        if p["card_src"]:
            card_scripts[p["name"]] = p["card_src"]
        if p["app_src"]:
            app_scripts[p["name"]] = p["app_src"]
        if p["demo_url"]:
            demo_modules[p["name"]] = p["demo_url"]

    shared = _walk_assets(SAMPLE_DATA_DIR)

    # Everything is JSON — including demoModules, which are data URLs that
    # the runtime imports via dynamic ``await import(url)`` to get a real
    # ES module. No code-string interpolation, no parser hacks.
    bundle_payload = {
        "manifests": manifests,
        "assets": assets,
        "shared": shared,
        "cardScripts": card_scripts,
        "appScripts": app_scripts,
        "demoModules": demo_modules,
    }
    bundle_json = json.dumps(bundle_payload).replace("</", "<\\/")

    return (
        "<script>/* openhort offline bundle */\n"
        "window.__LLMING_OFFLINE__ = true;\n"
        f"window.__LLMING_BUNDLE__ = {bundle_json};\n"
        "</script>\n"
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    if not INDEX_HTML.exists():
        logger.error("index.html not found at %s", INDEX_HTML)
        return 1

    OUT_DIR.mkdir(exist_ok=True)

    logger.info("Discovering llmings...")
    llmings = discover_llmings()
    logger.info("Found %d llmings; %d cards, %d apps, %d demos, %d shared assets",
                len(llmings),
                sum(1 for p in llmings if p["card_src"]),
                sum(1 for p in llmings if p["app_src"]),
                sum(1 for p in llmings if p["demo_url"]),
                len(_walk_assets(SAMPLE_DATA_DIR)))

    html = INDEX_HTML.read_text(encoding="utf-8")

    logger.info("Inlining vendor JS and CSS...")
    html = inline_vendor_assets(html)

    bundle_blob = build_bundle(llmings)
    if "</head>" in html:
        html = html.replace("</head>", bundle_blob + "</head>", 1)
    else:
        html = bundle_blob + html

    OUT_FILE.write_text(html, encoding="utf-8")
    size_kb = OUT_FILE.stat().st_size / 1024
    logger.info("Wrote %s (%.1f KB)", OUT_FILE, size_kb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
