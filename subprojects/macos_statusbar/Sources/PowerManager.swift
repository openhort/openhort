import IOKit
import IOKit.pwr_mgt

/// Prevents macOS from sleeping while openhort is serving.
///
/// Uses IOPMAssertionCreateWithName -- the same API that Amphetamine,
/// Caffeine, and similar apps use.
final class PowerManager {
    private var systemAssertion: IOPMAssertionID = 0
    private var displayAssertion: IOPMAssertionID = 0
    private(set) var isPreventingSleep = false
    private(set) var isPreventingDisplaySleep = false

    func preventSleep(preventDisplaySleep: Bool = false) {
        if !isPreventingSleep {
            let result = IOPMAssertionCreateWithName(
                kIOPMAssertPreventUserIdleSystemSleep as CFString,
                IOPMAssertionLevel(kIOPMAssertionLevelOn),
                "openhort remote viewer is active" as CFString,
                &systemAssertion
            )
            isPreventingSleep = (result == kIOReturnSuccess)
        }

        if preventDisplaySleep && !isPreventingDisplaySleep {
            let result = IOPMAssertionCreateWithName(
                kIOPMAssertPreventUserIdleDisplaySleep as CFString,
                IOPMAssertionLevel(kIOPMAssertionLevelOn),
                "openhort remote viewer -- display kept on" as CFString,
                &displayAssertion
            )
            isPreventingDisplaySleep = (result == kIOReturnSuccess)
        }
    }

    func allowSleep() {
        if systemAssertion != 0 {
            IOPMAssertionRelease(systemAssertion)
            systemAssertion = 0
        }
        if displayAssertion != 0 {
            IOPMAssertionRelease(displayAssertion)
            displayAssertion = 0
        }
        isPreventingSleep = false
        isPreventingDisplaySleep = false
    }
}
