import Foundation

enum ConfigStore {

    // MARK: — Paths

    static let configDir: URL = {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/icloud_sync")
    }()

    static let configURL:  URL = configDir.appendingPathComponent("config.json")
    static let prefsURL:   URL = configDir.appendingPathComponent("prefs.json")
    static let pidURL:     URL = configDir.appendingPathComponent("daemon.pid")
    static let activityURL: URL = configDir.appendingPathComponent("activity.json")
    static let logURL:     URL = {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/icloud_sync.log")
    }()

    // MARK: — Config

    static func load() -> AppConfig? {
        guard let data = try? Data(contentsOf: configURL) else { return nil }
        return try? JSONDecoder().decode(AppConfig.self, from: data)
    }

    static func updatePollInterval(_ interval: Int) throws {
        guard var raw = try? JSONSerialization.jsonObject(with: Data(contentsOf: configURL)) as? [String: Any] else { return }
        raw["poll_interval"] = interval
        let data = try JSONSerialization.data(withJSONObject: raw, options: .prettyPrinted)
        try data.write(to: configURL, options: .atomic)
    }

    // MARK: — PID

    static func readPID() -> pid_t? {
        guard let str = try? String(contentsOf: pidURL, encoding: .utf8) else { return nil }
        return pid_t(str.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    // MARK: — Activity heartbeat (written by the daemon during copies)

    private struct ActivityHeartbeat: Decodable {
        let lastActive: TimeInterval
        enum CodingKeys: String, CodingKey { case lastActive = "last_active" }
    }

    static func lastActivityDate() -> Date? {
        guard let data = try? Data(contentsOf: activityURL),
              let heartbeat = try? JSONDecoder().decode(ActivityHeartbeat.self, from: data)
        else { return nil }
        return Date(timeIntervalSince1970: heartbeat.lastActive)
    }
}
