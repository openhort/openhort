"""Pydantic models for screen watcher configuration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RegionConfig(BaseModel):
    """Defines a sub-region of a window to capture.

    Coordinates are relative fractions (0.0–1.0).
    """

    model_config = {"extra": "allow"}

    preset: Literal[
        "full",
        "left", "right", "top", "bottom",
        "top_left", "top_right", "bottom_left", "bottom_right",
        "center",
    ] | None = "full"
    # Custom region overrides preset (fractions 0.0-1.0)
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0


# Preset region definitions (x, y, w, h as fractions)
REGION_PRESETS: dict[str, tuple[float, float, float, float]] = {
    "full":         (0.0, 0.0, 1.0, 1.0),
    "left":         (0.0, 0.0, 0.5, 1.0),
    "right":        (0.5, 0.0, 0.5, 1.0),
    "top":          (0.0, 0.0, 1.0, 0.5),
    "bottom":       (0.0, 0.5, 1.0, 0.5),
    "top_left":     (0.0, 0.0, 0.5, 0.5),
    "top_right":    (0.5, 0.0, 0.5, 0.5),
    "bottom_left":  (0.0, 0.5, 0.5, 0.5),
    "bottom_right": (0.5, 0.5, 0.5, 0.5),
    "center":       (0.25, 0.25, 0.5, 0.5),
}


def resolve_region(region: RegionConfig) -> tuple[float, float, float, float]:
    """Resolve a RegionConfig to (x, y, w, h) fractions."""
    if region.preset and region.preset in REGION_PRESETS:
        return REGION_PRESETS[region.preset]
    return (region.x, region.y, region.w, region.h)


class WatchRule(BaseModel):
    """A single watch rule — which windows to watch and how."""

    model_config = {"extra": "allow"}

    name: str                                   # human-readable rule name
    app_filter: str | None = None               # case-insensitive app name substring
    window_filter: str | None = None            # case-insensitive window title substring
    region: RegionConfig = Field(default_factory=RegionConfig)
    poll_interval: float = 1.0                  # seconds between captures
    max_width: int = 800                        # max capture width (pixels)
    quality: int = 70                           # JPEG quality
    idle_threshold: float = 10.0                # seconds of no change → idle signal
    change_threshold: float = 0.01              # min hash-change ratio to count as "changed"
    enabled: bool = True


class ScreenWatcherConfig(BaseModel):
    """Top-level screen watcher configuration."""

    model_config = {"extra": "allow"}

    rules: list[WatchRule] = Field(default_factory=list)
