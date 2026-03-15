import AppKit

enum PairingsDialog {

    static func run() {
        withRegularActivation {
            runLoop()
        }
    }

    private static func runLoop() {
        while true {
            let pairs = ConfigStore.load()?.pairs ?? []

            // Build message
            var body: String
            var buttons: [String]
            if pairs.isEmpty {
                body = "No sync pairs configured yet."
                buttons = ["Done", "Add Pair…"]
            } else {
                let lines = pairs.map { "  \($0.localDir)  ↔  iCloud Drive / \($0.remoteDir)" }
                body = "Configured sync pairs:\n\n" + lines.joined(separator: "\n")
                buttons = ["Done", "Remove…", "Add Pair…"]
            }

            let clicked = showDialog(body, buttons: buttons, title: "Sync Pairings", defaultButton: "Done")

            switch clicked {
            case "Add Pair…":
                addPair()
            case "Remove…":
                removePair(from: pairs)
            default:
                return
            }
        }
    }

    private static func addPair() {
        guard let cmd = ShellRunner.icloudSyncCommand() else {
            showDialog("Cannot find icloud-sync CLI.", buttons: ["OK"], title: "iCloud Sync", defaultButton: "OK")
            return
        }

        // Step 1: pick iCloud Drive folder (combo box with live folder list)
        let folders = ICFolderHelper.fetchFolders(cmd: cmd)

        let a = NSAlert()
        a.messageText = "Select iCloud Drive Folder"
        a.informativeText = "Pick an existing folder or type a new name:"
        a.addButton(withTitle: "Next")
        a.addButton(withTitle: "Cancel")

        let combo = NSComboBox(frame: NSRect(x: 0, y: 0, width: 350, height: 26))
        combo.completes = true
        for f in folders { combo.addItem(withObjectValue: f) }
        if !folders.isEmpty { combo.selectItem(at: 0) }
        combo.isEditable = true
        a.accessoryView = combo
        a.window.initialFirstResponder = combo

        guard a.runModal() == .alertFirstButtonReturn else { return }
        let remote = combo.stringValue.trimmingCharacters(in: .whitespaces)
        guard !remote.isEmpty else { return }

        // Step 2: pick local folder
        let panel = NSOpenPanel()
        panel.title = "Select local folder to sync with \"\(remote)\""
        panel.message = "Choose the local folder:"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false

        guard panel.runModal() == .OK, let localURL = panel.url else { return }

        do {
            try ShellRunner.run(cmd + ["add-pair", "--local", localURL.path, "--remote", remote])
            UNHelper.post(title: "iCloud Sync", body: "Pair added: \(localURL.lastPathComponent) ↔ \(remote)")
        } catch {
            showDialog("Error adding pair:\n\(error.localizedDescription)", buttons: ["OK"], title: "iCloud Sync", defaultButton: "OK")
        }
    }

    private static func removePair(from pairs: [SyncPair]) {
        guard !pairs.isEmpty else { return }
        let labels = pairs.map { "\($0.localDir)  ↔  iCloud Drive / \($0.remoteDir)" }

        let a = NSAlert()
        a.messageText = "Remove Sync Pair"
        a.informativeText = "Select the pair to remove:"

        // Popup button as accessory
        let popup = NSPopUpButton(frame: NSRect(x: 0, y: 0, width: 400, height: 26))
        for label in labels { popup.addItem(withTitle: label) }
        a.accessoryView = popup
        a.addButton(withTitle: "Remove")
        a.addButton(withTitle: "Cancel")

        guard a.runModal() == .alertFirstButtonReturn else { return }
        let selected = pairs[popup.indexOfSelectedItem]

        let confirmed = showDialog(
            "Remove this sync pair?\n\nLocal:   \(selected.localDir)\nRemote: iCloud Drive / \(selected.remoteDir)\n\nFiles will NOT be deleted.",
            buttons: ["Cancel", "Remove"],
            title: "Confirm Removal",
            defaultButton: "Remove"
        )
        guard confirmed == "Remove" else { return }

        guard let rcmd = ShellRunner.icloudSyncCommand() else {
            showDialog("Cannot find icloud-sync CLI.", buttons: ["OK"], title: "iCloud Sync", defaultButton: "OK")
            return
        }
        do {
            try ShellRunner.run(rcmd + ["remove-pair", "--remote", selected.remoteDir])
            UNHelper.post(title: "iCloud Sync", body: "Removed: \(selected.localURL.lastPathComponent) ↔ \(selected.remoteDir)")
        } catch {
            showDialog("Error removing pair:\n\(error.localizedDescription)", buttons: ["OK"], title: "iCloud Sync", defaultButton: "OK")
        }
    }

    // MARK: — Dialog helpers

    @discardableResult
    private static func showDialog(_ message: String, buttons: [String], title: String, defaultButton: String) -> String? {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = message
        for btn in buttons { a.addButton(withTitle: btn) }
        // NSAlert returns buttons in reverse order (first added = first button return)
        let response = a.runModal()
        let idx = response.rawValue - NSApplication.ModalResponse.alertFirstButtonReturn.rawValue
        guard idx >= 0 && idx < buttons.count else { return nil }
        return buttons[idx]
    }

    private static func inputDialog(_ prompt: String, defaultValue: String, title: String) -> String? {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = prompt
        a.addButton(withTitle: "OK")
        a.addButton(withTitle: "Cancel")

        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24))
        field.stringValue = defaultValue
        a.accessoryView = field
        a.window.initialFirstResponder = field

        guard a.runModal() == .alertFirstButtonReturn else { return nil }
        return field.stringValue
    }
}
