import AppKit

enum SetupHelper {
    /// V1: open a Terminal window running `icloud-sync setup`.
    /// The Python CLI handles Apple ID, password, 2FA — no native dialogs needed.
    static func openInTerminal() {
        ShellRunner.appleScript("""
        tell application "Terminal"
            activate
            do script "icloud-sync setup"
        end tell
        """)
    }
}
