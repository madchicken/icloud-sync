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

    // Sync-activity icon animation (mela che si riempie durante le copie)
    private var baseIcon: NSImage?
    private var activityFrames: [NSImage] = []
    private var activityPollTimer: Timer?
    private var animationTimer: Timer?
    private var isAnimatingActivity = false
    private var frameIndex = 0
    private var frameDirection = 1
    private let activityFrameCount = 8
    private let activityStaleness: TimeInterval = 2.0

    init(updaterController: SPUStandardUpdaterController) {
        self.updaterController = updaterController
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        setupIcon()
        buildMenu()
        refresh()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.refresh()
        }
        activityPollTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            self?.checkActivity()
        }
    }

    // MARK: — Icon

    private func setupIcon() {
        if let button = statusItem.button {
            // Use the template image from the bundle, fall back to text
            if let img = NSImage(named: "menubarTemplate") {
                img.isTemplate = true
                baseIcon = img
                button.image = img
                activityFrames = (0...activityFrameCount).map {
                    makeActivityFrame(fillFraction: CGFloat($0) / CGFloat(activityFrameCount), from: img)
                }
            } else {
                button.title = "☁"
            }
        }
    }

    /// Renders the base icon with everything above `fillFraction` dimmed, so cycling
    /// through fractions 0→1→0 while a copy is in progress looks like the icon filling
    /// up from the bottom and draining again.
    private func makeActivityFrame(fillFraction: CGFloat, from base: NSImage, dimAlpha: CGFloat = 0.18) -> NSImage {
        let size = base.size
        let frame = NSImage(size: size)
        frame.isTemplate = true
        frame.lockFocus()
        base.draw(in: NSRect(origin: .zero, size: size), from: .zero, operation: .sourceOver, fraction: dimAlpha)
        if fillFraction > 0 {
            NSGraphicsContext.current?.saveGraphicsState()
            NSRect(x: 0, y: 0, width: size.width, height: size.height * fillFraction).clip()
            base.draw(in: NSRect(origin: .zero, size: size), from: .zero, operation: .sourceOver, fraction: 1.0)
            NSGraphicsContext.current?.restoreGraphicsState()
        }
        frame.unlockFocus()
        return frame
    }

    // MARK: — Sync-activity animation

    /// Polled every second: turns the fill animation on/off based on the daemon's
    /// activity heartbeat (~/.config/icloud_sync/activity.json), written from
    /// download()/upload() while a copy is actually happening.
    private func checkActivity() {
        let stale = ConfigStore.lastActivityDate()
            .map { Date().timeIntervalSince($0) > activityStaleness } ?? true
        if stale && isAnimatingActivity {
            stopActivityAnimation()
        } else if !stale && !isAnimatingActivity {
            startActivityAnimation()
        }
    }

    private func startActivityAnimation() {
        guard !activityFrames.isEmpty else { return }
        isAnimatingActivity = true
        frameIndex = 0
        frameDirection = 1
        animationTimer = Timer.scheduledTimer(withTimeInterval: 0.12, repeats: true) { [weak self] _ in
            self?.advanceActivityFrame()
        }
    }

    private func stopActivityAnimation() {
        isAnimatingActivity = false
        animationTimer?.invalidate()
        animationTimer = nil
        statusItem.button?.image = baseIcon
    }

    private func advanceActivityFrame() {
        statusItem.button?.image = activityFrames[frameIndex]
        let next = frameIndex + frameDirection
        if next >= activityFrames.count {
            frameDirection = -1
            frameIndex = activityFrames.count - 2
        } else if next < 0 {
            frameDirection = 1
            frameIndex = 1
        } else {
            frameIndex = next
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
        CredentialsDialog.run()
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
