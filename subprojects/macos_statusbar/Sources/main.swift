import AppKit

let managed = CommandLine.arguments.contains("--managed")
let app = NSApplication.shared
app.setActivationPolicy(.accessory) // no Dock icon, menu bar only

let controller = StatusBarController(managed: managed)
// Store globally to prevent GC
withExtendedLifetime(controller) {
    app.run()
}
