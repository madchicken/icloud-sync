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
    static let twoFAStateURL: URL = configDir.appendingPathComponent("2fa_state.json")
    /// Where the daemon expects the verification code (see icloud_sync/twofa.py).
    static let twoFACodeURL: URL = {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".icloud_sync_2fa_code")
    }()
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

    // MARK: — 2FA handshake (daemon asks, app answers — see icloud_sync/twofa.py)

    struct TwoFAState: Decodable {
        let status: String      // "waiting" | "failed"
        let message: String
        let since: TimeInterval // identifies one request; the app answers each once
    }

    static func readTwoFAState() -> TwoFAState? {
        guard let data = try? Data(contentsOf: twoFAStateURL) else { return nil }
        return try? JSONDecoder().decode(TwoFAState.self, from: data)
    }

    static func writeTwoFACode(_ code: String) throws {
        try Data(code.utf8).write(to: twoFACodeURL, options: .atomic)
    }

    static func clearTwoFAState() {
        try? FileManager.default.removeItem(at: twoFAStateURL)
    }
}
