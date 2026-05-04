import SwiftUI
import AppKit

@main
struct ReadingTrackerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var timer = TimerModel()

    var body: some Scene {
        MenuBarExtra {
            PopoverView()
                .environmentObject(ServerController.shared)
                .environmentObject(timer)
        } label: {
            Image(systemName: "books.vertical")
        }
        .menuBarExtraStyle(.window)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        NotificationManager.shared.bootstrap()
        ServerController.shared.start()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        // Synchronous — sends SIGTERM, waits up to 3 s, escalates to SIGKILL if needed.
        ServerController.shared.stop()
        return .terminateNow
    }
}
