"""macOS permission checks for Screen Recording and Accessibility."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PermissionStatus:
    """Which macOS permissions are granted."""

    screen_recording: bool
    accessibility: bool

    @property
    def all_granted(self) -> bool:
        return self.screen_recording and self.accessibility

    @property
    def summary(self) -> str:
        parts: list[str] = []
        if not self.screen_recording:
            parts.append("Screen Recording")
        if not self.accessibility:
            parts.append("Accessibility")
        if not parts:
            return "All permissions granted"
        return "Missing: " + ", ".join(parts)


def check_permissions() -> PermissionStatus:
    """Check which macOS permissions are currently granted."""
    try:
        import Quartz

        screen_recording = bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        screen_recording = False

    try:
        import ApplicationServices

        accessibility = bool(ApplicationServices.AXIsProcessTrusted())
    except Exception:
        accessibility = False

    return PermissionStatus(
        screen_recording=screen_recording,
        accessibility=accessibility,
    )


def request_screen_recording() -> None:
    """Trigger the macOS Screen Recording permission dialog."""
    try:
        import Quartz

        Quartz.CGRequestScreenCaptureAccess()
    except Exception:
        logger.exception("Failed to request Screen Recording permission")


def request_accessibility() -> None:
    """Open System Settings -> Accessibility with our app highlighted."""
    try:
        import ApplicationServices
        import CoreFoundation

        options = {CoreFoundation.kAXTrustedCheckOptionPrompt: True}
        ApplicationServices.AXIsProcessTrustedWithOptions(options)
    except Exception:
        logger.exception("Failed to request Accessibility permission")


def request_all_permissions() -> None:
    """Request all needed permissions (shows dialogs/System Settings)."""
    status = check_permissions()
    if not status.screen_recording:
        request_screen_recording()
    if not status.accessibility:
        request_accessibility()
