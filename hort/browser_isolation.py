"""Browser-side llming UI isolation policy."""

from __future__ import annotations

from fnmatch import fnmatch
from typing import Any, Literal, TypedDict, cast

from hort.ext.manifest import ExtensionManifest

IsolationMode = Literal["per_widget", "shared_host", "auto"]


class BrowserIsolationPolicy(TypedDict):
    """Serialized browser isolation policy sent to the SPA."""

    mode: IsolationMode
    isolate: list[str]
    share: list[str]


_VALID_MODES: set[str] = {"per_widget", "shared_host", "auto"}


def load_browser_isolation_policy() -> BrowserIsolationPolicy:
    """Load the browser isolation policy from ``hort-config.yaml``.

    Config namespace::

        ui.browser_isolation:
          mode: per_widget | shared_host | auto
          isolate: ["llming-wire", "finance-*"]
          share: ["weather"]

    Defaults to the current safest behavior: every widget in its own
    sandboxed iframe.
    """
    from hort.config import get_store

    raw = get_store().get("ui.browser_isolation")
    mode_raw = raw.get("mode", "per_widget")
    mode: IsolationMode = "per_widget"
    if isinstance(mode_raw, str) and mode_raw in _VALID_MODES:
        mode = cast(IsolationMode, mode_raw)

    return {
        "mode": mode,
        "isolate": _string_list(raw.get("isolate", [])),
        "share": _string_list(raw.get("share", [])),
    }


def should_isolate_widget(
    manifest: ExtensionManifest | None,
    policy: BrowserIsolationPolicy,
) -> bool:
    """Return whether a widget should render in its own iframe."""
    if manifest is None:
        return True

    name = manifest.name
    if _matches_any(name, policy["isolate"]):
        return True
    if _matches_any(name, policy["share"]):
        return False

    mode = policy["mode"]
    if mode == "per_widget":
        return True
    if mode == "shared_host":
        return False

    # Auto mode: isolate explicitly marked sensitive widgets and widgets
    # whose manifest requests cross-llming browser capabilities. Own vaults
    # and own streams are not treated as cross-boundary.
    if manifest.browser_isolation == "isolated":
        return True
    if manifest.browser_isolation == "shared":
        return False
    return _has_cross_llming_needs(manifest)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, str) and v.strip()]


def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch(name, pattern) for pattern in patterns)


def _has_cross_llming_needs(manifest: ExtensionManifest) -> bool:
    own = manifest.name
    for kind, specs in manifest.needs.items():
        if kind == "stream":
            if any(_is_cross_spec(spec, own) for spec in specs):
                return True
            continue
        if kind in {"vault", "vault_write"}:
            if any(_is_cross_spec(spec, own) for spec in specs):
                return True
            continue
        # Publishing/subscribing pulses and calling powers can affect other
        # llmings; treat them as sensitive unless the author opts into share.
        if specs:
            return True
    return False


def _is_cross_spec(spec: str, own: str) -> bool:
    owner, _, _key = spec.partition(":")
    if not owner:
        return False
    return owner not in {"self", own, own.replace("-", "_")}
