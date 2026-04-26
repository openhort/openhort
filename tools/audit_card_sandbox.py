"""Audit cards for patterns that won't survive the iframe sandbox.

Usage::

    poetry run python tools/audit_card_sandbox.py
    # exits non-zero if any card uses a forbidden pattern

The patterns are documented in
``docs/manual/internals/security/card-sandbox.md`` (section "Forbidden
patterns in cards"). Add a card path to ``ALLOWLIST`` only if you have
reviewed the violation and confirmed it is benign or unavoidable.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = [ROOT / "llmings"]
SCAN_GLOB = ("*.vue", "*.js")

# (pattern, sanctioned alternative) — printed in the report
FORBIDDEN: list[tuple[str, str, str]] = [
    (
        "host-globals",
        r"\bwindow\.(LlmingClient|hortWS|__hort|__hortPrefs)\b",
        "use $llming.* / vaultRef / useStream / usePulse instead",
    ),
    (
        "raw-cookies",
        r"\bdocument\.cookie\b",
        "store per-llming state in $llming.vault.set",
    ),
    (
        "raw-localstorage",
        r"\b(localStorage|sessionStorage)\.\w+",
        "use $llming.local.set for device-local data, $llming.vault.set for cross-device data",
    ),
    (
        "raw-indexeddb",
        r"\b(indexedDB|openDatabase)\b",
        "use $llming.local.set for device-local data, $llming.vault.set for cross-device data",
    ),
    (
        "dynamic-script",
        r"createElement\(\s*['\"]script['\"]\s*\)",
        "bundle the dependency at build time",
    ),
    (
        "fixed-overlay",
        r"position\s*:\s*['\"]?fixed['\"]?",
        "use LlmingClient.openSubapp / openFloat for popups",
    ),
    (
        "registry-walking",
        r"getRegistry\(\)|_vaultWatchers|_activeStreams",
        "use vaults['x'].get() / subscribe('y') / call('z')",
    ),
]

# Files known to legitimately use a flagged pattern. Each entry is
# (relative path, list of pattern names) — don't add to this without
# explaining why in the manifest review.
ALLOWLIST: dict[str, set[str]] = {
    # llming-cam and hue-bridge cards.js predate the sandbox and use
    # custom WS message types (cam.list, cam.policy, etc.) directly via
    # window.hortWS. Tracked as separate migration to power-style calls
    # via $llming.callOn in their respective tickets — until that lands,
    # these llmings can't be loaded sandboxed and are excluded from the
    # widget grid pending the rewrite.
    "llmings/core/llming_cam/static/cards.js": {"host-globals"},
    "llmings/core/hue_bridge/static/cards.js": {"host-globals"},
    # llming-wire's chat store is a structured IndexedDB schema with
    # multiple object stores and indices — beyond the simple kv shape
    # of $llming.local. Tracked as a future "structured local store"
    # feature on the bridge; until then this card stays first-party
    # via maintainer review.
    "llmings/core/llming_wire/static/cards.js": {"raw-indexeddb"},
}


def scan() -> int:
    findings: list[tuple[str, str, int, str]] = []
    for base in SCAN_DIRS:
        if not base.is_dir():
            continue
        for pat in SCAN_GLOB:
            for path in base.rglob(pat):
                rel = str(path.relative_to(ROOT))
                # Skip the build script's own demo modules folder, vendored libs, etc.
                if "/static/vendor/" in rel or "/__pycache__/" in rel:
                    continue
                text = path.read_text(errors="ignore")
                allowed = ALLOWLIST.get(rel, set())
                for name, regex, _alt in FORBIDDEN:
                    if name in allowed:
                        continue
                    for m in re.finditer(regex, text):
                        line = text[: m.start()].count("\n") + 1
                        snippet = text.splitlines()[line - 1].strip()[:100]
                        # Skip comment-only matches (lines that start with
                        # comment markers, after stripping whitespace).
                        if snippet.startswith(("//", "/*", "*", "#")):
                            continue
                        findings.append((rel, name, line, snippet))

    if not findings:
        print("Card sandbox audit: clean. All scanned cards respect the contract.")
        return 0

    print(f"Card sandbox audit: {len(findings)} violation(s)\n")
    for path, name, line, snippet in findings:
        alt = next((a for n, _, a in FORBIDDEN if n == name), "")
        print(f"  {path}:{line}  [{name}]")
        print(f"    {snippet}")
        print(f"    → {alt}")
        print()
    print("Fix violations or, with explicit reasoning, add the file to ALLOWLIST.")
    print("See docs/manual/internals/security/card-sandbox.md for the contract.")
    return 1


if __name__ == "__main__":
    sys.exit(scan())
