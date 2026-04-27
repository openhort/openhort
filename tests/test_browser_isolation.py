from __future__ import annotations

from hort.browser_isolation import should_isolate_widget
from hort.ext.manifest import ExtensionManifest


def _manifest(
    name: str = "weather",
    *,
    needs: dict[str, list[str]] | None = None,
    browser_isolation: str = "",
) -> ExtensionManifest:
    return ExtensionManifest(
        name=name,
        ui_widgets=[f"{name}-card"],
        ui_script="static/cards.js",
        needs=needs or {},
        browser_isolation=browser_isolation,
    )


def test_per_widget_policy_isolates_by_default() -> None:
    policy = {"mode": "per_widget", "isolate": [], "share": []}

    assert should_isolate_widget(_manifest(), policy)


def test_shared_host_policy_shares_by_default() -> None:
    policy = {"mode": "shared_host", "isolate": [], "share": []}

    assert not should_isolate_widget(_manifest(), policy)


def test_isolate_override_wins_in_shared_host_policy() -> None:
    policy = {"mode": "shared_host", "isolate": ["weather"], "share": []}

    assert should_isolate_widget(_manifest(), policy)


def test_auto_policy_isolates_cross_llming_needs() -> None:
    policy = {"mode": "auto", "isolate": [], "share": []}
    manifest = _manifest(needs={"vault": ["system-monitor:state.cpu_percent"]})

    assert should_isolate_widget(manifest, policy)


def test_auto_policy_shares_own_needs() -> None:
    policy = {"mode": "auto", "isolate": [], "share": []}
    manifest = _manifest(name="cameras", needs={"stream": ["cameras:*"]})

    assert not should_isolate_widget(manifest, policy)


def test_auto_policy_respects_manifest_hint() -> None:
    policy = {"mode": "auto", "isolate": [], "share": []}

    assert should_isolate_widget(_manifest(browser_isolation="isolated"), policy)
    assert not should_isolate_widget(_manifest(browser_isolation="shared"), policy)
