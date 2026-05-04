import Foundation
import SwiftUI

/// User-tweakable settings persisted in UserDefaults via @AppStorage.
/// Defaults assume the project lives at the path baked in below; override via the Settings sheet.
final class AppSettings: ObservableObject {
    static let shared = AppSettings()

    @AppStorage("projectRoot")
    var projectRoot: String = "/Users/rishunand/Desktop/CLaude/excel/smartsheet"

    /// Empty string means "auto-resolve via `which python3`".
    @AppStorage("pythonPath")
    var pythonPath: String = ""

    @AppStorage("serverPort")
    var serverPort: Int = 8000

    var baseURL: URL {
        URL(string: "http://localhost:\(serverPort)")!
    }
}
