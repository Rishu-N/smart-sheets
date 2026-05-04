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
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        p.arguments = ["python3"]
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = Pipe()
        try p.run()
        p.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let path = (String(data: data, encoding: .utf8) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if path.isEmpty {
            throw NSError(
                domain: "ReadingTracker",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "python3 not found in PATH"]
            )
        }
        return path
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
