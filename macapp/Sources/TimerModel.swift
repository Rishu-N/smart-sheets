import Foundation
import Combine

/// Reading timer with start / pause / resume / stop. Survives popover open/close because
/// it's owned by the App scene as a @StateObject.
@MainActor
final class TimerModel: ObservableObject {
    enum State {
        case idle, running, paused
    }

    @Published var state: State = .idle
    @Published var elapsedSeconds: Int = 0

    private var startedAt: Date?
    private var accumulated: TimeInterval = 0
    private var ticker: AnyCancellable?

    func start() {
        guard state == .idle else { return }
        accumulated = 0
        elapsedSeconds = 0
        startedAt = Date()
        state = .running
        startTicker()
    }

    func pause() {
        guard state == .running, let s = startedAt else { return }
        accumulated += Date().timeIntervalSince(s)
        startedAt = nil
        state = .paused
        ticker?.cancel()
        ticker = nil
    }

    func resume() {
        guard state == .paused else { return }
        startedAt = Date()
        state = .running
        startTicker()
    }

    @discardableResult
    func stop() -> Int {
        if state == .running, let s = startedAt {
            accumulated += Date().timeIntervalSince(s)
        }
        startedAt = nil
        let final = Int(accumulated.rounded())
        elapsedSeconds = final
        state = .idle
        ticker?.cancel()
        ticker = nil
        return final
    }

    func reset() {
        ticker?.cancel()
        ticker = nil
        accumulated = 0
        startedAt = nil
        elapsedSeconds = 0
        state = .idle
    }

    /// Manually set the elapsed time when the user forgot to use the timer.
    /// Only honoured when the timer is idle — refuses to overwrite a live run.
    @discardableResult
    func setManual(seconds: Int) -> Bool {
        guard state == .idle else { return false }
        ticker?.cancel()
        ticker = nil
        let clamped = max(0, seconds)
        accumulated = TimeInterval(clamped)
        startedAt = nil
        elapsedSeconds = clamped
        return true
    }

    func wpm(words: Int) -> Double {
        guard elapsedSeconds > 0, words > 0 else { return 0 }
        return Double(words) / Double(elapsedSeconds) * 60.0
    }

    private func startTicker() {
        ticker = Timer.publish(every: 1, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                guard let self, let s = self.startedAt else { return }
                self.elapsedSeconds = Int((self.accumulated + Date().timeIntervalSince(s)).rounded())
            }
    }
}
