import AppKit
import ServiceManagement

enum UninstallHelper {

    static func run(daemonManager: DaemonManager) {
        withRegularActivation {
            perform(daemonManager: daemonManager)
        }
    }

    private static func perform(daemonManager: DaemonManager) {
        let a = NSAlert()
        a.messageText = "Uninstall iCloud Sync"
        a.informativeText = """
        This will remove iCloud Sync from your Mac:

        • Stop the sync daemon
        • Remove the login item
        • Delete config, preferences and log files
        • Remove saved credentials from the Keychain
        • Move the app to the Trash

        Your synced files will NOT be deleted.
        """
        a.addButton(withTitle: "Uninstall")
        a.addButton(withTitle: "Cancel")
        a.alertStyle = .warning
        guard a.runModal() == .alertFirstButtonReturn else { return }

        // 1. Stop daemon
        if daemonManager.isRunning() { daemonManager.stop() }

        // 2. Remove login item
        LaunchAtLogin.setEnabled(false)

        // 3. Remove credentials from Keychain
        if let username = ConfigStore.load()?.username {
            try? KeychainStore.deletePassword(account: username)
        }

        // 4. Delete config directory + log
        let configDir = ConfigStore.configDir
        try? FileManager.default.removeItem(at: configDir)
        try? FileManager.default.removeItem(at: ConfigStore.logURL)

        // 5. Move .app to Trash
        let bundlePath = Bundle.main.bundlePath
        if bundlePath.hasSuffix(".app") {
            try? FileManager.default.trashItem(at: URL(fileURLWithPath: bundlePath), resultingItemURL: nil)
        }

        NSApp.terminate(nil)
    }
}
