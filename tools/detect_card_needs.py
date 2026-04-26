"""Suggest a manifest `needs:` block for each card by scanning its source.

Walks every llming with a ``card.vue`` / ``app.vue`` / ``cards.js``, finds
calls to ``vaultRef``, ``useStream``, ``$llming.subscribe``, ``$llming.callOn``,
``$llming.vaults('x').*``, etc., and emits the union as a JSON snippet you
can drop into ``manifest.json``.

Usage::

    poetry run python tools/detect_card_needs.py            # all llmings
    poetry run python tools/detect_card_needs.py cameras    # one llming
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LLMINGS = ROOT / "llmings"

# (label, regex with groups). Groups are interpreted per-rule below.
RULES = [
    # vaultRef('owner', 'state.path', ...) → needs.vault: owner:state
    ("vault_ref", re.compile(r"vaultRef\s*\(\s*['\"]([\w\-:]+)['\"]\s*,\s*['\"]([\w\.\-]+)['\"]")),
    # $llming.vault.set / .get / .delete on self
    ("vault_self", re.compile(r"\$llming\.vault\.(get|set|delete|watch)\s*\(\s*['\"]([\w\.\-]+)['\"]")),
    # $llming.vaults('x').get('key')
    ("vault_other", re.compile(r"\$llming\.vaults\(\s*['\"]([\w\-]+)['\"]\s*\)\.\w+\s*\(\s*['\"]([\w\.\-]+)['\"]")),
    # useStream('owner:channel', ...)
    ("stream", re.compile(r"useStream\s*\(\s*['\"]([\w\-]+):([^'\"]+)['\"]")),
    # $llming.subscribe('channel'), $llming.subscribe('owner:channel')
    ("pulse_sub_self", re.compile(r"\$llming\.subscribe\s*\(\s*['\"]([\w\-:]+)['\"]")),
    # $llming.emit('channel', ...) / .publish
    ("pulse_pub_self", re.compile(r"\$llming\.(?:emit|publish)\s*\(\s*['\"]([\w\-:]+)['\"]")),
    # $llming.callOn('llming', 'power', ...)
    ("power_other", re.compile(r"\$llming\.callOn\s*\(\s*['\"]([\w\-]+)['\"]\s*,\s*['\"]([\w\-]+)['\"]")),
]


def scan_file(path: Path, owner: str, needs: dict[str, set[str]]) -> None:
    text = path.read_text(errors="ignore")
    for label, regex in RULES:
        for m in regex.finditer(text):
            if label == "vault_ref":
                ns, key_path = m.group(1), m.group(2)
                key = key_path.split(".", 1)[0]
                if ns == "self" or ns == owner:
                    continue
                needs.setdefault("vault", set()).add(f"{ns}:{key}")
            elif label == "vault_self":
                _, key_path = m.group(1), m.group(2)
                # self access is implicit — skip
                continue
            elif label == "vault_other":
                ns, key = m.group(1), m.group(2)
                if ns == owner:
                    continue
                needs.setdefault("vault", set()).add(f"{ns}:{key.split('.', 1)[0]}")
            elif label == "stream":
                ns, ch = m.group(1), m.group(2)
                if ns == owner:
                    needs.setdefault("stream", set()).add(f"{ns}:*")
                else:
                    needs.setdefault("stream", set()).add(f"{ns}:{ch}")
            elif label == "pulse_sub_self":
                ch = m.group(1)
                ns = ch.split(":", 1)[0] if ":" in ch else owner
                if ns == owner:
                    continue
                needs.setdefault("pulse", set()).add(f"subscribe:{ch}")
            elif label == "pulse_pub_self":
                ch = m.group(1)
                ns = ch.split(":", 1)[0] if ":" in ch else owner
                if ns == owner:
                    continue
                needs.setdefault("pulse", set()).add(f"publish:{ch}")
            elif label == "power_other":
                target, power = m.group(1), m.group(2)
                if target == owner:
                    continue
                needs.setdefault("powers", set()).add(f"{target}:{power}")


def detect_for_llming(name_dir: Path, manifest_name: str) -> dict[str, list[str]]:
    needs: dict[str, set[str]] = {}
    for pat in ("*.vue", "*.js"):
        for path in name_dir.rglob(pat):
            if "/__pycache__/" in str(path) or path.suffix == ".test.js":
                continue
            scan_file(path, manifest_name, needs)
    return {k: sorted(v) for k, v in sorted(needs.items())}


def main(argv: list[str]) -> int:
    target = argv[1] if len(argv) > 1 else None
    out: dict[str, dict[str, list[str]]] = {}
    for provider_dir in sorted(LLMINGS.iterdir()) if LLMINGS.is_dir() else []:
        if not provider_dir.is_dir() or provider_dir.name.startswith("_"):
            continue
        for name_dir in sorted(provider_dir.iterdir()):
            if not name_dir.is_dir() or name_dir.name.startswith("_"):
                continue
            mp = name_dir / "manifest.json"
            if not mp.exists():
                continue
            try:
                manifest = json.loads(mp.read_text())
            except json.JSONDecodeError:
                continue
            name = manifest.get("name", name_dir.name.replace("_", "-"))
            if target and name != target:
                continue
            if not manifest.get("ui_widgets"):
                continue
            needs = detect_for_llming(name_dir, name)
            out[name] = needs

    for name, needs in out.items():
        print(f"\n=== {name} ===")
        if not needs:
            print("  (no cross-llming access detected — needs: {})")
        else:
            print(json.dumps({"needs": needs}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
