import AppKit

enum SetupHelper {
    /// Open a Terminal window running `icloud-sync setup`.
    /// Prefers the bundled venv copy; falls back to PATH lookup.
    static func openInTerminal() {
        guard let cmd = ShellRunner.icloudSyncCommand() else {
            UNHelper.post(title: "iCloud Sync", body: "Cannot find icloud-sync CLI.")
            return
        }
        let escaped = (cmd + ["setup"]).map { "'\($0.replacingOccurrences(of: "'", with: "'\\''"))'" }.joined(separator: " ")
        ShellRunner.appleScript("""
        tell application "Terminal"
            activate
            do script "\(escaped)"
        end tell
        """)
    }
}
