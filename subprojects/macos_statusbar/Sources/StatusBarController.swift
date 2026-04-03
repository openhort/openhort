import AppKit

/// Main status bar controller -- owns the NSStatusItem, menu, and
/// coordinates the server bridge, power manager, and shared key.
final class StatusBarController: NSObject {
    let managed: Bool
    let bridge: ServerBridge
    let power: PowerManager

    private let sharedKey: SharedKey
    private let statusItem: NSStatusItem

    // Menu items we update dynamically
    private var serverStatusMenuItem: NSMenuItem!
    private var viewersMenuItem: NSMenuItem!
    private var startStopItem: NSMenuItem?
    private var openBrowserItem: NSMenuItem!
    private var copyURLItem: NSMenuItem!
    private var sleepItem: NSMenuItem!
    private var displaySleepItem: NSMenuItem!

    init(managed: Bool) {
        self.managed = managed
        self.sharedKey = SharedKey()
        self.bridge = ServerBridge(sharedKey: sharedKey)
        self.power = PowerManager()
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)

        super.init()

        setupIcon(active: false)
        buildMenu()
        power.preventSleep()

        bridge.onStatusChange = { [weak self] status in
            self?.onStatusChange(status)
        }
        bridge.startPolling()
    }

    // MARK: - Icon

    private func setupIcon(active: Bool, warning: Bool = false) {
        guard let button = statusItem.button else { return }
        button.image = createIcon(active: active, warning: warning)
        button.toolTip = "openhort -- Remote Window Viewer"
    }

    private func createIcon(active: Bool, warning: Bool) -> NSImage {
        let size = NSSize(width: 18, height: 18)
        let image = NSImage(size: size)
        image.lockFocus()

        // Rounded rect border
        let rect = NSRect(x: 2, y: 2, width: 14, height: 14)
        let path = NSBezierPath(roundedRect: rect, xRadius: 3, yRadius: 3)
        NSColor.labelColor.setStroke()
        path.lineWidth = 1.5
        path.stroke()

        // "H" letter
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 10, weight: .bold),
            .foregroundColor: NSColor.labelColor,
        ]
        let hStr = NSAttributedString(string: "H", attributes: attrs)
        let hSize = hStr.size()
        hStr.draw(at: NSPoint(
            x: (18 - hSize.width) / 2,
            y: (18 - hSize.height) / 2 - 0.5
        ))

        // Status dot (top-right)
        if active || warning {
            let dotRect = NSRect(x: 12, y: 12, width: 5, height: 5)
            let dot = NSBezierPath(ovalIn: dotRect)
            (warning ? NSColor.systemYellow : NSColor.systemGreen).setFill()
            dot.fill()
        }

        image.unlockFocus()
        image.isTemplate = !(active || warning)
        return image
    }

    // MARK: - Menu

    private func buildMenu() {
        let menu = NSMenu()
        menu.autoenablesItems = false

        // Status labels
        serverStatusMenuItem = addLabel(to: menu, title: "Server: Checking...")
        viewersMenuItem = addLabel(to: menu, title: "No active viewers")
        menu.addItem(.separator())

        // Controls
        if !managed {
            startStopItem = addAction(to: menu, title: "Start Server", action: #selector(toggleServer(_:)))
        }
        openBrowserItem = addAction(to: menu, title: "Open in Browser\u{2026}", action: #selector(openBrowser(_:)))
        openBrowserItem.isEnabled = false
        copyURLItem = addAction(to: menu, title: "Copy URL", action: #selector(copyURL(_:)))
        copyURLItem.isEnabled = false
        menu.addItem(.separator())

        // Settings submenu
        let settingsMenu = NSMenu()
        settingsMenu.autoenablesItems = false

        sleepItem = addAction(to: settingsMenu, title: "Prevent Sleep", action: #selector(toggleSleep(_:)))
        sleepItem.state = .on
        displaySleepItem = addAction(to: settingsMenu, title: "Keep Display On", action: #selector(toggleDisplaySleep(_:)))
        displaySleepItem.state = .off

        let settingsParent = NSMenuItem(title: "Settings", action: nil, keyEquivalent: "")
        settingsParent.submenu = settingsMenu
        menu.addItem(settingsParent)

        menu.addItem(.separator())

        let quitLabel = managed ? "Quit Status Bar" : "Quit OpenHort"
        addAction(to: menu, title: quitLabel, action: #selector(quitApp(_:)))

        statusItem.menu = menu
    }

    private func addLabel(to menu: NSMenu, title: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        menu.addItem(item)
        return item
    }

    @discardableResult
    private func addAction(to menu: NSMenu, title: String, action: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
        item.target = self
        menu.addItem(item)
        return item
    }

    // MARK: - Status Updates

    private func onStatusChange(_ status: ServerStatus) {
        if status.running {
            serverStatusMenuItem.title = "Server: Running"
            startStopItem?.title = "Stop Server"
            openBrowserItem.isEnabled = true
            copyURLItem.isEnabled = true
            setupIcon(active: true)
        } else {
            serverStatusMenuItem.title = "Server: Stopped"
            startStopItem?.title = "Start Server"
            openBrowserItem.isEnabled = false
            copyURLItem.isEnabled = false
            setupIcon(active: false)
        }

        if status.observers > 0 {
            let s = status.observers == 1 ? "" : "s"
            viewersMenuItem.title = "\(status.observers) viewer\(s) connected"
        } else {
            viewersMenuItem.title = "No active viewers"
        }
    }

    // MARK: - Actions

    @objc private func toggleServer(_ sender: NSMenuItem) {
        // Standalone mode only -- managed mode has no start/stop
    }

    @objc private func openBrowser(_ sender: NSMenuItem) {
        let urlString = bridge.status.httpURL.isEmpty ? "http://localhost:8940" : bridge.status.httpURL
        if let url = URL(string: urlString) {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func copyURL(_ sender: NSMenuItem) {
        let urlString = bridge.status.httpURL.isEmpty ? "http://localhost:8940" : bridge.status.httpURL
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(urlString, forType: .string)
    }

    @objc private func toggleSleep(_ sender: NSMenuItem) {
        if power.isPreventingSleep {
            power.allowSleep()
            sender.state = .off
        } else {
            power.preventSleep()
            sender.state = .on
        }
    }

    @objc private func toggleDisplaySleep(_ sender: NSMenuItem) {
        if power.isPreventingDisplaySleep {
            power.allowSleep()
            power.preventSleep(preventDisplaySleep: false)
            sender.state = .off
        } else {
            power.preventSleep(preventDisplaySleep: true)
            sender.state = .on
        }
    }

    @objc private func quitApp(_ sender: NSMenuItem) {
        bridge.stopPolling()
        power.allowSleep()
        NSApp.terminate(nil)
    }
}
