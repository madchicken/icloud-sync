import AppKit

enum CredentialsDialog {

    @discardableResult
    static func run() -> Bool {
        var result = false
        withRegularActivation {
            result = runFlow()
        }
        return result
    }

    private static func runFlow() -> Bool {
        let existingUsername = ConfigStore.load()?.username ?? ""

        // Step 1: Apple ID
        guard let username = inputDialog(
            prompt: "Enter your Apple ID (email):",
            defaultValue: existingUsername,
            title: "iCloud Credentials"
        ), !username.isEmpty else { return false }

        // Step 2: Password
        guard let password = secureInputDialog(
            prompt: "Enter your iCloud password:",
            title: "iCloud Credentials"
        ), !password.isEmpty else { return false }

        // Step 3: Store in Keychain
        do {
            try KeychainStore.setPassword(password, account: username)
        } catch {
            showAlert("Failed to store credentials in Keychain:\n\(error.localizedDescription)")
            return false
        }

        // Step 4: Save username to config
        guard let cmd = ShellRunner.icloudSyncCommand() else {
            showAlert("Cannot find icloud-sync CLI.")
            return false
        }
        try? ShellRunner.run(cmd + ["store-credentials", "--username", username])

        // Step 5: Verify credentials with iCloud
        showProgress("Verifying credentials with iCloud…")
        let verifyResult = runCLI(cmd + ["verify", "--username", username])
        dismissProgress()

        let output = verifyResult.output.trimmingCharacters(in: .whitespacesAndNewlines)

        if verifyResult.exitCode == 2 && output == "2FA_REQUIRED" {
            // Step 5a: 2FA needed
            guard let code = inputDialog(
                prompt: "Enter the verification code sent to your devices:",
                defaultValue: "",
                title: "Two-Factor Authentication"
            ), !code.isEmpty else {
                showAlert("2FA cancelled. Credentials are saved — you can verify later by restarting the app.")
                return true
            }

            showProgress("Verifying 2FA code…")
            let codeResult = runCLI(cmd + ["verify", "--username", username, "--code", code])
            dismissProgress()

            let codeOutput = codeResult.output.trimmingCharacters(in: .whitespacesAndNewlines)
            if codeResult.exitCode != 0 {
                if codeOutput == "INVALID_CODE" {
                    showAlert("Invalid verification code. Credentials are saved — try again from Setup / Credentials.")
                } else {
                    showAlert("Verification failed: \(codeOutput)")
                }
                return true
            }
        } else if verifyResult.exitCode != 0 {
            if output.hasPrefix("LOGIN_FAILED:") {
                showAlert("Login failed. Please check your Apple ID and password.")
                try? KeychainStore.deletePassword(account: username)
                return false
            }
            showAlert("Verification failed: \(output)\n\nCredentials are saved — the daemon will retry on start.")
            return true
        }

        // Step 6: Verified! If no pairs, offer to add one with folder list
        let pairs = ConfigStore.load()?.pairs ?? []
        if pairs.isEmpty {
            showAlert("Login verified!\n\nNow let's configure your first sync pair.")
            addFirstPair(cmd: cmd, username: username)
        } else {
            showAlert("Login verified! Credentials updated.")
        }

        return true
    }

    // MARK: — First pair (reuses PairingsDialog which now has folder browsing)

    private static func addFirstPair(cmd: [String], username: String) {
        PairingsDialog.run()
    }

    // MARK: — CLI runner

    private static func runCLI(_ args: [String]) -> (output: String, exitCode: Int32) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: args[0])
        p.arguments = Array(args.dropFirst())
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        do {
            try p.run()
            p.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8) ?? ""
            return (output, p.terminationStatus)
        } catch {
            return (error.localizedDescription, 1)
        }
    }

    // MARK: — Dialogs

    private static var progressWindow: NSWindow?

    private static func showProgress(_ message: String) {
        let w = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 300, height: 80),
            styleMask: [.titled],
            backing: .buffered,
            defer: false
        )
        w.title = "iCloud Sync"

        let label = NSTextField(labelWithString: message)
        label.frame = NSRect(x: 20, y: 40, width: 260, height: 20)
        label.alignment = .center
        w.contentView?.addSubview(label)

        let spinner = NSProgressIndicator(frame: NSRect(x: 130, y: 10, width: 32, height: 32))
        spinner.style = .spinning
        spinner.startAnimation(nil)
        w.contentView?.addSubview(spinner)

        w.center()
        w.makeKeyAndOrderFront(nil)
        progressWindow = w

        // Keep UI responsive
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
    }

    private static func dismissProgress() {
        progressWindow?.close()
        progressWindow = nil
    }

    private static func inputDialog(prompt: String, defaultValue: String, title: String) -> String? {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = prompt
        a.addButton(withTitle: "OK")
        a.addButton(withTitle: "Cancel")

        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        field.stringValue = defaultValue
        a.accessoryView = field
        a.window.initialFirstResponder = field

        guard a.runModal() == .alertFirstButtonReturn else { return nil }
        return field.stringValue.trimmingCharacters(in: .whitespaces)
    }

    private static func secureInputDialog(prompt: String, title: String) -> String? {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = prompt
        a.addButton(withTitle: "OK")
        a.addButton(withTitle: "Cancel")

        let field = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        a.accessoryView = field
        a.window.initialFirstResponder = field

        guard a.runModal() == .alertFirstButtonReturn else { return nil }
        return field.stringValue
    }

    private static func showAlert(_ message: String) {
        let a = NSAlert()
        a.messageText = "iCloud Sync"
        a.informativeText = message
        a.addButton(withTitle: "OK")
        a.runModal()
    }
}
