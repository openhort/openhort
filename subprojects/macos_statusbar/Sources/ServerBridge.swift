import Foundation

/// Snapshot of the openhort server state.
struct ServerStatus {
    var running = false
    var observers = 0
    var version = ""
    var httpURL = ""
    var authenticated = false
}

/// Polls the openhort server on localhost and tracks its status.
///
/// No server management -- the bridge is a pure observer. It polls
/// GET /api/hash every 3 seconds and sends the X-Hort-Key header
/// from the shared key file.
final class ServerBridge {
    var onStatusChange: ((ServerStatus) -> Void)?

    private(set) var status = ServerStatus()
    private var timer: Timer?
    private let sharedKey: SharedKey
    private var handshakeDone = false

    private let httpPort = 8940
    private let pollInterval: TimeInterval = 3.0

    init(sharedKey: SharedKey) {
        self.sharedKey = sharedKey
    }

    var isRunning: Bool { status.running }

    func startPolling() {
        // Poll immediately, then on interval
        pollOnce()
        timer = Timer.scheduledTimer(withTimeInterval: pollInterval, repeats: true) { [weak self] _ in
            self?.pollOnce()
        }
    }

    func stopPolling() {
        timer?.invalidate()
        timer = nil
    }

    private func pollOnce() {
        guard let url = URL(string: "http://localhost:\(httpPort)/api/hash") else { return }
        var request = URLRequest(url: url, timeoutInterval: 5)
        request.setValue(sharedKey.getOrRotate(), forHTTPHeaderField: "X-Hort-Key")

        URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            guard let self = self else { return }
            let oldRunning = self.status.running
            let oldObservers = self.status.observers

            if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                self.status.running = true
                self.status.httpURL = "http://localhost:\(self.httpPort)"

                // Parse observer count from JSON response
                if let data = data,
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let obs = json["observers"] as? Int {
                    self.status.observers = obs
                }

                if !self.handshakeDone {
                    self.doHandshake()
                }
            } else {
                self.status.running = false
                self.status.observers = 0
            }

            if oldRunning != self.status.running || oldObservers != self.status.observers {
                let s = self.status
                DispatchQueue.main.async {
                    self.onStatusChange?(s)
                }
            }
        }.resume()
    }

    private func doHandshake() {
        guard let url = URL(string: "http://localhost:\(httpPort)/api/llmings/macos-statusbar/verify") else { return }
        var request = URLRequest(url: url, timeoutInterval: 5)
        request.httpMethod = "POST"
        request.setValue(sharedKey.getOrRotate(), forHTTPHeaderField: "X-Hort-Key")

        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                self?.handshakeDone = true
                self?.status.authenticated = true
            }
        }.resume()
    }
}
