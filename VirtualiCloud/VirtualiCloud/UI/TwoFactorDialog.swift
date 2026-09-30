import AppKit

/// Answers the daemon's two-factor requests.
///
/// The daemon runs headless: when iCloud wants a verification code it writes
/// ~/.config/icloud_sync/2fa_state.json ("waiting") and blocks until the code
/// shows up in ~/.icloud_sync_2fa_code. StatusBarController polls this every
/// second; we show one native dialog per request and hand the code over.
enum TwoFactorDialog {

    /// `since` of the last request we already answered (or the user dismissed),
    /// so a still-pending request does not re-open the dialog every second.
    private static var handledSince: TimeInterval?
    private static var isShowing = false

    static func checkPending() {
        guard !isShowing, let state = ConfigStore.readTwoFAState() else { return }

        switch state.status {
        case "waiting":
            guard handledSince != state.since else { return }
            handledSince = state.since
            isShowing = true
            defer { isShowing = false }
            withRegularActivation {
                if let code = promptForCode(message: state.message) {
                    do {
                        try ConfigStore.writeTwoFACode(code)
                    } catch {
                        showAlert("Could not hand the code to the sync daemon:\n\(error.localizedDescription)")
                    }
                }
            }

        case "failed":
            // Shown once; the daemon has already exited.
            ConfigStore.clearTwoFAState()
            handledSince = nil
            isShowing = true
            defer { isShowing = false }
            withRegularActivation {
                showAlert("Two-factor authentication failed.\n\n\(state.message)")
            }

        default:
            break
        }
    }

    // MARK: — Dialogs

    private static func promptForCode(message: String) -> String? {
        let a = NSAlert()
        a.messageText = "iCloud Two-Factor Authentication"
        a.informativeText = message.isEmpty
            ? "Enter the verification code sent to your Apple devices:"
            : message
        a.addButton(withTitle: "OK")
        a.addButton(withTitle: "Cancel")

        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        field.placeholderString = "123456"
        a.accessoryView = field
        a.window.initialFirstResponder = field

        guard a.runModal() == .alertFirstButtonReturn else { return nil }
        let code = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        return code.isEmpty ? nil : code
    }

    private static func showAlert(_ message: String) {
        let a = NSAlert()
        a.messageText = "iCloud Sync"
        a.informativeText = message
        a.addButton(withTitle: "OK")
        a.runModal()
    }
}
