import SwiftUI
import AppKit

/// Forces the SwiftUI MenuBarExtra popover to become the key window when it
/// appears. Without this the popover opens as a non-key panel, which makes
/// every control render in its inactive (greyed-out) style and silently drops
/// keyboard input. Attach as `.background(ActivatePopoverWindow())`.
private struct ActivatePopoverWindow: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let v = NSView()
        DispatchQueue.main.async {
            NSApp.activate(ignoringOtherApps: true)
            v.window?.makeKeyAndOrderFront(nil)
        }
        return v
    }
    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            NSApp.activate(ignoringOtherApps: true)
            nsView.window?.makeKeyAndOrderFront(nil)
        }
    }
}

struct PopoverView: View {
    @EnvironmentObject var server: ServerController
    @EnvironmentObject var timer: TimerModel

    // Form state
    @State private var title: String = ""
    @State private var url: String = ""
    @State private var wordCountText: String = ""
    @State private var fetching: Bool = false
    @State private var saving: Bool = false
    @State private var saveError: String? = nil
    @State private var saveOK: Bool = false
    @State private var manualMinutes: String = "00"
    @State private var manualSeconds: String = "00"

    // Have-I-read-this state — driven directly by the URL field.
    @State private var urlReadStatus: URLReadStatus = .empty
    @State private var urlCheckTask: Task<Void, Never>? = nil

    // Settings sheet
    @State private var showSettings = false

    private enum URLReadStatus: Equatable {
        case empty                 // no URL typed yet
        case checking              // request in flight (or debouncing)
        case read(MatchEntry)      // best match — green tag
        case unread                // queried, no match — red tag
        case unavailable           // server not ready or check failed — hide tag
    }

    private var wordCount: Int {
        Int(wordCountText.trimmingCharacters(in: .whitespaces)) ?? 0
    }

    private var serverReady: Bool {
        server.status == .running || server.status == .adopted
    }

    private var canSave: Bool {
        // Time is intentionally NOT required — saving with elapsed=0 fires a
        // notification reminding the user to fill it in via the spreadsheet.
        !title.trimmingCharacters(in: .whitespaces).isEmpty
        && wordCount > 0
        && timer.state == .idle
        && serverReady
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            Divider()
            formSection
            Divider()
            timerSection
            saveRow
            if let err = saveError {
                Text(err).font(.caption).foregroundStyle(.red).lineLimit(3)
            }
            Divider()
            footer
        }
        .padding(14)
        .frame(width: 380)
        .background(ActivatePopoverWindow())
        .onAppear {
            NSApp.activate(ignoringOtherApps: true)
        }
        .sheet(isPresented: $showSettings) { SettingsView() }
    }

    // MARK: - Sections

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "books.vertical.fill")
            Text("Reading Tracker").font(.headline)
            Spacer()
            Circle().fill(statusColor).frame(width: 10, height: 10)
            Text(statusText).font(.caption).foregroundStyle(.secondary)
        }
    }

    private var formSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("Article title", text: $title)
                .textFieldStyle(.roundedBorder)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    TextField("URL (optional)", text: $url)
                        .textFieldStyle(.roundedBorder)
                        .onChange(of: url) { newValue in
                            scheduleURLCheck(newValue)
                        }
                    Button {
                        Task { await fetchWordCount() }
                    } label: {
                        if fetching {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("Fetch")
                        }
                    }
                    .help("Open the URL in your browser AND fetch the word count from the server")
                    .disabled(url.trimmingCharacters(in: .whitespaces).isEmpty || fetching || !serverReady)
                }
                urlStatusTag
                    .onChange(of: serverReady) { ready in
                        if ready { scheduleURLCheck(url) }
                    }
            }

            TextField("Word count", text: $wordCountText)
                .textFieldStyle(.roundedBorder)
                .onChange(of: wordCountText) { newValue in
                    let filtered = newValue.filter { $0.isNumber }
                    if filtered != newValue { wordCountText = filtered }
                }
        }
    }

    @ViewBuilder
    private var urlStatusTag: some View {
        switch urlReadStatus {
        case .empty, .unavailable:
            EmptyView()
        case .checking:
            HStack(spacing: 4) {
                ProgressView().controlSize(.small)
                Text("checking your log…")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        case .unread:
            ReadTag(label: "New — not in your log",
                    systemIcon: "circle.dotted",
                    color: .red)
        case .read(let m):
            let suffix: String = {
                let date = shortDate(m.date)
                let wpm = m.wpm.trimmingCharacters(in: .whitespaces)
                if !wpm.isEmpty {
                    return "\(date) · \(wpm) wpm"
                }
                return date
            }()
            ReadTag(label: "Read · \(suffix)",
                    systemIcon: "checkmark.circle.fill",
                    color: .green)
                .help(m.title.isEmpty ? m.url : m.title)
        }
    }

    private var timerSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(formatElapsed(timer.elapsedSeconds))
                    .font(.system(size: 28, weight: .semibold, design: .monospaced))
                Spacer()
                HStack(spacing: 6) {
                    Button("Start") { timer.start() }
                        .disabled(timer.state != .idle)
                    Button(timer.state == .paused ? "Resume" : "Pause") {
                        if timer.state == .running { timer.pause() }
                        else if timer.state == .paused { timer.resume() }
                    }
                    .disabled(timer.state == .idle)
                    Button("Stop") { _ = timer.stop() }
                        .disabled(timer.state == .idle)
                    Button("Reset") {
                        timer.reset()
                        manualMinutes = "00"
                        manualSeconds = "00"
                    }
                    .help("Clear the elapsed time (and any manually entered minutes / seconds)")
                    .disabled(timer.state == .idle && timer.elapsedSeconds == 0
                              && manualMinutes == "00" && manualSeconds == "00")
                }
            }

            // Manual time entry — separate Minutes and Seconds fields, both
            // defaulting to "00". Only enabled while the timer is idle so a
            // running session can't be silently overwritten.
            HStack(spacing: 6) {
                Text("Or set manually:")
                    .font(.caption).foregroundStyle(.secondary)
                TextField("00", text: $manualMinutes)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 44)
                    .multilineTextAlignment(.center)
                    .onChange(of: manualMinutes) { newValue in
                        let filtered = newValue.filter(\.isNumber)
                        let trimmed = String(filtered.prefix(4))   // up to 9999 min
                        if trimmed != newValue { manualMinutes = trimmed }
                    }
                Text("min").font(.caption).foregroundStyle(.secondary)
                TextField("00", text: $manualSeconds)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 44)
                    .multilineTextAlignment(.center)
                    .onChange(of: manualSeconds) { newValue in
                        let filtered = newValue.filter(\.isNumber)
                        var n = Int(filtered) ?? 0
                        if n > 59 { n = 59 }
                        let normalised = filtered.isEmpty ? "" : String(n)
                        if normalised != newValue { manualSeconds = normalised }
                    }
                Text("sec").font(.caption).foregroundStyle(.secondary)
                Button("Set") {
                    let m = Int(manualMinutes) ?? 0
                    let s = Int(manualSeconds) ?? 0
                    timer.setManual(seconds: m * 60 + s)
                }
                .disabled(timer.state != .idle)
                Spacer()
            }
            .disabled(timer.state != .idle)
        }
    }

    private var saveRow: some View {
        HStack {
            Button {
                Task { await save() }
            } label: {
                if saving {
                    ProgressView().controlSize(.small)
                } else {
                    Text("Save reading")
                }
            }
            .keyboardShortcut(.defaultAction)
            .disabled(!canSave || saving)

            if saveOK {
                Label("Saved", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                    .font(.caption)
            }
            Spacer()
            if timer.elapsedSeconds > 0, wordCount > 0 {
                let live = timer.wpm(words: wordCount)
                Text(String(format: "%.0f wpm", live))
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var footer: some View {
        HStack {
            Button("Open Spreadsheet") {
                APIClient.shared.openSpreadsheet()
            }
            Button("Settings…") { showSettings = true }
            Spacer()
            Button {
                relaunchApp()
            } label: {
                Label("Reload", systemImage: "arrow.clockwise")
            }
            .help("Quit and relaunch the app (kills the python child and spawns a fresh server)")
            Button("Quit") { NSApp.terminate(nil) }
        }
    }

    /// Restart the .app bundle: spawn a detached shell that waits for our PID
    /// to disappear (so the python child has been SIGTERM'd by
    /// `applicationShouldTerminate`) and then `open -n`s a fresh copy. The
    /// shell process is reparented to launchd when we die, so it survives our
    /// exit and reliably launches the replacement.
    private func relaunchApp() {
        let bundlePath = Bundle.main.bundlePath
        let myPID = ProcessInfo.processInfo.processIdentifier
        let script = """
        while kill -0 \(myPID) 2>/dev/null; do sleep 0.2; done
        sleep 0.5
        /usr/bin/open -n "\(bundlePath)"
        """
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/sh")
        task.arguments = ["-c", script]
        do {
            try task.run()
        } catch {
            // If we couldn't even spawn the relauncher, give up on restart
            // and fall back to a plain quit so the user isn't left wondering.
            NSApp.terminate(nil)
            return
        }
        NSApp.terminate(nil)
    }

    // MARK: - Status helpers

    private var statusColor: Color {
        switch server.status {
        case .running, .adopted: return .green
        case .starting: return .yellow
        case .stopped: return .gray
        case .failed: return .red
        }
    }

    private var statusText: String {
        switch server.status {
        case .running: return "running"
        case .adopted: return "adopted"
        case .starting: return "starting…"
        case .stopped: return "stopped"
        case .failed(let m): return m
        }
    }

    private func formatElapsed(_ s: Int) -> String {
        let h = s / 3600
        let m = (s % 3600) / 60
        let sec = s % 60
        if h > 0 { return String(format: "%d:%02d:%02d", h, m, sec) }
        return String(format: "%02d:%02d", m, sec)
    }

    /// Render a logged date for display in the URL "Read" tag.
    /// Handles both the new format ("DD-MMM-YYYY : HH:MM:SS") and any older
    /// ISO 8601 entries that may still live in the sheet.
    private func shortDate(_ raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespaces)
        // New backend format already reads naturally — return as-is.
        if trimmed.contains(" : ") {
            return trimmed
        }
        // Legacy ISO 8601 — clip to "YYYY-MM-DD HH:MM".
        if trimmed.count >= 16 {
            let idx = trimmed.index(trimmed.startIndex, offsetBy: 16)
            return String(trimmed[..<idx]).replacingOccurrences(of: "T", with: " ")
        }
        return trimmed
    }

    // MARK: - Actions

    private func fetchWordCount() async {
        let trimmed = url.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        fetching = true
        defer { fetching = false }
        saveError = nil

        // Open the link in the user's default browser, in parallel with the server fetch.
        APIClient.shared.openInBrowser(trimmed)

        do {
            let r = try await APIClient.shared.fetchWordCount(url: trimmed)
            wordCountText = String(r.word_count)
            if title.trimmingCharacters(in: .whitespaces).isEmpty, let t = r.title {
                title = t
            }
        } catch {
            saveError = "Word count fetch failed: \(error.localizedDescription)"
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        saveError = nil
        saveOK = false

        let words = wordCount
        let secs = timer.elapsedSeconds
        let wpmVal = timer.wpm(words: words)
        let savedTitle = title.trimmingCharacters(in: .whitespaces)

        let req = LogReadingRequest(
            title: savedTitle,
            url: url.trimmingCharacters(in: .whitespaces),
            word_count: words,
            time_seconds: secs,
            wpm: wpmVal
        )
        do {
            _ = try await APIClient.shared.logReading(req)
            saveOK = true
            // If the user saved without ever starting the timer, fire a system
            // notification with a deep link to the spreadsheet so they can fill
            // in the missing time.
            if secs == 0 {
                Task { await NotificationManager.shared.notifyMissingTime(title: savedTitle) }
            }
            // Reset form
            title = ""
            url = ""
            wordCountText = ""
            manualMinutes = "00"
            manualSeconds = "00"
            urlReadStatus = .empty
            timer.reset()
            // Auto-hide success badge
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            saveOK = false
        } catch {
            saveError = "Save failed: \(error.localizedDescription)"
        }
    }

    /// Debounced "have I read this URL?" check. Cancels any in-flight request,
    /// waits ~500 ms after the user stops typing, then queries the server and
    /// sets `urlReadStatus` so the inline tag updates.
    private func scheduleURLCheck(_ value: String) {
        urlCheckTask?.cancel()
        let trimmed = value.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty {
            urlReadStatus = .empty
            return
        }
        if !serverReady {
            urlReadStatus = .unavailable
            return
        }
        urlReadStatus = .checking
        urlCheckTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 500_000_000)
            if Task.isCancelled { return }
            // Snapshot the URL we are about to query — if it changes underneath
            // us, discard the result so a stale response can't overwrite a
            // newer one.
            let queried = trimmed
            do {
                let r = try await APIClient.shared.checkArticle(query: queried)
                if Task.isCancelled { return }
                if url.trimmingCharacters(in: .whitespaces) != queried { return }
                if let best = r.matches.first {
                    urlReadStatus = .read(best)
                } else {
                    urlReadStatus = .unread
                }
            } catch {
                if Task.isCancelled { return }
                if url.trimmingCharacters(in: .whitespaces) != queried { return }
                urlReadStatus = .unavailable
            }
        }
    }
}

/// Inline pill tag rendered next to the URL field.
private struct ReadTag: View {
    let label: String
    let systemIcon: String
    let color: Color

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: systemIcon)
            Text(label).lineLimit(1).truncationMode(.middle)
        }
        .font(.caption2)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(color.opacity(0.15))
        .foregroundStyle(color)
        .overlay(
            Capsule().stroke(color.opacity(0.45), lineWidth: 0.5)
        )
        .clipShape(Capsule())
    }
}

// MARK: - Settings sheet

private struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var settings = AppSettings.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Settings").font(.title2).bold()

            Form {
                TextField("Project root", text: $settings.projectRoot)
                TextField("Python path (blank = auto)", text: $settings.pythonPath)
                Stepper("Server port: \(settings.serverPort)",
                        value: $settings.serverPort, in: 1024...65535)
            }

            Text("Changes apply on next server restart.")
                .font(.caption).foregroundStyle(.secondary)

            HStack {
                Spacer()
                Button("Done") { dismiss() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 420)
    }
}
