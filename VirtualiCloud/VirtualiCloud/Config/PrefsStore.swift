import Foundation

enum PrefsStore {

    static func load() -> AppPrefs {
        guard let data = try? Data(contentsOf: ConfigStore.prefsURL) else { return .default }
        return (try? JSONDecoder().decode(AppPrefs.self, from: data)) ?? .default
    }

    static func save(_ prefs: AppPrefs) {
        guard let data = try? JSONEncoder().encode(prefs) else { return }
        try? data.write(to: ConfigStore.prefsURL, options: .atomic)
    }
}
