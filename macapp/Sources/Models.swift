import Foundation

struct LogReadingRequest: Codable {
    let title: String
    let url: String
    let word_count: Int
    let time_seconds: Int
    let wpm: Double
}

struct LogReadingResponse: Codable {
    let row: Int
    let date: String
}

struct CheckResponse: Codable {
    let found: Bool
    let matches: [MatchEntry]
}

struct MatchEntry: Codable, Identifiable, Equatable {
    var id: Int { row }
    let row: Int
    let title: String
    let url: String
    let date: String
    let wpm: String
    let word_count: String
    let time_seconds: String
    let score: Double
}

struct WordCountRequest: Codable {
    let url: String
}

struct WordCountResponse: Codable {
    let url: String
    let word_count: Int
    let title: String?
}
