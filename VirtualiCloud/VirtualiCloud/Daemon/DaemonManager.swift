import Foundation

final class DaemonManager {

    private var process: Process?

    // MARK: — Public API

    func startIfNeeded() {
        guard !isRunning() else { return }
        start()
    }

    func start() {
        guard let binary = findDaemonBinary() else {
            UNHelper.post(title: "iCloud Sync", body: "Cannot find icloud-sync binary.")
            return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: binary)
        p.arguments = ["start"]
        p.standardOutput = FileHandle.nullDevice
        p.standardError  = FileHandle.nullDevice
        p.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async { self?.process = nil }
        }
        do {
            try p.run()
            process = p
            UNHelper.post(title: "iCloud Sync", body: "Daemon started — syncing in the background…")
        } catch {
            UNHelper.post(title: "iCloud Sync", body: "Failed to start daemon: \(error.localizedDescription)")
        }
    }

    func stop() {
        if let p = process, p.isRunning {
            p.terminate()
            process = nil
        } else if let pid = ConfigStore.readPID() {
            kill(pid, SIGTERM)
        }
        UNHelper.post(title: "iCloud Sync", body: "Daemon stopped.")
    }

    func stopIfOwned() {
        if let p = process, p.isRunning {
            p.terminate()
            process = nil
        }
    }

    func reload() {
        if let pid = ConfigStore.readPID() {
            kill(pid, SIGHUP)
        }
    }

    func isRunning() -> Bool {
        if let p = process { return p.isRunning }
        guard let pid = ConfigStore.readPID() else { return false }
        return kill(pid, 0) == 0
    }

    // MARK: — Binary discovery

    private func findDaemonBinary() -> String? {
        // 1. Bundled alongside the .app (distribution)
        if let resourcePath = Bundle.main.resourcePath {
            let candidate = "\(resourcePath)/venv/bin/icloud-sync"
            if FileManager.default.isExecutableFile(atPath: candidate) { return candidate }
        }
        // 2. PATH lookup (development)
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        task.arguments = ["icloud-sync"]
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = FileHandle.nullDevice
        try? task.run()
        task.waitUntilExit()
        let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return output.isEmpty ? nil : output
    }
}
