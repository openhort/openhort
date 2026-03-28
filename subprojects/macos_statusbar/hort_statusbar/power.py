"""Sleep prevention via IOPMAssertion (macOS IOKit)."""

from __future__ import annotations

import ctypes
import ctypes.util
import logging

logger = logging.getLogger(__name__)

_iokit_path = ctypes.util.find_library("IOKit")
_cf_path = ctypes.util.find_library("CoreFoundation")

if _iokit_path and _cf_path:
    IOKit = ctypes.cdll.LoadLibrary(_iokit_path)
    CoreFoundation = ctypes.cdll.LoadLibrary(_cf_path)
else:
    IOKit = None  # type: ignore[assignment]
    CoreFoundation = None  # type: ignore[assignment]

# IOPMAssertion constants
kIOPMAssertionLevelOn = 255
kIOPMAssertPreventUserIdleSystemSleep = "PreventUserIdleSystemSleep"
kIOPMAssertPreventUserIdleDisplaySleep = "PreventUserIdleDisplaySleep"


def _cfstr(s: str) -> ctypes.c_void_p:
    """Create a CFStringRef from a Python string."""
    CoreFoundation.CFStringCreateWithCString.restype = ctypes.c_void_p
    CoreFoundation.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    return CoreFoundation.CFStringCreateWithCString(
        None, s.encode("utf-8"), 0x08000100  # kCFStringEncodingUTF8
    )


class PowerManager:
    """Prevents macOS from sleeping while openhort is serving.

    Uses IOPMAssertionCreateWithName — the same API that Amphetamine,
    Caffeine, and similar apps use.

    Two levels:
    - System sleep prevention (default): Mac stays awake, display can dim/off
    - Display sleep prevention (optional): display stays on too
    """

    def __init__(self) -> None:
        self._system_assertion = ctypes.c_uint32(0)
        self._display_assertion = ctypes.c_uint32(0)
        self._active = False
        self._display_active = False

    @property
    def is_preventing_sleep(self) -> bool:
        return self._active

    @property
    def is_preventing_display_sleep(self) -> bool:
        return self._display_active

    def prevent_sleep(self, prevent_display_sleep: bool = False) -> bool:
        """Create IOPMAssertion to prevent system sleep.

        Args:
            prevent_display_sleep: Also prevent display from turning off.

        Returns:
            True if assertion was created successfully.
        """
        if not IOKit:
            logger.warning("IOKit not available — cannot prevent sleep")
            return False

        if self._active:
            # If already active, just handle display toggle
            if prevent_display_sleep and not self._display_active:
                return self._create_display_assertion()
            return True

        reason = _cfstr("openhort remote viewer is active")
        assertion_type = _cfstr(kIOPMAssertPreventUserIdleSystemSleep)

        IOKit.IOPMAssertionCreateWithName.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        IOKit.IOPMAssertionCreateWithName.restype = ctypes.c_int32

        result = IOKit.IOPMAssertionCreateWithName(
            assertion_type,
            kIOPMAssertionLevelOn,
            reason,
            ctypes.byref(self._system_assertion),
        )

        if result != 0:  # kIOReturnSuccess
            logger.error("IOPMAssertionCreateWithName failed: %d", result)
            return False

        self._active = True
        logger.info("Sleep prevention enabled (assertion ID: %d)", self._system_assertion.value)

        if prevent_display_sleep:
            self._create_display_assertion()

        return True

    def _create_display_assertion(self) -> bool:
        """Create a display sleep prevention assertion."""
        reason = _cfstr("openhort remote viewer — display kept on")
        assertion_type = _cfstr(kIOPMAssertPreventUserIdleDisplaySleep)

        result = IOKit.IOPMAssertionCreateWithName(
            assertion_type,
            kIOPMAssertionLevelOn,
            reason,
            ctypes.byref(self._display_assertion),
        )

        if result != 0:
            logger.error("Display assertion failed: %d", result)
            return False

        self._display_active = True
        logger.info("Display sleep prevention enabled")
        return True

    def allow_sleep(self) -> None:
        """Release all assertions, allow sleep again."""
        if not IOKit:
            return

        IOKit.IOPMAssertionRelease.argtypes = [ctypes.c_uint32]
        IOKit.IOPMAssertionRelease.restype = ctypes.c_int32

        if self._system_assertion.value:
            IOKit.IOPMAssertionRelease(self._system_assertion.value)
            self._system_assertion = ctypes.c_uint32(0)
            logger.info("System sleep assertion released")

        if self._display_assertion.value:
            IOKit.IOPMAssertionRelease(self._display_assertion.value)
            self._display_assertion = ctypes.c_uint32(0)
            logger.info("Display sleep assertion released")

        self._active = False
        self._display_active = False
