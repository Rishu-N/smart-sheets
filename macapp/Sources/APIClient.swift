import Foundation
import AppKit

enum APIError: Error, LocalizedError {
    case http(Int, String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .http(let code, let body):
            let snippet = body.prefix(200)
            return "HTTP \(code): \(snippet)"
        case .decoding(let msg):
            return "Decoding error: \(msg)"
        }
    }
}

final class APIClient {
    static let shared = APIClient()

    private var base: URL { AppSettings.shared.baseURL }

    func logReading(_ req: LogReadingRequest) async throws -> LogReadingResponse {
        try await post("/api/reading/log", body: req)
    }

    func checkArticle(query: String) async throws -> CheckResponse {
        var comps = URLComponents(
            url: base.appendingPathComponent("/api/reading/check"),
            resolvingAgainstBaseURL: false
        )!
        comps.queryItems = [URLQueryItem(name: "query", value: query)]
        var req = URLRequest(url: comps.url!)
        req.httpMethod = "GET"
        return try await send(req)
    }

    func fetchWordCount(url: String) async throws -> WordCountResponse {
        try await post("/api/reading/wordcount", body: WordCountRequest(url: url))
    }

    /// Public accessor for the spreadsheet's URL (used by notifications etc.).
    var spreadsheetURL: URL { base }

    func openSpreadsheet() {
        NSWorkspace.shared.open(base)
    }

    func openInBrowser(_ urlString: String) {
        guard let u = URL(string: urlString) else { return }
        NSWorkspace.shared.open(u)
    }

    // MARK: - Private

    private func post<B: Encodable, R: Decodable>(_ path: String, body: B) async throws -> R {
        var req = URLRequest(url: base.appendingPathComponent(path))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder().encode(body)
        return try await send(req)
    }

    private func send<R: Decodable>(_ req: URLRequest) async throws -> R {
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse else {
            throw APIError.http(-1, "no HTTP response")
        }
        if http.statusCode >= 400 {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw APIError.http(http.statusCode, body)
        }
        do {
            return try JSONDecoder().decode(R.self, from: data)
        } catch {
            throw APIError.decoding("\(error)")
        }
    }
}
