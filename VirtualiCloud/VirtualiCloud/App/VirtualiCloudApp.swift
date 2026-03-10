import AppKit

// Entry point — pure AppKit, no SwiftUI scenes.
// LSUIElement in Info.plist suppresses the Dock icon.
final class AppMain: NSObject, NSApplicationDelegate {

    private var statusBarController: StatusBarController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Belt-and-suspenders alongside LSUIElement = YES in Info.plist
        NSApp.setActivationPolicy(.accessory)
        UNHelper.requestAuthorization()

        statusBarController = StatusBarController()

        // Auto-start daemon if the preference is set
        if PrefsStore.load().autostartDaemon == true {
            statusBarController?.daemonManager.startIfNeeded()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        // Only stop the daemon if we spawned it in this session
        statusBarController?.daemonManager.stopIfOwned()
    }
}

// Swift 5.9 @main on a non-SwiftUI class
@main
struct AppEntry {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppMain()
        app.delegate = delegate
        app.run()
    }
}
