import Foundation
import Security

/// Manages the shared key file at ~/.hort/statusbar.key
///
/// Both the Swift status bar and the Python openhort plugin read/write
/// this file. Whoever starts first creates it; either side rotates
/// when the key is older than 24 hours.
final class SharedKey {
    private let keyFile: URL
    private let maxAge: TimeInterval = 86400 // 24 hours

    private struct KeyData: Codable {
        let key: String
        let created: Double // Unix timestamp
    }

    init() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        keyFile = home.appendingPathComponent(".hort/statusbar.key")
    }

    /// Read the current key, rotating if missing or stale.
    func getOrRotate() -> String {
        if let data = try? Data(contentsOf: keyFile),
           let keyData = try? JSONDecoder().decode(KeyData.self, from: data) {
            let age = Date().timeIntervalSince1970 - keyData.created
            if age < maxAge && !keyData.key.isEmpty {
                return keyData.key
            }
        }
        return rotate()
    }

    private func rotate() -> String {
        // Generate 32 random bytes, base64url-encode (matches Python's token_urlsafe)
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        let key = Data(bytes).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")

        let keyData = KeyData(key: key, created: Date().timeIntervalSince1970)

        // Create directory
        let dir = keyFile.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        // Atomic write with 0600 permissions
        if let jsonData = try? JSONEncoder().encode(keyData) {
            try? jsonData.write(to: keyFile, options: [.atomic])
            chmod(keyFile.path, 0o600)
        }

        return key
    }
}
