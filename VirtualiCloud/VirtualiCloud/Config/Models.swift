import Foundation

struct SyncPair: Codable, Equatable {
    let localDir: String
    let remoteDir: String

    enum CodingKeys: String, CodingKey {
        case localDir  = "local_dir"
        case remoteDir = "remote_dir"
    }

    var localURL: URL { URL(fileURLWithPath: localDir) }
    var displayName: String { "\(localURL.lastPathComponent)  ↔  \(remoteDir)" }
}

struct AppConfig: Codable {
    let username: String
    let pairs: [SyncPair]
    let pollInterval: Int

    enum CodingKeys: String, CodingKey {
        case username, pairs
        case pollInterval = "poll_interval"
    }
}

struct AppPrefs: Codable {
    var autostartDaemon: Bool?

    enum CodingKeys: String, CodingKey {
        case autostartDaemon = "autostart_daemon"
    }

    static var `default`: AppPrefs { AppPrefs(autostartDaemon: false) }
}
