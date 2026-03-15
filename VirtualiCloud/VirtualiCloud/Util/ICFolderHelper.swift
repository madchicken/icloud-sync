import Foundation

enum ICFolderHelper {
    /// Fetch top-level iCloud Drive folder names via the CLI.
    /// Returns an empty array on failure (caller can fall back to manual entry).
    static func fetchFolders(cmd: [String]) -> [String] {
        guard let username = ConfigStore.load()?.username else { return [] }

        let p = Process()
        p.executableURL = URL(fileURLWithPath: cmd[0])
        p.arguments = Array(cmd.dropFirst()) + ["list-folders", "--username", username]
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = FileHandle.nullDevice
        do {
            try p.run()
            p.waitUntilExit()
            guard p.terminationStatus == 0 else { return [] }
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8) ?? ""
            return output
                .split(separator: "\n")
                .map { String($0).trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
        } catch {
            return []
        }
    }
}
