import Foundation
import Combine
import AppKit

/// Manages the FastAPI subprocess: spawn on launch, terminate on quit.
/// If a server is already running on the configured port, adopts it instead of spawning.
final class ServerController: ObservableObject {
    static let shared = ServerController()

    enum ServerStatus: Equatable {
        case stopped
        case starting
        case running
        case adopted        // Was already running before we tried to spawn.
        case failed(String)
    }

    @Published var status: ServerStatus = .stopped

    private var process: Process?
    private var weOwnProcess = false
    private var pollTimer: Timer?
    private var pollDeadline: Date = .distantPast
    private let queue = DispatchQueue(label: "ReadingTracker.ServerController")

    // MARK: - Public

    func start() {
        queue.async { [weak self] in
            guard let self else { return }
            switch self.status {
            case .running, .adopted, .starting: return
            default: break
            }
            self.setStatus(.starting)

            // If something already answers /auth/whoami, adopt it.
            if self.healthCheckSync() {
                self.setStatus(.adopted)
                return
            }

            do {
                try self.spawn()
                self.weOwnProcess = true
                self.startPolling()
            } catch {
                self.setStatus(.failed(error.localizedDescription))
            }
        }
    }

    /// Synchronous stop — safe to call from `applicationShouldTerminate` (main thread).
    /// Sends SIGTERM, waits up to 3 s, escalates to SIGKILL.
    func stop() {
        var procToKill: Process? = nil
        queue.sync {
            if self.weOwnProcess {
                procToKill = self.process
            }
            self.process = nil
            self.weOwnProcess = false
        }

        if let p = procToKill, p.isRunning {
            kill(p.processIdentifier, SIGTERM)
            let deadline = Date().addingTimeInterval(3)
            while p.isRunning && Date() < deadline {
                usleep(100_000)
            }
            if p.isRunning {
                kill(p.processIdentifier, SIGKILL)
            }
        }

        DispatchQueue.main.async { [weak self] in
            self?.pollTimer?.invalidate()
            self?.pollTimer = nil
            self?.status = .stopped
        }
    }

    // MARK: - Internals

    private func setStatus(_ s: ServerStatus) {
        DispatchQueue.main.async { [weak self] in self?.status = s }
    }

    private func spawn() throws {
        let pythonAbs: String
        let pyOverride = AppSettings.shared.pythonPath
        if !pyOverride.isEmpty {
            pythonAbs = pyOverride
        } else {
            pythonAbs = try Self.resolvePython()
        }
        let root = AppSettings.shared.projectRoot

        let p = Process()
        p.executableURL = URL(fileURLWithPath: pythonAbs)
        p.arguments = ["app.py"]
        p.currentDirectoryURL = URL(fileURLWithPath: root)

        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        p.environment = env

        // Pipe stdout/stderr to ~/Library/Logs/ReadingTracker.log (append).
        let logURL = Self.logFileURL()
        try? FileManager.default.createDirectory(
            at: logURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        let handle = try FileHandle(forWritingTo: logURL)
        handle.seekToEndOfFile()
        p.standardOutput = handle
        p.standardError = handle

        p.terminationHandler = { [weak self] _ in
            guard let self else { return }
            if self.weOwnProcess {
                self.process = nil
                self.weOwnProcess = false
                DispatchQueue.main.async { self.status = .stopped }
            }
        }

        try p.run()
        self.process = p
    }

    private static func resolvePython() throws -> String {
        // Probe candidates in priority order. Framework installs (pip-managed) come
        // first because /usr/bin/python3 is the bare Apple-stub that often lacks deps.
        let candidates: [String] = [
            // Python.org framework installer (most common for pip users on macOS)
            "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3",
            // Homebrew (Apple Silicon)
            "/opt/homebrew/bin/python3",
            "/opt/homebrew/bin/python3.11",
            "/opt/homebrew/bin/python3.12",
            // Homebrew (Intel)
            "/usr/local/bin/python3",
            // pyenv shim
            (ProcessInfo.processInfo.environment["HOME"] ?? "") + "/.pyenv/shims/python3",
            // System fallback last (usually missing fastapi/pandas/etc.)
            "/usr/bin/python3",
        ]

        for candidate in candidates {
            guard FileManager.default.isExecutableFile(atPath: candidate) else { continue }
            if pythonHasFastapi(candidate) { return candidate }
        }

        // Last resort: ask user's login shell (may have PATH set in ~/.zshrc / ~/.bashrc)
        if let shellPath = resolvePythonViaShell(), pythonHasFastapi(shellPath) {
            return shellPath
        }

        throw NSError(
            domain: "ReadingTracker",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey:
                "Could not find a python3 with 'fastapi' installed. " +
                "Set the Python path in Settings to the interpreter you use for pip installs."]
        )
    }

    /// Returns true if `pythonPath` can `import fastapi` without error.
    private static func pythonHasFastapi(_ pythonPath: String) -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: pythonPath)
        p.arguments = ["-c", "import fastapi"]
        p.standardOutput = Pipe()
        p.standardError = Pipe()
        do { try p.run() } catch { return false }
        p.waitUntilExit()
        return p.terminationStatus == 0
    }

    /// Falls back to resolving python3 through a login shell so ~/.zshrc PATH is honoured.
    private static func resolvePythonViaShell() -> String? {
        let shell = ProcessInfo.processInfo.environment["SHELL"] ?? "/bin/zsh"
        let p = Process()
        p.executableURL = URL(fileURLWithPath: shell)
        p.arguments = ["-lc", "which python3"]
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = Pipe()
        do { try p.run() } catch { return nil }
        p.waitUntilExit()
        let out = (String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return out.isEmpty ? nil : out
    }

    private static func logFileURL() -> URL {
        FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Logs/ReadingTracker.log")
    }

    private func startPolling() {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.pollDeadline = Date().addingTimeInterval(20)
            self.pollTimer?.invalidate()
            self.pollTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] timer in
                guard let self else { timer.invalidate(); return }
                if Date() > self.pollDeadline {
                    timer.invalidate()
                    self.pollTimer = nil
                    self.status = .failed(
                        "Server didn't respond on port \(AppSettings.shared.serverPort) within 20s"
                    )
                    return
                }
                self.queue.async {
                    if self.healthCheckSync() {
                        DispatchQueue.main.async {
                            timer.invalidate()
                            self.pollTimer = nil
                            self.status = .running
                        }
                    }
                }
            }
        }
    }

    private func healthCheckSync() -> Bool {
        let url = AppSettings.shared.baseURL
            .appendingPathComponent("/auth/whoami")
        var req = URLRequest(url: url)
        req.timeoutInterval = 1.5
        let sem = DispatchSemaphore(value: 0)
        var ok = false
        let task = URLSession.shared.dataTask(with: req) { _, resp, _ in
            ok = (resp as? HTTPURLResponse)?.statusCode == 200
            sem.signal()
        }
        task.resume()
        _ = sem.wait(timeout: .now() + 2)
        return ok
    }
}
