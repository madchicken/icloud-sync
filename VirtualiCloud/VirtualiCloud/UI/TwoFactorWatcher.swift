import AppKit

/// Bridges the daemon's headless 2FA/2SA request to a real dialog.
///
/// The daemon cannot show UI. When iCloud asks it to verify (typically after the
/// Apple session expires, roughly every two months) it writes
/// `~/.icloud_sync_2fa_request` and blocks polling for a code at
/// `~/.icloud_sync_2fa_code`. This watcher notices the marker, prompts, and
/// writes the code back so the daemon can finish logging in.
final class TwoFactorWatcher {

    private static let requestURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".icloud_sync_2fa_request")
    private static let codeURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".icloud_sync_2fa_code")

    private struct Request {
        let kind: String
        let pid: pid_t
        let started: Date
        let timeout: TimeInterval

        /// Identifies one daemon's one wait, so a cancelled prompt is not reshown.
        var identity: String { "\(pid)@\(started.timeIntervalSince1970)" }
    }

    private var timer: Timer?
    private var isPrompting = false
    private var handled = Set<String>()

    // MARK: — Lifecycle

    func start() {
        guard timer == nil else { return }
        let t = Timer(timeInterval: 2, repeats: true) { [weak self] _ in self?.check() }
        RunLoop.main.add(t, forMode: .common)
        timer = t
        check()
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    // MARK: — Polling

    private func check() {
        guard !isPrompting, let request = readRequest() else { return }
        guard !handled.contains(request.identity) else { return }

        // Ignore a marker whose daemon is gone, or that has already timed out —
        // Apple's code is long dead and prompting would only confuse.
        guard kill(request.pid, 0) == 0 else {
            try? FileManager.default.removeItem(at: Self.requestURL)
            return
        }
        guard Date().timeIntervalSince(request.started) < request.timeout else { return }

        handled.insert(request.identity)
        isPrompting = true
        defer { isPrompting = false }

        UNHelper.post(
            title: "iCloud Sync",
            body: "Verification required — enter the code Apple sent to your devices."
        )
        prompt(for: request)
    }

    private func readRequest() -> Request? {
        guard let data = try? Data(contentsOf: Self.requestURL),
              let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let pid = (obj["pid"] as? NSNumber)?.int32Value, pid > 0,
              let started = obj["started"] as? Double
        else { return nil }

        return Request(
            kind: obj["kind"] as? String ?? "2fa",
            pid: pid,
            started: Date(timeIntervalSince1970: started),
            timeout: obj["timeout"] as? Double ?? 600
        )
    }

    // MARK: — Prompt

    private func prompt(for request: Request) {
        let method = request.kind == "2sa" ? "two-step verification" : "two-factor authentication"
        var code: String?

        withRegularActivation {
            let a = NSAlert()
            a.messageText = "iCloud Sync — Verification Required"
            a.informativeText = """
                Your iCloud session has expired and syncing is paused.

                Enter the \(method) code Apple sent to your trusted devices.
                """
            a.addButton(withTitle: "Verify")
            a.addButton(withTitle: "Cancel")

            let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
            field.placeholderString = "000000"
            a.accessoryView = field
            a.window.initialFirstResponder = field

            if a.runModal() == .alertFirstButtonReturn {
                code = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }

        guard let code, !code.isEmpty else { return }

        do {
            try writeCode(code)
        } catch {
            withRegularActivation {
                let a = NSAlert()
                a.messageText = "iCloud Sync"
                a.informativeText = "Could not hand the code to the daemon:\n\(error.localizedDescription)"
                a.addButton(withTitle: "OK")
                a.runModal()
            }
        }
    }

    /// Write the code 0600 and rename into place, so the daemon never reads a
    /// half-written file and no other local user can read a live code.
    private func writeCode(_ code: String) throws {
        let target = Self.codeURL.path
        let tmp = target + ".tmp"

        unlink(tmp)
        let fd = open(tmp, O_WRONLY | O_CREAT | O_EXCL, 0o600)
        guard fd >= 0 else { throw Self.errnoError("open") }

        let bytes = Array(code.utf8)
        var written = 0
        while written < bytes.count {
            let n = bytes[written...].withUnsafeBufferPointer {
                write(fd, $0.baseAddress, $0.count)
            }
            guard n > 0 else {
                let err = Self.errnoError("write")
                close(fd)
                unlink(tmp)
                throw err
            }
            written += n
        }
        close(fd)

        guard rename(tmp, target) == 0 else {
            let err = Self.errnoError("rename")
            unlink(tmp)
            throw err
        }
    }

    private static func errnoError(_ op: String) -> NSError {
        NSError(
            domain: NSPOSIXErrorDomain,
            code: Int(errno),
            userInfo: [NSLocalizedDescriptionKey: "\(op) failed: \(String(cString: strerror(errno)))"]
        )
    }
}
