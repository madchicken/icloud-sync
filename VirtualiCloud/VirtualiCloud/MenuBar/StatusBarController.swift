import AppKit
import Sparkle

final class StatusBarController {

    let daemonManager = DaemonManager()

    private let statusItem: NSStatusItem
    private let updaterController: SPUStandardUpdaterController
    private var refreshTimer: Timer?

    // Mutable menu items updated without full menu reconstruction
    private var statusMenuItem  = NSMenuItem()
    private var toggleMenuItem  = NSMenuItem()
    private var pairsSubmenu    = NSMenu()
    private var pairsMenuItem   = NSMenuItem()

    init(updaterController: SPUStandardUpdaterController) {
        self.updaterController = updaterController
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        setupIcon()
        buildMenu()
        refresh()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    // MARK: — Icon

    private func setupIcon() {
        if let button = statusItem.button {
            // Use the template image from the bundle, fall back to text
            if let img = NSImage(named: "menubarTemplate") {
                img.isTemplate = true
                button.image = img
            } else {
                button.title = "☁"
            }
        }
    }

    // MARK: — Menu construction

    private func buildMenu() {
        let menu = NSMenu()

        statusMenuItem = NSMenuItem(title: "○  Stopped", action: nil, keyEquivalent: "")
        statusMenuItem.isEnabled = false
        menu.addItem(statusMenuItem)

        menu.addItem(.separator())

        toggleMenuItem = NSMenuItem(title: "▶  Start", action: #selector(toggleDaemon), keyEquivalent: "")
        toggleMenuItem.target = self
        menu.addItem(toggleMenuItem)

        menu.addItem(.separator())

        // Pairs submenu
        pairsMenuItem = NSMenuItem(title: "Sync Pairs", action: nil, keyEquivalent: "")
        pairsSubmenu = NSMenu()
        pairsMenuItem.submenu = pairsSubmenu
        menu.addItem(pairsMenuItem)

        let pairingsItem = NSMenuItem(title: "Pairings…", action: #selector(openPairings), keyEquivalent: "")
        pairingsItem.target = self
        menu.addItem(pairingsItem)

        menu.addItem(.separator())

        let setupItem = NSMenuItem(title: "Setup / Credentials…", action: #selector(openSetup), keyEquivalent: "")
        setupItem.target = self
        menu.addItem(setupItem)

        let settingsItem = NSMenuItem(title: "Settings…", action: #selector(openSettings), keyEquivalent: "")
        settingsItem.target = self
        menu.addItem(settingsItem)

        let logItem = NSMenuItem(title: "Open Log", action: #selector(openLog), keyEquivalent: "")
        logItem.target = self
        menu.addItem(logItem)

        let updateItem = NSMenuItem(
            title: "Check for Updates…",
            action: #selector(SPUStandardUpdaterController.checkForUpdates(_:)),
            keyEquivalent: ""
        )
        updateItem.target = updaterController
        menu.addItem(updateItem)

        menu.addItem(.separator())

        let uninstallItem = NSMenuItem(title: "Uninstall…", action: #selector(uninstall), keyEquivalent: "")
        uninstallItem.target = self
        menu.addItem(uninstallItem)

        let quitItem = NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        statusItem.menu = menu
        rebuildPairsSubmenu()
    }

    // MARK: — Refresh (called every 5 s)

    func refresh() {
        let running = daemonManager.isRunning()
        statusMenuItem.title = running ? "●  Running" : "○  Stopped"
        toggleMenuItem.title = running ? "■  Stop"    : "▶  Start"
    }

    private func rebuildPairsSubmenu() {
        pairsSubmenu.removeAllItems()
        let pairs = ConfigStore.load()?.pairs ?? []
        if pairs.isEmpty {
            pairsSubmenu.addItem(NSMenuItem(title: "(none configured)", action: nil, keyEquivalent: ""))
        } else {
            for pair in pairs {
                pairsSubmenu.addItem(NSMenuItem(title: pair.displayName, action: nil, keyEquivalent: ""))
            }
        }
    }

    // MARK: — Actions

    @objc private func toggleDaemon() {
        if daemonManager.isRunning() {
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                self?.daemonManager.stop()
                DispatchQueue.main.async { self?.refresh() }
            }
        } else {
            let pairs = ConfigStore.load()?.pairs ?? []
            guard !pairs.isEmpty else {
                alert("No sync pairs configured.\n\nUse Pairings… to add at least one local ↔ iCloud Drive folder pair.")
                return
            }
            daemonManager.start()
            refresh()
        }
    }

    @objc private func openPairings() {
        PairingsDialog.run()
        rebuildPairsSubmenu()
        daemonManager.reload()
    }

    @objc private func openSetup() {
        SetupHelper.openInTerminal()
    }

    @objc private func openSettings() {
        SettingsDialog.run(daemonManager: daemonManager)
    }

    @objc private func openLog() {
        let log = ConfigStore.logURL
        if FileManager.default.fileExists(atPath: log.path) {
            NSWorkspace.shared.open(log)
        } else {
            alert("No log file found yet.\nStart the daemon first.")
        }
    }

    @objc private func uninstall() {
        UninstallHelper.run(daemonManager: daemonManager)
    }

    @objc private func quit() {
        daemonManager.stopIfOwned()
        NSApp.terminate(nil)
    }

    // MARK: — Helpers

    private func alert(_ message: String) {
        withRegularActivation {
            let a = NSAlert()
            a.messageText = "iCloud Sync"
            a.informativeText = message
            a.addButton(withTitle: "OK")
            a.runModal()
        }
    }
}

/// Temporarily switch to .regular activation policy so alerts can receive focus,
/// then restore to .accessory (LSUIElement). Must be called on the main thread.
func withRegularActivation(_ block: () -> Void) {
    NSApp.setActivationPolicy(.regular)
    NSApp.activate(ignoringOtherApps: true)
    block()
    NSApp.setActivationPolicy(.accessory)
}
