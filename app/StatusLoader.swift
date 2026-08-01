import Cocoa
import Combine
import SwiftUI

class StatusLoader: ObservableObject {
    @Published var payload: StatusPayload?
    @Published var lastError: String?
    private var timer: Timer?
    // Serial queue for file I/O + JSON decode, off the main run loop.
    private let ioQueue = DispatchQueue(label: "com.tonye.tokenstatusbar.status-io")

    private let poolDir: String
    private let dataDir: String
    let statusURL: URL
    // Persistent local control server (opencodex-style): the app launches
    // `pool.py server` once and drives all add/reconnect/manage flows through
    // the browser panel it serves on this loopback port.
    private var serverProcess: Process?
    let serverPort: Int

    init() {
        let env = ProcessInfo.processInfo.environment
        let poolDir: String
        if let override = env["AGENT_POOL_DIR"], !override.isEmpty {
            poolDir = override
        } else {
            poolDir = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("solo/token-status-bar").path
        }
        self.poolDir = poolDir
        let dataDir = "\(poolDir)/secrets"
        self.dataDir = dataDir
        if let override = env["AGENT_POOL_SERVER_PORT"], let p = Int(override) {
            self.serverPort = p
        } else {
            self.serverPort = 7817
        }
        if let override = env["AGENT_POOL_STATUS_JSON"], !override.isEmpty {
            self.statusURL = URL(fileURLWithPath: override)
        } else {
            self.statusURL = URL(fileURLWithPath: dataDir).appendingPathComponent("status.json")
        }
    }

    func start() {
        reload()
        ensureServer()
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            self?.reload()
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        if let proc = serverProcess, proc.isRunning {
            proc.terminate()
        }
        serverProcess = nil
    }

    /// Start the local control server if it is not already running. The server
    /// binds 127.0.0.1:serverPort and serves the accounts panel + /api/oauth/*.
    /// Launch failure is non-fatal: the menu bar still reads status.json.
    func ensureServer() {
        if let proc = serverProcess, proc.isRunning { return }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            let proc = self.poolProcess(["server"])
            proc.terminationHandler = { [weak self] _ in
                self?.serverProcess = nil
            }
            do {
                try proc.run()
                self.serverProcess = proc
            } catch {
                NSLog("token-bar server failed to launch: \(error.localizedDescription)")
            }
        }
    }

    /// URL of the browser accounts panel.
    var panelURL: URL { URL(string: "http://127.0.0.1:\(serverPort)/")! }

    /// Ensure the server is up, then open the browser accounts panel. All
    /// add / reconnect / swap / remove happens there (opencodex parity).
    func openPanel() {
        ensureServer()
        let url = panelURL
        // Small delay on cold start so the first open lands after the bind.
        let delay: DispatchTimeInterval = serverProcess?.isRunning == true ? .milliseconds(0) : .milliseconds(600)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            NSWorkspace.shared.open(url)
        }
    }

    func reload() {
        ioQueue.async { [weak self] in
            guard let self else { return }
            guard FileManager.default.fileExists(atPath: self.statusURL.path) else {
                DispatchQueue.main.async {
                    self.lastError = "No status.json yet. Run: pool.py poll"
                }
                return
            }
            do {
                let data = try Data(contentsOf: self.statusURL)
                let decoded = try JSONDecoder().decode(StatusPayload.self, from: data)
                DispatchQueue.main.async {
                    self.payload = decoded
                    self.lastError = nil
                }
            } catch {
                // Keep the cached payload; surface the failure via statusWarning.
                DispatchQueue.main.async {
                    self.lastError = "Parse error: \(error.localizedDescription)"
                }
            }
        }
    }

    /// Parse a status.json timestamp (ISO8601, with or without timezone suffix).
    static func parseStatusDate(_ iso: String) -> Date? {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = parser.date(from: iso) { return d }
        parser.formatOptions = [.withInternetDateTime]
        if let d = parser.date(from: iso) { return d }
        // generated_at has no timezone suffix; parse as local time.
        let local = DateFormatter()
        local.locale = Locale(identifier: "en_US_POSIX")
        local.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        if let d = local.date(from: iso) { return d }
        local.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return local.date(from: iso)
    }

    /// Warning surfaced in the menu (and status-item title) when the last
    /// reload failed or the cached payload is older than 15 minutes.
    var statusWarning: String? {
        if let err = lastError { return err }
        guard let payload,
              let date = StatusLoader.parseStatusDate(payload.generated_at) else { return nil }
        let age = Date().timeIntervalSince(date)
        if age > 15 * 60 {
            return "status.json is stale (updated \(Int(age / 60))m ago)"
        }
        return nil
    }

    // ─── Bundled Python / backend paths ────────────────────────────────
    // The .app bundles a standalone Python and the backend scripts under
    // Contents/Resources so the app works without a system python3. In dev
    // mode (running the binary directly from build/), fall back to system
    // python3 and the repo's backend/ dir.

    private var bundledPython: String? {
        let p = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/python/bin/python3").path
        return FileManager.default.fileExists(atPath: p) ? p : nil
    }

    private var bundledPoolPy: String? {
        let p = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/backend/pool.py").path
        return FileManager.default.fileExists(atPath: p) ? p : nil
    }

    private var devPoolPy: String {
        "\(poolDir)/backend/pool.py"
    }

    /// Quote a string for safe use as a single word in a POSIX shell command.
    static func shellQuote(_ s: String) -> String {
        "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    /// Process configured to run `pool.py <args>` with data-path env vars set.
    func poolProcess(_ args: [String]) -> Process {
        var env = ProcessInfo.processInfo.environment
        if env["AGENT_POOL_DB"] == nil { env["AGENT_POOL_DB"] = "\(dataDir)/pool.db" }
        if env["AGENT_POOL_STATUS_JSON"] == nil { env["AGENT_POOL_STATUS_JSON"] = "\(dataDir)/status.json" }
        if env["AGENT_POOL_HISTORY_DIR"] == nil { env["AGENT_POOL_HISTORY_DIR"] = "\(poolDir)/history" }
        let p = Process()
        p.environment = env
        if let py = bundledPython, let pool = bundledPoolPy {
            p.launchPath = py
            p.arguments = [pool] + args
        } else {
            p.launchPath = "/usr/bin/env"
            p.arguments = ["python3", devPoolPy] + args
        }
        return p
    }

    /// Shell command string for running `pool.py <args>` (for Terminal-based flows).
    func poolShellCommand(_ args: [String]) -> String {
        let q = StatusLoader.shellQuote
        let envPrefix = "AGENT_POOL_DB=\(q("\(dataDir)/pool.db")) AGENT_POOL_STATUS_JSON=\(q("\(dataDir)/status.json")) AGENT_POOL_HISTORY_DIR=\(q("\(poolDir)/history"))"
        let quotedArgs = args.map(q).joined(separator: " ")
        if let py = bundledPython, let pool = bundledPoolPy {
            return "\(envPrefix) \(q(py)) \(q(pool)) \(quotedArgs)"
        } else {
            let dir = "\(poolDir)/backend"
            return "cd \(q(dir)) && \(envPrefix) python3 pool.py \(quotedArgs)"
        }
    }

    /// Run `pool.py <args>` synchronously, optionally writing `stdinText`
    /// (plus a newline) to the process's stdin. Returns true on exit code 0.
    /// Launch failures and non-zero exits are logged and surfaced via
    /// lastError. Must not be called on the main thread.
    @discardableResult
    private func runPool(_ args: [String], stdinText: String? = nil) -> Bool {
        let task = poolProcess(args)
        var stdinPipe: Pipe?
        if stdinText != nil {
            let pipe = Pipe()
            task.standardInput = pipe
            stdinPipe = pipe
        }
        do {
            try task.run()
        } catch {
            NSLog("pool.py \(args.first ?? "?") failed to launch: \(error.localizedDescription)")
            DispatchQueue.main.async {
                self.lastError = "Failed to launch backend: \(error.localizedDescription)"
            }
            return false
        }
        if let pipe = stdinPipe, let stdinText {
            pipe.fileHandleForWriting.write(Data((stdinText + "\n").utf8))
            pipe.fileHandleForWriting.closeFile()
        }
        task.waitUntilExit()
        if task.terminationStatus != 0 {
            NSLog("pool.py \(args.first ?? "?") exited with status \(task.terminationStatus)")
            return false
        }
        return true
    }

    func runPoll() {
        DispatchQueue.global(qos: .userInitiated).async {
            self.runPool(["poll"])
            self.reload()
        }
    }

    func runHeartbeat(accountId: Int? = nil) {
        DispatchQueue.global(qos: .userInitiated).async {
            var args = ["heartbeat"]
            if let id = accountId {
                args += ["--account", "\(id)"]
            }
            self.runPool(args)
            // heartbeat writes refresh_log only; export so the menu sees it.
            self.runPool(["export-status"])
            self.reload()
        }
    }

    func runDashboard() {
        DispatchQueue.global(qos: .userInitiated).async {
            // Regenerates history/dashboard.html fresh; the backend's --open
            // flag then opens it in the default browser.
            self.runPool(["dashboard", "--open"])
        }
    }

    func addAgent(provider: String) {
        // Devin needs an API key: prompt in-app, then pass it via stdin so
        // it never appears in the process argument list.
        if provider == "devin" {
            guard let apiKey = promptDevinApiKey(confirmTitle: L10n.tr("add_new_agent")) else { return }
            DispatchQueue.global(qos: .userInitiated).async {
                self.runPool(["add-devin"], stdinText: apiKey)
                self.reload()
            }
            return
        }
        // Copilot uses the GitHub device flow (paste a code): keep the Terminal
        // path — the browser panel drives loopback-callback OAuth only.
        if provider == "copilot" {
            runPoolInTerminal(["add", provider])
            return
        }
        // Every other provider is browser OAuth: hand off to the accounts panel.
        openPanel()
    }

    /// Manual "Swap to this account" (spec §3.2): rewrites ~/.codex/auth.json
    /// with this pool account's tokens via `pool.py swap`. --force because a
    /// user click is explicit intent; the backend still backs up the old
    /// auth.json, writes atomically, records the event, and notifies.
    func swapToAgent(_ acct: Account) {
        DispatchQueue.global(qos: .userInitiated).async {
            self.runPool(["swap", "--provider", acct.provider,
                          "--account-id", "\(acct.id)", "--force"])
            self.reload()
        }
    }

    func reconnectAgent(_ acct: Account) {
        if acct.provider == "devin" {
            reconnectDevinAgent(acct)
            return
        }
        if acct.provider == "copilot" {
            runPoolInTerminal(["reconnect", "\(acct.id)"])
            return
        }
        // Browser OAuth providers reconnect through the accounts panel, which
        // deep-reauths the exact account via /api/oauth/login?account_id=…
        openPanel()
    }

    /// Modal secure-field prompt for a Devin API key. Returns nil on cancel/empty.
    private func promptDevinApiKey(confirmTitle: String) -> String? {
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = L10n.tr("devin_api_key_title")
        alert.informativeText = L10n.tr("devin_api_key_message")
        alert.addButton(withTitle: confirmTitle)
        alert.addButton(withTitle: L10n.tr("cancel"))
        let input = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 24))
        input.placeholderString = "API key"
        alert.accessoryView = input
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        let apiKey = input.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        return apiKey.isEmpty ? nil : apiKey
    }

    private func reconnectDevinAgent(_ acct: Account) {
        guard let apiKey = promptDevinApiKey(confirmTitle: L10n.tr("reconnect_agent")) else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            // Key goes over stdin, not argv, so it never shows up in `ps`.
            self.runPool(["reconnect", "\(acct.id)"], stdinText: apiKey)
            self.reload()
        }
    }

    private func runPoolInTerminal(_ args: [String]) {
        let cmd = poolShellCommand(args)
        // Escape for embedding in an AppleScript string literal.
        let escapedCmd = cmd
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        let script = """
        tell application "Terminal"
            activate
            do script "\(escapedCmd)"
        end tell
        """
        let task = Process()
        task.launchPath = "/usr/bin/osascript"
        task.arguments = ["-e", script]
        do {
            try task.run()
        } catch {
            NSLog("osascript launch failed: \(error.localizedDescription)")
            DispatchQueue.main.async {
                self.lastError = "Failed to open Terminal: \(error.localizedDescription)"
            }
        }
    }

    func deleteAgent(accountId: Int) {
        DispatchQueue.global(qos: .userInitiated).async {
            self.runPool(["remove", "\(accountId)"])
            self.reload()
        }
    }

    func confirmDeleteAgent(acct: Account) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = L10n.tr("delete_agent")
        let name = acct.email ?? acct.label ?? "account #\(acct.id)"
        alert.informativeText = String(format: L10n.tr("delete_agent_confirm"), name)
        alert.addButton(withTitle: L10n.tr("delete_agent"))
        alert.addButton(withTitle: L10n.tr("cancel"))
        if alert.runModal() == .alertFirstButtonReturn {
            deleteAgent(accountId: acct.id)
        }
    }
}
