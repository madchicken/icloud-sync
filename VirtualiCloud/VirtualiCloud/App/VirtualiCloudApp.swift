import AppKit
import Sparkle

// Entry point — pure AppKit, no SwiftUI scenes.
// LSUIElement in Info.plist suppresses the Dock icon.
final class AppMain: NSObject, NSApplicationDelegate {

    private var statusBarController: StatusBarController?
    let updaterController: SPUStandardUpdaterController

    override init() {
        updaterController = SPUStandardUpdaterController(
            startingUpdater: true,
            updaterDelegate: nil,
            userDriverDelegate: nil
        )
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Belt-and-suspenders alongside LSUIElement = YES in Info.plist
        NSApp.setActivationPolicy(.accessory)
        UNHelper.requestAuthorization()

        statusBarController = StatusBarController(updaterController: updaterController)

        // Watch for the daemon asking for a verification code. Started before
        // the daemon, and unconditionally, since launchd may also have spawned one.
        statusBarController?.twoFactorWatcher.start()

        // Auto-start daemon if the preference is set
        if PrefsStore.load().autostartDaemon == true {
            statusBarController?.daemonManager.startIfNeeded()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        statusBarController?.twoFactorWatcher.stop()
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
