import AppKit

enum SettingsDialog {

    static func run(daemonManager: DaemonManager) {
        withRegularActivation {
            showModal(daemonManager: daemonManager)
        }
    }

    private static func showModal(daemonManager: DaemonManager) {
        let config = ConfigStore.load()
        var prefs  = PrefsStore.load()

        // MARK: Accessory view
        let viewW: CGFloat = 310
        let viewH: CGFloat = 116
        let view = NSView(frame: NSRect(x: 0, y: 0, width: viewW, height: viewH))

        // Launch at login checkbox
        let loginCB = checkbox("Start at Login", x: 0, y: viewH - 26, width: viewW,
                               checked: LaunchAtLogin.isEnabled())
        view.addSubview(loginCB)

        // Auto-start daemon checkbox
        let autostartCB = checkbox("Auto-start Daemon", x: 0, y: viewH - 54, width: viewW,
                                   checked: prefs.autostartDaemon == true)
        view.addSubview(autostartCB)

        // Separator
        let sep = NSBox(frame: NSRect(x: 0, y: viewH - 66, width: viewW, height: 1))
        sep.boxType = .separator
        view.addSubview(sep)

        // Poll interval
        let pollLabel = label("Polling interval:", x: 0, y: viewH - 94)
        view.addSubview(pollLabel)

        let pollField = NSTextField(frame: NSRect(x: 120, y: viewH - 96, width: 60, height: 24))
        pollField.stringValue = "\(config?.pollInterval ?? 60)"
        pollField.alignment = .right
        view.addSubview(pollField)

        let secsLabel = label("seconds", x: 188, y: viewH - 94, width: 80)
        view.addSubview(secsLabel)

        // MARK: Alert
        let alert = NSAlert()
        alert.messageText = "iCloud Sync Settings"
        alert.informativeText = "Version \(appVersion())"
        alert.addButton(withTitle: "Save")
        alert.addButton(withTitle: "Cancel")
        alert.accessoryView = view

        guard alert.runModal() == .alertFirstButtonReturn else { return }

        // MARK: Persist
        LaunchAtLogin.setEnabled(loginCB.state == .on)

        prefs.autostartDaemon = autostartCB.state == .on
        PrefsStore.save(prefs)

        let newPoll = max(10, Int(pollField.stringValue) ?? (config?.pollInterval ?? 60))
        if newPoll != config?.pollInterval {
            try? ConfigStore.updatePollInterval(newPoll)
            daemonManager.reload()
        }
    }

    // MARK: — Helpers

    private static func checkbox(_ title: String, x: CGFloat, y: CGFloat, width: CGFloat, checked: Bool) -> NSButton {
        let btn = NSButton(frame: NSRect(x: x, y: y, width: width - x, height: 22))
        btn.setButtonType(.switch)
        btn.title = title
        btn.state = checked ? .on : .off
        return btn
    }

    private static func label(_ text: String, x: CGFloat, y: CGFloat, width: CGFloat = 110) -> NSTextField {
        let f = NSTextField(frame: NSRect(x: x, y: y, width: width, height: 20))
        f.stringValue = text
        f.isBezeled = false
        f.drawsBackground = false
        f.isEditable = false
        f.isSelectable = false
        return f
    }

    private static func appVersion() -> String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "unknown"
    }
}
