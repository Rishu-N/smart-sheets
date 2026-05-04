import Foundation
import UserNotifications
import AppKit

/// Posts macOS notifications when the user saves a reading without time tracked.
/// Tapping the notification opens the SmartSheet web UI in the default browser
/// so the user can fill in the missing time directly.
final class NotificationManager: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationManager()

    private static let categoryID = "READING_MISSING_TIME"
    private static let openAction = "OPEN_SPREADSHEET"

    private var requestedAuthorization = false

    /// Wire up the delegate and register the action category. Call once on
    /// application launch (e.g. from `applicationDidFinishLaunching`).
    func bootstrap() {
        let center = UNUserNotificationCenter.current()
        center.delegate = self

        let action = UNNotificationAction(
            identifier: Self.openAction,
            title: "Open Spreadsheet",
            options: [.foreground]
        )
        let category = UNNotificationCategory(
            identifier: Self.categoryID,
            actions: [action],
            intentIdentifiers: [],
            options: []
        )
        center.setNotificationCategories([category])
    }

    /// Lazily request authorization the first time we need to post a
    /// notification. macOS shows this prompt once per bundle id.
    private func ensureAuthorization() async -> Bool {
        let center = UNUserNotificationCenter.current()
        let settings = await center.notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            return true
        case .denied:
            return false
        case .notDetermined:
            if requestedAuthorization { return false }
            requestedAuthorization = true
            do {
                return try await center.requestAuthorization(options: [.alert, .sound])
            } catch {
                return false
            }
        @unknown default:
            return false
        }
    }

    /// Post a notification reminding the user to fill in the time on the row
    /// they just saved. Tapping the body or the action opens the spreadsheet.
    func notifyMissingTime(title: String) async {
        guard await ensureAuthorization() else {
            // Last-resort fallback so the user still gets feedback even when
            // notifications are denied.
            APIClient.shared.openSpreadsheet()
            return
        }

        let content = UNMutableNotificationContent()
        content.title = "Reading saved without time"
        let trimmed = title.trimmingCharacters(in: .whitespaces)
        content.body = trimmed.isEmpty
            ? "Tap to open the spreadsheet and add how long it took to read."
            : "“\(trimmed)” — tap to open the spreadsheet and add the time."
        content.sound = .default
        content.categoryIdentifier = Self.categoryID
        content.userInfo = ["url": APIClient.shared.spreadsheetURL.absoluteString]

        let request = UNNotificationRequest(
            identifier: "missing-time-\(UUID().uuidString)",
            content: content,
            trigger: nil          // deliver immediately
        )
        do {
            try await UNUserNotificationCenter.current().add(request)
        } catch {
            // If adding the notification fails for any reason, open the
            // spreadsheet directly so the reminder isn't lost.
            APIClient.shared.openSpreadsheet()
        }
    }

    // MARK: - UNUserNotificationCenterDelegate

    /// Show the banner even when our app is the frontmost.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler:
            @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound])
    }

    /// Open the spreadsheet when the user taps the notification body or the
    /// "Open Spreadsheet" action.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        defer { completionHandler() }
        let userInfo = response.notification.request.content.userInfo
        let urlString = (userInfo["url"] as? String)
            ?? APIClient.shared.spreadsheetURL.absoluteString
        if let url = URL(string: urlString) {
            NSWorkspace.shared.open(url)
        }
    }
}
