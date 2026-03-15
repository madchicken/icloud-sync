import Foundation

enum ShellRunner {

    @discardableResult
    static func run(_ args: [String]) throws -> String {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: args[0])
        p.arguments = Array(args.dropFirst())
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError  = FileHandle.nullDevice
        try p.run()
        p.waitUntilExit()
        return String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    }

    static func runAsync(_ args: [String], completion: @escaping (Result<String, Error>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let output = try run(args)
                DispatchQueue.main.async { completion(.success(output)) }
            } catch {
                DispatchQueue.main.async { completion(.failure(error)) }
            }
        }
    }

    /// Resolve the icloud-sync CLI command.
    /// Returns `[python3, script]` for the bundled venv, or `[path]` from PATH lookup.
    static func icloudSyncCommand() -> [String]? {
        if let resourcePath = Bundle.main.resourcePath {
            let python = "\(resourcePath)/venv/bin/python3"
            let script = "\(resourcePath)/venv/bin/icloud-sync"
            if FileManager.default.isExecutableFile(atPath: python)
                && FileManager.default.fileExists(atPath: script)
            {
                return [python, script]
            }
        }
        // PATH fallback
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        task.arguments = ["icloud-sync"]
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = FileHandle.nullDevice
        do {
            try task.run()
            task.waitUntilExit()
            let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return output.isEmpty ? nil : [output]
        } catch {
            return nil
        }
    }

    /// Run an AppleScript string via osascript.
    static func appleScript(_ source: String) {
        var error: NSDictionary?
        NSAppleScript(source: source)?.executeAndReturnError(&error)
    }
}
