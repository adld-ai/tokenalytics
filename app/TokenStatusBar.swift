import Cocoa
import Combine
import SwiftUI

// ─── Models ───────────────────────────────────────────────────────────────

// ─── Status Loader ────────────────────────────────────────────────────────

// ─── Menu Row Design (ported from codex-status-bar) ───────────────────────

// ─── Language Mode ─────────────────────────────────────────────────────────


// ─── Dropdown layout experiment (spec §2.1) ────────────────────────────────

// ─── Menu Bar App ─────────────────────────────────────────────────────────
@main
struct TokenStatusBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        Settings {
            EmptyView()
        }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem!
    var loader = StatusLoader()
    var popover: NSPopover!
    var language: Language = .en
    var menuLayout: MenuLayout = .classic
    // 1s ticker: keeps LIMITED-section reset countdowns ticking while the
    // menu is open (usable-first layout only). Section moves happen on the
    // next menu open (menuNeedsUpdate re-derives phase client-side).
    private var menuTicker: Timer?
    private var limitedRows: [(row: FixedMenuRowView, account: Account)] = []
    private var cancellables = Set<AnyCancellable>()

    func applicationDidFinishLaunching(_ notification: Notification) {
        language = Language.current
        L10n.lang = language
        menuLayout = MenuLayout.current
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        updateStatusIcon()

        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu

        loader.$payload
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.updateStatusIcon() }
            .store(in: &cancellables)

        loader.$lastError
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.updateStatusIcon() }
            .store(in: &cancellables)

        loader.start()

        NSApp.setActivationPolicy(.accessory)
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopMenuTicker()
        loader.stop()
    }

    private func windowRiskColor(pct: Double, severity: String?, projected: Bool) -> NSColor {
        if projected || pct > 80 || (severity ?? "normal") != "normal" { return .systemRed }
        if pct >= 50 { return .systemYellow }
        return .systemGreen
    }

    static func timeLeft(_ epoch: Double?) -> String? {
        guard let epoch else { return nil }
        let s = Int(epoch - Date().timeIntervalSince1970)
        if s <= 0 { return nil }
        if s < 3600 { return "\(s / 60)m" }
        if s < 86400 { return "\(s / 3600)h\((s % 3600) / 60)m" }
        return String(format: "%.1fd", Double(s) / 86400.0)
    }

    private func headlineTitle() -> NSAttributedString? {
        let warn = loader.statusWarning != nil
        guard let h = loader.payload?.headline else {
            guard warn else { return nil }
            return NSAttributedString(string: " ⚠︎", attributes: [
                .font: NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium),
                .foregroundColor: NSColor.systemOrange,
                .baselineOffset: 0.5,
            ])
        }
        var text = " \(Int(h.used_pct.rounded()))%"
        if let left = AppDelegate.timeLeft(h.reset_at_epoch) { text += " · \(left)" }
        if warn { text += " ⚠︎" }
        let color = warn ? NSColor.systemOrange
            : windowRiskColor(pct: h.used_pct, severity: h.severity, projected: false)
        return NSAttributedString(string: text, attributes: [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium),
            .foregroundColor: color,
            .baselineOffset: 0.5,
        ])
    }

    /// Pool-wide health shown as the icon's corner dot.
    private func poolDotColor() -> NSColor {
        guard let payload = loader.payload else { return .systemOrange }
        if (payload.heartbeat?.failed ?? 0) > 0
            || payload.accounts.contains(where: { $0.status == "error" || $0.heartbeat_status == "fail" }) {
            return .systemRed
        }
        if payload.accounts.contains(where: { $0.status == "expired" }) {
            return .systemOrange
        }
        return .systemGreen
    }

    private func updateStatusIcon() {
        guard let button = statusItem.button else { return }
        guard let symbol = NSImage(systemSymbolName: "chart.bar.fill", accessibilityDescription: "Agent Pool")?
            .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 13, weight: .regular)) else {
            button.title = "AP"
            return
        }
        let dotColor = poolDotColor()
        let size = NSSize(width: 18, height: 18)
        let image = NSImage(size: size, flipped: false) { rect in
            let symbolRect = NSRect(x: (rect.width - symbol.size.width) / 2,
                                    y: (rect.height - symbol.size.height) / 2,
                                    width: symbol.size.width,
                                    height: symbol.size.height)
            symbol.draw(in: symbolRect)
            NSColor.labelColor.set()
            symbolRect.fill(using: .sourceAtop)

            let dotRect = NSRect(x: rect.maxX - 7, y: 0, width: 7, height: 7)
            if let ctx = NSGraphicsContext.current {
                // Punch a gap around the dot so it reads against the bars.
                ctx.compositingOperation = .destinationOut
                NSBezierPath(ovalIn: dotRect.insetBy(dx: -1.5, dy: -1.5)).fill()
                ctx.compositingOperation = .sourceOver
            }
            dotColor.setFill()
            NSBezierPath(ovalIn: dotRect).fill()
            return true
        }
        image.isTemplate = false
        image.accessibilityDescription = "Agent Pool"
        button.image = image
        if let title = headlineTitle() {
            button.attributedTitle = title
            button.imagePosition = .imageLeft
        } else {
            button.attributedTitle = NSAttributedString(string: "")
            button.imagePosition = .imageOnly
        }
    }

    @objc func quitApp() {
        NSApp.terminate(nil)
    }
}

extension AppDelegate: NSMenuDelegate {
    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        buildMenu(menu)
    }

    func menuWillOpen(_ menu: NSMenu) {
        guard menu === statusItem.menu, menuLayout == .usableFirst else { return }
        startMenuTicker()
    }

    func menuDidClose(_ menu: NSMenu) {
        guard menu === statusItem.menu else { return }
        stopMenuTicker()
    }

    func buildMenu(_ menu: NSMenu) {
        limitedRows = []
        guard let payload = loader.payload else {
            menu.addItem(headerItem(t("loading")))
            if let err = loader.lastError {
                menu.addItem(separatorRow())
                menu.addItem(infoItem(err))
            }
            menu.addItem(separatorRow())
            addFooter(menu)
            return
        }

        // Layout experiment (spec §2.1): usable-first restructures the list
        // around "what can I use right now"; classic stays untouched below.
        if menuLayout == .usableFirst {
            buildUsableFirstMenu(menu, payload: payload)
            return
        }

        // Header
        if let warning = loader.statusWarning {
            menu.addItem(warningItem("⚠︎ \(warning)"))
            menu.addItem(separatorRow())
        }
        menu.addItem(titleItem("Agent Pool: \(payload.account_count) accounts"))
        menu.addItem(infoItem("\(t("updated")): \(formatUpdated(payload.generated_at))"))
        if let heartbeat = payload.heartbeat {
            menu.addItem(heartbeatItem(heartbeat, accounts: payload.accounts))
        }
        menu.addItem(separatorRow())

        // Group by provider: the known order first, then anything the app has
        // no opinion about, so a backend adapter for a new provider shows up
        // here without waiting on an app release.
        let providerOrder = ["codex", "claude", "xai", "antigravity", "copilot", "cursor", "devin", "droid", "opencode"]
        let grouped = Dictionary(grouping: payload.accounts, by: { $0.provider })
        let unknown = grouped.keys.filter { !providerOrder.contains($0) }.sorted()
        for provider in providerOrder + unknown {
            guard let accts = grouped[provider] else { continue }
            menu.addItem(headerItem(providerDisplayName(provider)))
            for acct in accts {
                menu.addItem(accountItem(acct))
            }
            menu.addItem(separatorRow())
        }

        addLiveActivityRow(menu, payload: payload)

        addFooter(menu)
    }

    /// Live ticker row: freshest local session activity across accounts.
    /// Shared by both layouts (unchanged from classic).
    private func addLiveActivityRow(_ menu: NSMenu, payload: StatusPayload) {
        let fresh = payload.accounts.compactMap { a -> (Account, LiveActivity, Double)? in
            guard let live = a.live, let ts = live.as_of_epoch ?? live.event_epoch,
                  Date().timeIntervalSince1970 - ts < 600 else { return nil }
            return (a, live, ts)
        }.max(by: { $0.2 < $1.2 })
        if let (acct, live, _) = fresh {
            var parts: [String] = [providerDisplayName(acct.provider)]
            if let tokens = live.last_total_tokens {
                parts.append("+\(tokens.formatted()) tok")
            }
            if let ctx = live.context_used_pct {
                parts.append("context \(Int(ctx.rounded()))%")
            }
            if let t60 = live.tokens_60m, live.last_total_tokens == nil {
                parts.append("\(t60.formatted()) tok/60m")
            }
            menu.addItem(infoItem("⚡︎ " + parts.joined(separator: " · ")))
            menu.addItem(separatorRow())
        }
    }

    // ─── usable-first layout (spec §2.2) ─────────────────────────────────

    enum AccountSection {
        case useNow, limited, blocked, other
    }

    /// Effective per-window used% with the client-side phase rule applied:
    /// a window whose reset_at_epoch has already passed counts as reset
    /// (0% used) without waiting for the next poll (spec §1.3 / §2.2).
    func windowEffectivePct(_ w: WindowInfo, now: Double) -> Double? {
        if w.phase == "reset" { return 0 }
        if let reset = w.reset_at_epoch, reset < now { return 0 }
        return w.used_pct_effective ?? w.used_pct
    }

    /// Client-side section assignment from the exported `state`, re-deriving
    /// window phase at `now` so a countdown hitting 0 moves the account to
    /// USE NOW on the next rebuild without waiting for the next poll.
    func effectiveSection(_ acct: Account, now: Double) -> AccountSection {
        guard let state = acct.state else { return .other }
        if (state.auth ?? "ok") != "ok" || state.subscription == "expired" {
            return .blocked
        }
        var quota = state.quota ?? "unknown"
        if quota == "exhausted" {
            // Phase flip: exhaustion requires every live window at 100%, so
            // once any live window's reset time passes the account recovers.
            let live = (acct.windows ?? []).filter { $0.stale != true && $0.phase != "reset" }
            if live.contains(where: { ($0.reset_at_epoch ?? .infinity) < now }) {
                quota = "ok"
            }
        }
        switch quota {
        case "exhausted": return .limited
        case "unknown": return .other
        default: return .useNow // ok and warning are both usable
        }
    }

    private func windowKindLabel(_ w: WindowInfo) -> String {
        if w.kind == "model_weekly" { return w.label ?? "model" }
        if w.kind == "monthly", let label = w.label { return label }
        return w.kind
    }

    /// "weekly 78% left" from the account's binding window.
    private func bindingSummary(_ acct: Account, now: Double) -> String? {
        guard let w = acct.state?.binding_window,
              let pct = windowEffectivePct(w, now: now) else { return nil }
        let left = max(0, 100 - Int(pct.rounded()))
        return "\(windowKindLabel(w)) \(left)% \(t("pct_left"))"
    }

    /// "5h 0% left · resets in 42m" — why the account is cooling down.
    private func limitedReason(_ acct: Account, now: Double) -> String {
        let windows = (acct.windows ?? []).filter { $0.stale != true }
        let exhausted = windows.filter { w in
            let sev = (w.severity ?? "normal").lowercased()
            return (windowEffectivePct(w, now: now) ?? 0) >= 100
                || sev == "rate_limited" || sev == "exceeded"
        }
        let nextReset = exhausted.compactMap { $0.reset_at_epoch }.filter { $0 > now }.min()
        guard let nextReset else { return t("quota_exhausted") }
        let kind = exhausted.first(where: { $0.reset_at_epoch == nextReset }).map(windowKindLabel)
        var text = kind.map { "\($0) 0% \(t("pct_left"))" } ?? t("quota_exhausted")
        if let left = AppDelegate.timeLeft(nextReset) {
            text += " · " + String(format: t("resets_in"), left)
        }
        return text
    }

    /// Full row title for a LIMITED account; recomputed by the 1s ticker so
    /// the countdown ticks while the menu is open. When the countdown hits 0
    /// (phase flips client-side) it says so in place; the row moves to
    /// USE NOW on the next rebuild.
    private func limitedRowTitle(_ acct: Account, now: Double) -> String {
        let base = "\(providerDisplayName(acct.provider)) · \(accountTitle(acct))"
        if effectiveSection(acct, now: now) != .limited {
            return "\(base) · \(t("usable_now"))"
        }
        return "\(base) · \(limitedReason(acct, now: now))"
    }

    /// Exact reason a BLOCKED account can't be used.
    private func blockedReason(_ acct: Account) -> String {
        guard let state = acct.state else { return t("no_details") }
        switch state.auth ?? "ok" {
        case "token_expired":
            return t("token_expired_reconnect")
        case "error":
            let msg = acct.status_message ?? ""
            return msg.isEmpty ? t("error_prefix") : "\(t("error_prefix")): \(msg)"
        default:
            break
        }
        if state.subscription == "expired" {
            return String(format: t("sub_expired_on"), shortMonthDay(state.sub_expires_at) ?? "?")
        }
        return t("no_details")
    }

    func buildUsableFirstMenu(_ menu: NSMenu, payload: StatusPayload) {
        let now = Date().timeIntervalSince1970

        if let warning = loader.statusWarning {
            menu.addItem(warningItem("⚠︎ \(warning)"))
            menu.addItem(separatorRow())
        }

        var useNow: [Account] = []
        var limited: [Account] = []
        var blocked: [Account] = []
        var other: [Account] = []
        for acct in payload.accounts {
            switch effectiveSection(acct, now: now) {
            case .useNow: useNow.append(acct)
            case .limited: limited.append(acct)
            case .blocked: blocked.append(acct)
            case .other: other.append(acct)
            }
        }

        // Header
        menu.addItem(titleItem(
            "Agent Pool: \(payload.account_count) accounts · \(useNow.count) \(t("usable_count"))"))
        menu.addItem(infoItem("\(t("updated")): \(formatUpdated(payload.generated_at))"))
        if let heartbeat = payload.heartbeat {
            menu.addItem(heartbeatItem(heartbeat, accounts: payload.accounts))
        }
        menu.addItem(separatorRow())

        // USE NOW: best-headroom account first within each provider.
        let providerOrder = ["codex", "claude", "xai", "antigravity", "copilot", "cursor", "devin", "droid", "opencode"]
        func providerRank(_ p: String) -> Int { providerOrder.firstIndex(of: p) ?? providerOrder.count }
        func headroom(_ a: Account) -> Double {
            guard let w = a.state?.binding_window,
                  let pct = windowEffectivePct(w, now: now) else { return 100 }
            return 100 - pct
        }
        useNow.sort { a, b in
            if providerRank(a.provider) != providerRank(b.provider) {
                return providerRank(a.provider) < providerRank(b.provider)
            }
            return headroom(a) > headroom(b)
        }

        if !useNow.isEmpty {
            menu.addItem(headerItem(t("use_now_header")))
            for acct in useNow {
                var title = "\(providerDisplayName(acct.provider)) · \(accountTitle(acct))"
                if let summary = bindingSummary(acct, now: now) { title += " · \(summary)" }
                menu.addItem(accountItem(acct, titleOverride: title, dotColorOverride: .systemGreen))
            }
            menu.addItem(separatorRow())
        }

        // LIMITED / COOLING DOWN: strictly quota-exhausted (auth ok, sub fine).
        if !limited.isEmpty {
            menu.addItem(headerItem(t("limited_header")))
            for acct in limited {
                let item = accountItem(acct, titleOverride: limitedRowTitle(acct, now: now),
                                       dotColorOverride: .systemYellow)
                if let container = item.view as? AccountRowWithGauges {
                    limitedRows.append((row: container.rowView, account: acct))
                }
                menu.addItem(item)
            }
            menu.addItem(separatorRow())
        }

        // BLOCKED: auth or subscription problem.
        if !blocked.isEmpty {
            menu.addItem(headerItem(t("blocked_header")))
            for acct in blocked {
                let title = "\(providerDisplayName(acct.provider)) · \(accountTitle(acct)) · \(blockedReason(acct))"
                menu.addItem(accountItem(acct, titleOverride: title,
                                         dotColorOverride: .systemGray, hollowDot: true))
            }
            menu.addItem(separatorRow())
        }

        // OTHER: no exported state (older status.json) or unknown quota —
        // rendered as plain classic-style rows in a trailing group.
        if !other.isEmpty {
            menu.addItem(headerItem(t("other_header")))
            for acct in other {
                menu.addItem(accountItem(acct))
            }
            menu.addItem(separatorRow())
        }

        // Last auto-swap event (hidden placeholder until M4 exports it).
        if let swapRow = lastSwapItem(payload) {
            menu.addItem(swapRow)
            menu.addItem(separatorRow())
        }

        addLiveActivityRow(menu, payload: payload)
        addFooter(menu)
    }

    /// "⇄ auto-swap: Codex → codex-2 at 16:41". Returns nil until the M4
    /// swap engine starts exporting `last_swap` in status.json.
    func lastSwapItem(_ payload: StatusPayload) -> NSMenuItem? {
        guard let swap = payload.last_swap else { return nil }
        var text = "⇄ auto-swap: " + (swap.provider.map(providerDisplayName) ?? "?")
        if let to = swap.to { text += " → \(to)" }
        var when: Date?
        if let epoch = swap.at_epoch {
            when = Date(timeIntervalSince1970: epoch)
        } else if let at = swap.at {
            when = StatusLoader.parseStatusDate(at)
        }
        if let when {
            let out = DateFormatter()
            out.locale = Locale(identifier: "en_US_POSIX")
            out.dateFormat = "HH:mm"
            text += " at \(out.string(from: when))"
        }
        return infoItem(text)
    }

    // ─── 1s menu ticker (usable-first countdowns) ────────────────────────

    private func startMenuTicker() {
        stopMenuTicker()
        let ticker = Timer(timeInterval: 1, repeats: true) { [weak self] _ in
            self?.tickCountdowns()
        }
        // Menu tracking runs in the event-tracking run-loop mode; register
        // for both so countdowns keep ticking while the menu is open.
        RunLoop.main.add(ticker, forMode: .common)
        RunLoop.main.add(ticker, forMode: .eventTracking)
        menuTicker = ticker
    }

    func stopMenuTicker() {
        menuTicker?.invalidate()
        menuTicker = nil
    }

    private func tickCountdowns() {
        let now = Date().timeIntervalSince1970
        for (row, acct) in limitedRows {
            row.updateTitle(limitedRowTitle(acct, now: now))
        }
    }

    private func statusColor(_ status: String) -> NSColor {
        switch status {
        case "active": return .systemGreen
        case "error": return .systemRed
        case "expired": return .systemYellow
        default: return .tertiaryLabelColor
        }
    }

    private func heartbeatColor(_ status: String) -> NSColor {
        switch status {
        case "success": return .systemGreen
        case "fail": return .systemRed
        default: return .systemYellow
        }
    }

    private func heartbeatStatusText(_ status: String?) -> String {
        switch status {
        case "success": return t("heartbeat_success")
        case "fail": return t("heartbeat_fail")
        default: return t("heartbeat_unknown")
        }
    }

    private func heartbeatLine(status: String?, next: String?) -> String {
        "\(t("heartbeat")): \(heartbeatStatusText(status)) · \(t("heartbeat_next")) \(next ?? "?")"
    }

    func heartbeatItem(_ heartbeat: HeartbeatSummary, accounts: [Account]) -> NSMenuItem {
        let submenu = NSMenu()
        let width: CGFloat = 360
        let heartbeatAccounts = accounts.filter { ["codex", "claude", "antigravity"].contains($0.provider) }
        for acct in heartbeatAccounts {
            let name = acct.email ?? acct.label ?? "account #\(acct.id)"
            submenu.addItem(infoItem("\(providerDisplayName(acct.provider)): \(name)", width: width))
            submenu.addItem(infoItem(heartbeatLine(status: acct.heartbeat_status, next: acct.heartbeat_next),
                                     width: width))
            if let last = acct.heartbeat_last {
                submenu.addItem(infoItem("\(t("heartbeat_last")): \(last)", width: width))
            }
            if let lastOk = acct.heartbeat_last_success {
                submenu.addItem(infoItem("\(t("heartbeat_last_success")): \(lastOk)", width: width))
            }
            if let msg = acct.heartbeat_message, !msg.isEmpty {
                submenu.addItem(infoItem(msg, width: width))
            }
            submenu.addItem(separatorRow(width: width))
        }
        submenu.addItem(actionItem(t("run_heartbeat_now"), width: width) { [weak self] in
            self?.loader.runHeartbeat()
        })
        let failed = heartbeat.failed ?? 0
        let count = heartbeat.accounts ?? heartbeatAccounts.count
        let suffix = failed > 0 ? " · \(failed)/\(count) failed" : " · \(count) accounts"
        return submenuRow(heartbeatLine(status: heartbeat.status, next: heartbeat.next) + suffix,
                          submenu: submenu,
                          dotColor: heartbeatColor(heartbeat.status))
    }

    private func addHeartbeatStatus(_ submenu: NSMenu, acct: Account, width: CGFloat) {
        guard acct.heartbeat_status != nil || acct.heartbeat_next != nil || acct.heartbeat_last != nil else { return }
        submenu.addItem(groupHeaderItem(t("heartbeat"), width: width))
        submenu.addItem(infoItem(heartbeatLine(status: acct.heartbeat_status, next: acct.heartbeat_next), width: width))
        if let last = acct.heartbeat_last {
            submenu.addItem(infoItem("\(t("heartbeat_last")): \(last)", width: width))
        }
        if let lastOk = acct.heartbeat_last_success {
            submenu.addItem(infoItem("\(t("heartbeat_last_success")): \(lastOk)", width: width))
        }
        if let msg = acct.heartbeat_message, !msg.isEmpty {
            submenu.addItem(infoItem(msg, width: width))
        }
        submenu.addItem(actionItem(t("run_heartbeat_now"), width: width) { [weak self] in
            self?.loader.runHeartbeat(accountId: acct.id)
        })
    }

    /// Display name used for account rows in both layouts.
    func accountTitle(_ acct: Account) -> String {
        var title = acct.email ?? acct.label ?? "unknown"
        if acct.provider == "copilot", let mail = acct.github_email, !mail.isEmpty {
            title = "\(acct.email ?? acct.label ?? "unknown") (\(mail))"
        }
        return title
    }

    func accountItem(_ acct: Account, titleOverride: String? = nil,
                     dotColorOverride: NSColor? = nil, hollowDot: Bool = false) -> NSMenuItem {
        let title = titleOverride ?? accountTitle(acct)
        let submenu = NSMenu()
        let detailWidth: CGFloat = 420
        if acct.provider == "codex" {
            buildCodexSubmenu(submenu, acct: acct, width: detailWidth)
        } else if acct.provider == "claude" {
            buildClaudeSubmenu(submenu, acct: acct, width: detailWidth)
        } else if acct.provider == "xai" {
            buildGrokSubmenu(submenu, acct: acct, width: detailWidth)
        } else if acct.provider == "antigravity" {
            buildAntigravitySubmenu(submenu, acct: acct, width: detailWidth)
        } else if acct.provider == "copilot" {
            buildCopilotSubmenu(submenu, acct: acct, width: detailWidth)
        } else if acct.provider == "devin" {
            buildDevinSubmenu(submenu, acct: acct, width: detailWidth)
        } else {
            for line in detailLines(acct) {
                submenu.addItem(infoItem(line, width: detailWidth))
            }
        }
        for w in acct.windows ?? [] {
            guard let exhaust = w.projected_exhaust_epoch,
                  let left = AppDelegate.timeLeft(exhaust) else { continue }
            let name = w.kind == "model_weekly" ? (w.label ?? "model") : w.kind
            submenu.addItem(warningItem("⚠︎ \(name): exhausts in ~\(left) at current pace",
                                        width: detailWidth))
        }
        submenu.addItem(separatorRow(width: detailWidth))
        addHeartbeatStatus(submenu, acct: acct, width: detailWidth)
        if acct.heartbeat_status != nil || acct.heartbeat_next != nil || acct.heartbeat_last != nil {
            submenu.addItem(separatorRow(width: detailWidth))
        }
        // Manual same-provider swap (codex only, spec §3.2) — offered only
        // when this account could actually take over (usable == true).
        if acct.provider == "codex", acct.state?.usable == true {
            submenu.addItem(actionItem(t("swap_to_agent"), width: detailWidth) { [weak self] in
                self?.loader.swapToAgent(acct)
            })
        }
        submenu.addItem(actionItem(t("reconnect_agent"), width: detailWidth) { [weak self] in
            self?.loader.reconnectAgent(acct)
        })
        submenu.addItem(actionItem(t("delete_agent"), width: detailWidth, destructive: true) { [weak self] in
            self?.loader.confirmDeleteAgent(acct: acct)
        })
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.submenu = submenu
        let row = FixedMenuRowView(title: title, style: .submenu, submenu: submenu,
                                   dotColor: dotColorOverride ?? statusColor(acct.status),
                                   hollowDot: hollowDot, badge: endSoonBadge(acct))
        let gauges = (acct.windows ?? []).prefix(3).map { w in
            GaugeRowView(window: w,
                         color: windowRiskColor(pct: w.used_pct ?? 0,
                                                severity: w.severity,
                                                projected: w.projected_exhaust_epoch != nil),
                         width: MenuRowLayout.width)
        }
        item.view = AccountRowWithGauges(row: row, gauges: Array(gauges),
                                         width: MenuRowLayout.width)
        return item
    }

    func normalizePlan(_ acct: Account) -> String? {
        let raw = (acct.plan ?? "").lowercased()
        let tier = (acct.rate_limit_tier ?? "").lowercased()
        let override = (acct.tier_override ?? "").lowercased()
        switch acct.provider {
        case "codex":
            if raw.contains("enterprise") { return "Enterprise" }
            if raw.contains("business") { return "Business" }
            switch raw {
            case "free": return "Free"
            case "go": return "Go"
            case "plus": return "Plus"
            default:
                if raw.contains("pro") {
                    if override.contains("20x") || raw.contains("20x") || tier.contains("20x") { return "Pro 20x" }
                    if override.contains("5x") || raw.contains("5x") || tier.contains("5x") { return "Pro 5x" }
                    return "Pro"
                }
                return acct.plan
            }
        case "claude":
            if raw.contains("enterprise") { return "Enterprise" }
            if raw.contains("team") { return "Team" }
            if raw.contains("free") { return "Free" }
            if raw.contains("pro") && !raw.contains("max") { return "Pro" }
            if raw.contains("max") {
                if tier.contains("20x") { return "Max 20x" }
                if tier.contains("5x") { return "Max 5x" }
                return "Max"
            }
            return acct.plan
        case "antigravity":
            if override.contains("ultra") || override.contains("20x") || override.contains("5x") {
                if override.contains("20x") || override.contains("20") { return "Ultra 20x" }
                if override.contains("5x") || override.contains("5") { return "Ultra 5x" }
                return "Ultra"
            }
            if override.contains("pro") { return "Pro" }
            if override.contains("plus") { return "Plus" }
            if raw.contains("free") { return "Free" }
            if raw.contains("plus") { return "Plus" }
            if raw.contains("ultra") {
                if raw.contains("20x") { return "Ultra 20x" }
                if raw.contains("5x") { return "Ultra 5x" }
                return "Ultra"
            }
            if raw.contains("pro") { return "Pro" }
            return acct.plan
        case "xai":
            if raw.contains("heavy") { return "SuperGrok Heavy" }
            if raw.contains("super") { return "SuperGrok" }
            if raw.contains("free") { return "Free" }
            if let limit = acct.monthly_limit {
                if limit >= 30000 { return "SuperGrok Heavy" }
                if limit >= 15000 { return "SuperGrok" }
                return "Free"
            }
            return acct.plan
        case "copilot":
            if raw.contains("enterprise") { return "Enterprise" }
            if raw.contains("business") { return "Business" }
            if raw.contains("max") { return "Max" }
            if raw.contains("pro_plus") || raw.contains("pro+") { return "Pro+" }
            if raw.contains("pro") { return "Pro" }
            if raw.contains("free") { return "Free" }
            return acct.plan
        case "devin":
            if raw.contains("enterprise") { return "Enterprise" }
            if raw.contains("team") { return "Teams" }
            if raw.contains("max") { return "Max" }
            if raw.contains("pro") { return "Pro" }
            if raw.contains("free") { return "Free" }
            return acct.plan
        case "cursor":
            if raw.contains("enterprise") { return "Enterprise" }
            if raw.contains("team") { return "Teams" }
            if raw.contains("ultra") { return "Ultra" }
            if raw.contains("pro_plus") || raw.contains("pro+") { return "Pro+" }
            if raw.contains("pro") { return "Pro" }
            if raw.contains("free") { return "Free" }
            return acct.plan
        default:
            return acct.plan
        }
    }

    func planPrice(_ acct: Account) -> String? {
        guard let plan = normalizePlan(acct) else { return nil }
        switch acct.provider {
        case "codex":
            switch plan {
            case "Free": return "$0"
            case "Go": return "$8"
            case "Plus": return "$20"
            case "Pro 5x": return "$100"
            case "Pro 20x": return "$200"
            case "Business": return "$25/user"
            case "Enterprise": return "Custom"
            default: return nil
            }
        case "claude":
            switch plan {
            case "Free": return "$0"
            case "Pro": return "$20"
            case "Max 5x": return "$100"
            case "Max 20x": return "$200"
            case "Team": return "$25/seat"
            case "Enterprise": return "Custom"
            default: return nil
            }
        case "antigravity":
            switch plan {
            case "Free": return "$0"
            case "Plus": return "$7.99"
            case "Pro": return "$19.99"
            case "Ultra 5x": return "$100"
            case "Ultra 20x": return "$200"
            default: return nil
            }
        case "xai":
            switch plan {
            case "Free": return "$0"
            case "SuperGrok": return "$30"
            case "SuperGrok Heavy": return "$300"
            default: return nil
            }
        case "copilot":
            switch plan {
            case "Free": return "$0"
            case "Pro": return "$10"
            case "Pro+": return "$39"
            case "Max": return "$100"
            case "Business": return "$19/user"
            case "Enterprise": return "$39/user"
            default: return nil
            }
        case "devin":
            switch plan {
            case "Free": return "$0"
            case "Pro": return "$20"
            case "Max": return "$200"
            case "Teams": return "$80+$40/seat"
            case "Enterprise": return "Custom"
            default: return nil
            }
        case "cursor":
            switch plan {
            case "Free": return "$0"
            case "Pro": return "$20"
            case "Pro+": return "$60"
            case "Ultra": return "$200"
            case "Teams": return "$40/user"
            case "Enterprise": return "Custom"
            default: return nil
            }
        default:
            return nil
        }
    }

    func planText(_ acct: Account) -> String? {
        guard let plan = normalizePlan(acct), !plan.isEmpty else { return nil }
        if let price = planPrice(acct) {
            return "\(t("plan")): \(plan) (\(price))"
        }
        return "\(t("plan")): \(plan)"
    }

    /// "2026-08-01T00:00:00+00:00" → "08-01" (local time).
    func shortMonthDay(_ iso: String?) -> String? {
        guard let iso, let date = StatusLoader.parseStatusDate(iso) else { return nil }
        let out = DateFormatter()
        out.locale = Locale(identifier: "en_US_POSIX")
        out.dateFormat = "MM-dd"
        return out.string(from: date)
    }

    /// Subscription lifecycle line from the exported per-account `state`:
    /// "Plan · paid · renews 08-01" / "Plan · expired since 07-19".
    func subscriptionLine(_ acct: Account) -> String? {
        guard let state = acct.state, let sub = state.subscription, sub != "unknown" else { return nil }
        let plan = normalizePlan(acct) ?? t("plan")
        switch sub {
        case "paid":
            if let d = shortMonthDay(state.sub_renews_at) {
                return "\(plan) · \(t("sub_paid")) · " + String(format: t("sub_renews"), d)
            }
            return "\(plan) · \(t("sub_paid"))"
        case "renews_soon":
            let d = shortMonthDay(state.sub_renews_at) ?? "?"
            return "\(plan) · \(t("sub_paid")) · " + String(format: t("sub_renews_soon"), d)
        case "free":
            return "\(plan) · \(t("sub_free"))"
        case "expired":
            if let d = shortMonthDay(state.sub_expires_at) {
                return "\(plan) · " + String(format: t("sub_expired_since"), d)
            }
            return "\(plan) · \(t("sub_expired"))"
        default:
            return nil
        }
    }

    func planStartText(_ acct: Account) -> String? {
        let start = acct.plan_start ?? acct.billing_period_start ?? acct.monthly_period_start
        if let start, !start.isEmpty {
            return L10n.label("plan_started", start)
        }
        return nil
    }

    func planResetText(_ acct: Account) -> String? {
        let end = acct.plan_reset ?? acct.monthly_period_end
        if let end, !end.isEmpty {
            if acct.provider == "codex", acct.is_active_subscription_gratis == true {
                return L10n.label("plan_expires", end)
            }
            return L10n.label("plan_resets", end)
        }
        return nil
    }

    func quotaResetHoursLeft(_ resetStr: String?) -> Double? {
        guard let resetStr, !resetStr.isEmpty else { return nil }
        let fmt = DateFormatter()
        fmt.locale = Locale(identifier: "en_US_POSIX")
        fmt.timeZone = TimeZone(identifier: "Asia/Seoul")
        fmt.dateFormat = "yyyy-MM-dd HH:mm"
        guard let reset = fmt.date(from: resetStr) else { return nil }
        let hours = reset.timeIntervalSinceNow / 3600.0
        guard hours > 0, hours <= 24 else { return nil }
        return hours
    }

    func hasWeeklyQuota(_ acct: Account) -> Bool {
        acct.provider == "codex" || acct.provider == "claude" || acct.provider == "devin"
    }

    func hasMonthlyQuota(_ acct: Account) -> Bool {
        acct.provider == "xai" || acct.provider == "copilot"
    }

    func weeklyResetEndsSoon(_ acct: Account) -> Bool {
        guard hasWeeklyQuota(acct), acct.secondary_used_pct != nil else { return false }
        return quotaResetHoursLeft(acct.secondary_reset) != nil
    }

    func monthlyResetEndsSoon(_ acct: Account) -> Bool {
        guard hasMonthlyQuota(acct), acct.primary_used_pct != nil else { return false }
        return quotaResetHoursLeft(acct.primary_reset) != nil
    }

    func weeklyQuotaLow(_ acct: Account) -> Bool {
        guard hasWeeklyQuota(acct), let used = acct.secondary_used_pct else { return false }
        return used > 80
    }

    func monthlyQuotaLow(_ acct: Account) -> Bool {
        guard hasMonthlyQuota(acct), let used = acct.primary_used_pct else { return false }
        return used > 80
    }

    /// Compact top-level badge shown when a weekly/monthly quota resets within
    /// one day or has less than 20% remaining.
    func endSoonBadge(_ acct: Account) -> String? {
        guard weeklyResetEndsSoon(acct) || monthlyResetEndsSoon(acct) ||
              weeklyQuotaLow(acct) || monthlyQuotaLow(acct) else { return nil }
        return t("finishes_soon")
    }

    func buildCodexSubmenu(_ submenu: NSMenu, acct: Account, width: CGFloat) {
        // ─── Status group ───
        var extra: [(String, String)] = []
        if let created = acct.account_created, !created.isEmpty {
            extra.append(("account_created", created))
        }
        if let history = acct.payment_history, !history.isEmpty {
            extra.append(("payment_history", history))
        }
        statusGroup(submenu, acct: acct, width: width, extra: extra)

        // ─── Limit session group ───
        limitSessionGroup(submenu, acct: acct, width: width, fiveHour: true, weekly: true, credits: true)

        // ─── Resets group ───
        submenu.addItem(separatorRow(width: width))
        let credits = acct.reset_credits ?? []
        submenu.addItem(groupHeaderItem("Resets (\(credits.count))", width: width))
        if !credits.isEmpty {
            let couponDetailWidth: CGFloat = 260
            for c in credits {
                let typeTag = couponType(c.description)
                let issued = formatCouponExpiry(c.granted_at)
                let expire = formatCouponExpiry(c.expires_at)
                let detailSub = NSMenu()
                detailSub.autoenablesItems = false
                detailSub.addItem(infoItem(L10n.label("coupon_reason_label", typeTag), width: couponDetailWidth))
                detailSub.addItem(infoItem(L10n.label("coupon_issued_label", issued), width: couponDetailWidth))
                detailSub.addItem(infoItem(L10n.label("coupon_expire_label", expire), width: couponDetailWidth))
                submenu.addItem(submenuRow(expire, submenu: detailSub, width: width,
                                           dotColor: couponDotColor(c), badge: couponBadge(c)))
            }
        }
    }

    func buildClaudeSubmenu(_ submenu: NSMenu, acct: Account, width: CGFloat) {
        // ─── Status group ───
        statusGroup(submenu, acct: acct, width: width)

        // ─── Limit session group ───
        limitSessionGroup(submenu, acct: acct, width: width, fiveHour: true, weekly: true)
    }

    private func statusGroup(_ submenu: NSMenu, acct: Account, width: CGFloat, extra: [(String, String)] = []) {
        submenu.addItem(groupHeaderItem(t("status"), width: width))
        let na = t("na")
        if let line = planText(acct) {
            submenu.addItem(infoItem(line, width: width))
        } else {
            submenu.addItem(infoItem(L10n.label("plan", na), width: width))
        }
        if let line = subscriptionLine(acct) {
            submenu.addItem(infoItem(line, width: width))
        }
        submenu.addItem(infoItem(planStartText(acct) ?? L10n.label("plan_started", na), width: width))
        submenu.addItem(infoItem(planResetText(acct) ?? L10n.label("plan_resets", na), width: width))
        for (key, value) in extra {
            submenu.addItem(infoItem(L10n.label(key, value), width: width))
        }
        submenu.addItem(infoItem(L10n.label("token_expires", acct.token_expires ?? na), width: width))
        submenu.addItem(infoItem(L10n.label("last_poll", acct.last_poll ?? na), width: width))
    }

    /// Limit session group: only 5h / weekly / monthly / additional credits,
    /// whichever are available. The whole group is omitted when none apply.
    private func limitSessionGroup(_ submenu: NSMenu, acct: Account, width: CGFloat,
                                   fiveHour: Bool = false, weekly: Bool = false,
                                   monthly: Bool = false, credits: Bool = false,
                                   primaryLabel: String? = nil) {
        var items: [NSMenuItem] = []
        if fiveHour, let p = acct.primary_used_pct {
            items.append(infoItem(L10n.usedLine("5h_limit", String(format: "%.1f", p), reset: acct.primary_reset),
                                  width: width, accentPercent: true))
        }
        if weekly, let s = acct.secondary_used_pct {
            items.append(infoItem(L10n.usedLine("weekly_limit", String(format: "%.1f", s), reset: acct.secondary_reset),
                                  width: width, accentPercent: true,
                                  warnPercent: weeklyQuotaLow(acct),
                                  accentResetTime: weeklyResetEndsSoon(acct)))
        }
        if acct.provider == "claude", let p = acct.fable_used_pct {
            items.append(infoItem(L10n.usedLine("fable_limit", String(format: "%.1f", p), reset: acct.fable_reset),
                                  width: width, accentPercent: true))
        } else if acct.provider == "claude", let st = acct.fable_status, !st.isEmpty {
            items.append(infoItem("\(L10n.tr("fable_limit")): \(L10n.tr("fable_\(st)"))",
                                  width: width))
        }
        if monthly, let p = acct.primary_used_pct {
            items.append(infoItem(L10n.usedLine("monthly_limit", String(format: "%.1f", p), reset: acct.primary_reset),
                                  width: width, accentPercent: true,
                                  warnPercent: monthlyQuotaLow(acct),
                                  accentResetTime: monthlyResetEndsSoon(acct)))
        }
        if let label = primaryLabel, let p = acct.primary_used_pct {
            items.append(infoItem(L10n.usedLine(label, String(format: "%.1f", p), reset: acct.primary_reset),
                                  width: width, accentPercent: true,
                                  warnPercent: monthlyQuotaLow(acct),
                                  accentResetTime: monthlyResetEndsSoon(acct)))
        }
        if credits, let b = acct.credits_balance {
            items.append(infoItem(L10n.label("additional_credits", String(format: "%.0f", b)), width: width))
        }
        if items.isEmpty { return }
        submenu.addItem(separatorRow(width: width))
        submenu.addItem(groupHeaderItem("Limit session", width: width))
        for item in items { submenu.addItem(item) }
    }

    func buildGrokSubmenu(_ submenu: NSMenu, acct: Account, width: CGFloat) {
        statusGroup(submenu, acct: acct, width: width)

        // ─── Limit session group ───
        limitSessionGroup(submenu, acct: acct, width: width, monthly: true)
    }

    func buildAntigravitySubmenu(_ submenu: NSMenu, acct: Account, width: CGFloat) {
        statusGroup(submenu, acct: acct, width: width)

        // ─── Limit session group ───
        if let windows = acct.usage_windows, !windows.isEmpty {
            submenu.addItem(separatorRow(width: width))
            submenu.addItem(groupHeaderItem(t("limit_session"), width: width))
            for w in windows {
                let groupLabel = w.group == "gemini" ? t("ag_group_gemini") : t("ag_group_other")
                let windowKey = w.window == "weekly" ? "weekly_limit" : "5h_limit"
                let pct = w.used_pct ?? 0
                let line = "\(groupLabel) · " + L10n.usedLine(windowKey, String(format: "%.1f", pct), reset: w.reset)
                submenu.addItem(infoItem(line, width: width, accentPercent: true, warnPercent: pct > 80))
            }
        } else {
            limitSessionGroup(submenu, acct: acct, width: width, primaryLabel: "tier_usage")
        }
    }

    func buildCopilotSubmenu(_ submenu: NSMenu, acct: Account, width: CGFloat) {
        statusGroup(submenu, acct: acct, width: width)

        // ─── Limit session group ───
        limitSessionGroup(submenu, acct: acct, width: width, primaryLabel: "premium_requests")
    }

    func buildDevinSubmenu(_ submenu: NSMenu, acct: Account, width: CGFloat) {
        statusGroup(submenu, acct: acct, width: width)

        // ─── Limit session group ───
        limitSessionGroup(submenu, acct: acct, width: width, weekly: true)
    }

    func detailLines(_ acct: Account) -> [String] {
        var lines: [String] = []
        if let plan = normalizePlan(acct), !plan.isEmpty {
            lines.append(L10n.label("plan", plan))
        }
        if let sub = subscriptionLine(acct) {
            lines.append(sub)
        }
        if let start = planStartText(acct) {
            lines.append(start)
        }
        if let reset = planResetText(acct) {
            lines.append(reset)
        }
        if let msg = acct.status_message, !msg.isEmpty {
            lines.append(L10n.label("status", msg))
        }
        if let exp = acct.token_expires {
            lines.append(L10n.label("token_expires", exp))
        }
        // Primary window (5h for codex/claude, 24h for xai, etc.)
        if let p = acct.primary_used_pct {
            let w1: String
            switch acct.provider {
            case "codex", "claude": w1 = "5h"
            case "xai": w1 = t("window_monthly")
            case "copilot": w1 = t("window_quota")
            case "antigravity": w1 = t("window_tier")
            default: w1 = t("window_win")
            }
            lines.append("\(w1) \(t("window_label")): \(String(format: "%.1f", p))% \(t("used"))")
            if let r = acct.primary_reset {
                lines.append("  \(t("reset")): \(r)")
            }
        }
        // Secondary window (7d for codex/claude, 24h tokens for xai)
        if let s = acct.secondary_used_pct {
            let w2: String
            switch acct.provider {
            case "codex", "claude": w2 = "7d"
            case "xai": w2 = t("window_24h_tokens")
            default: w2 = t("window_win")
            }
            lines.append("\(w2) \(t("window_label")): \(String(format: "%.1f", s))% \(t("used"))")
            if let r = acct.secondary_reset {
                lines.append("  \(t("reset")): \(r)")
            }
        }
        // Codex-specific details are rendered via buildCodexSubmenu (grouped).
        // Copilot-specific: SKU
        if acct.provider == "copilot" {
            if let sku = acct.sku {
                lines.append(L10n.label("sku", sku))
            }
            if let q = acct.limited_user_quotas {
                lines.append(L10n.label("quota_limit", q))
            }
            if let r = acct.limited_user_reset_date {
                lines.append(L10n.label("quota_reset", r))
            }
        }
        // Grok-specific: monthly credits
        if acct.provider == "xai" {
            if let used = acct.monthly_used, let limit = acct.monthly_limit {
                lines.append("\(t("monthly")): \(Int(used))/\(Int(limit)) \(t("credits"))")
            }
            if let r = acct.primary_reset ?? acct.monthly_period_end {
                lines.append("  \(t("reset")): \(r)")
            }
        }
        // Fallback for providers without window data
        if acct.primary_used_pct == nil {
            if let rem = acct.rate_limit_remaining {
                lines.append(L10n.label("remaining", rem))
            }
            if let reset = acct.rate_limit_reset {
                lines.append(L10n.label("reset", reset))
            }
            if let lim = acct.rate_limit_limit {
                lines.append(L10n.label("limit", lim))
            }
        }
        if let lp = acct.last_poll {
            lines.append(L10n.label("last_poll", lp))
        }
        if lines.isEmpty {
            lines.append(t("no_details"))
        }
        return lines
    }

    func providerDisplayName(_ provider: String) -> String {
        switch provider {
        case "xai": return "Grok"
        case "codex": return "Codex"
        case "claude": return "Claude"
        case "antigravity": return "Antigravity"
        case "copilot": return "Copilot"
        case "cursor": return "Cursor"
        case "devin": return "Devin"
        case "droid": return "Droid"
        case "opencode": return "Opencode"
        default: return provider.capitalized
        }
    }

    func addFooter(_ menu: NSMenu) {
        menu.addItem(actionItem(t("poll_now")) { [weak self] in self?.loader.runPoll() })
        menu.addItem(actionItem(t("manage_accounts")) { [weak self] in self?.loader.openPanel() })
        menu.addItem(actionItem(t("open_dashboard")) { [weak self] in self?.loader.runDashboard() })
        menu.addItem(actionItem(t("refresh_display")) { [weak self] in self?.loader.reload() })
        menu.addItem(submenuRow(t("add_new_agent"), submenu: addAgentSubmenu()))
        menu.addItem(submenuRow(t("language"), submenu: languageSubmenu()))
        menu.addItem(submenuRow(t("layout"), submenu: layoutSubmenu()))
        menu.addItem(infoItem(timezoneLabel()))
        menu.addItem(separatorRow())
        let quit = NSMenuItem(title: t("quit"), action: #selector(quitApp), keyEquivalent: "q")
        quit.keyEquivalentModifierMask = [.command]
        quit.target = self
        menu.addItem(quit)
    }

    func t(_ key: String) -> String { L10n.tr(key) }

    func languageSubmenu() -> NSMenu {
        let submenu = NSMenu()
        let w: CGFloat = 200
        for lang in Language.allCases {
            let active = (lang == language)
            submenu.addItem(actionItem(lang.nativeName, width: w, checkmark: active) { [weak self] in
                self?.setLanguage(lang)
            })
        }
        return submenu
    }

    func timezoneLabel() -> String {
        let seconds = TimeZone.current.secondsFromGMT()
        let sign = seconds < 0 ? "-" : "+"
        let hours = abs(seconds) / 3600
        let minutes = (abs(seconds) % 3600) / 60
        let offsetStr = minutes == 0
            ? "UTC\(sign)\(hours)"
            : String(format: "UTC%@%d:%02d", sign, hours, minutes)
        return "Time Zone: \(offsetStr)"
    }

    func setLanguage(_ lang: Language) {
        Language.current = lang
        language = lang
        L10n.lang = lang
        if let menu = statusItem.menu {
            menu.removeAllItems()
            buildMenu(menu)
        }
    }

    /// Layout experiment switcher (spec §2.1): both layouts with a checkmark
    /// on the active one; switching rebuilds the menu like setLanguage does.
    func layoutSubmenu() -> NSMenu {
        let submenu = NSMenu()
        let w: CGFloat = 200
        for layout in MenuLayout.allCases {
            let active = (layout == menuLayout)
            submenu.addItem(actionItem(t(layout.titleKey), width: w, checkmark: active) { [weak self] in
                self?.setMenuLayout(layout)
            })
        }
        return submenu
    }

    func setMenuLayout(_ layout: MenuLayout) {
        MenuLayout.current = layout
        menuLayout = layout
        if let menu = statusItem.menu {
            menu.removeAllItems()
            buildMenu(menu)
        }
    }

    func addAgentSubmenu() -> NSMenu {
        let submenu = NSMenu()
        let w: CGFloat = 200
        // Browser panel (opencodex-style): all OAuth add/reconnect/manage
        // happens in the accounts page the local server serves.
        submenu.addItem(actionItem(t("manage_accounts"), width: w) { [weak self] in self?.loader.openPanel() })
        // Devin uses an API key, not OAuth — keep the in-app secure prompt.
        submenu.addItem(separatorRow(width: w))
        submenu.addItem(actionItem("Devin (API key)…", width: w) { [weak self] in self?.loader.addAgent(provider: "devin") })
        return submenu
    }

    // ─── Row builders ─────────────────────────────────────────────────────
    // NSMenuItems get an empty title: the fixed-width view carries the text,
    // and a non-empty title would also feed NSMenu's width calculation,
    // widening the menu past the views when the string is long.
    func titleItem(_ title: String) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.isEnabled = false
        item.view = FixedMenuRowView(title: title, style: .title, accentNumbers: true)
        return item
    }

    func headerItem(_ title: String) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.isEnabled = false
        item.view = FixedMenuRowView(title: title, style: .header)
        return item
    }

    func groupHeaderItem(_ title: String, width: CGFloat = MenuRowLayout.width) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.isEnabled = false
        item.view = FixedMenuRowView(title: title, style: .groupHeader, width: width)
        return item
    }

    func bulletItem(_ title: String, width: CGFloat = MenuRowLayout.width) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.isEnabled = false
        item.view = FixedMenuRowView(title: title, style: .bullet, width: width)
        return item
    }

    func infoItem(_ title: String, width: CGFloat = MenuRowLayout.width,
                  accentPercent: Bool = false, warnPercent: Bool = false,
                  accentResetTime: Bool = false) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.isEnabled = false
        item.view = FixedMenuRowView(title: title, style: .info, accentPercent: accentPercent,
                                     warnPercent: warnPercent, accentResetTime: accentResetTime, width: width)
        return item
    }

    func warningItem(_ title: String, width: CGFloat = MenuRowLayout.width) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.isEnabled = false
        item.view = FixedMenuRowView(title: title, style: .warning, width: width)
        return item
    }

    func formatExpiryKST(_ raw: String?) -> String {
        guard let raw, !raw.isEmpty else { return "?" }
        if raw.hasSuffix(" KST") { return raw }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var date = parser.date(from: raw)
        if date == nil {
            parser.formatOptions = [.withInternetDateTime]
            date = parser.date(from: raw)
        }
        guard let date else { return raw }
        let out = DateFormatter()
        out.locale = Locale(identifier: "en_US_POSIX")
        out.timeZone = TimeZone(identifier: "Asia/Seoul")
        out.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return "\(out.string(from: date)) KST"
    }

    func formatCouponExpiry(_ raw: String?) -> String {
        let full = formatExpiryKST(raw)
        // "2026-07-12 11:11:10 KST" → "2026-07-12 11:11" (drop seconds and KST)
        if full.hasSuffix(" KST"), full.count >= 16 {
            return String(full.prefix(16))
        }
        return full
    }

    func couponExpiryDate(_ raw: String?) -> Date? {
        guard let raw, !raw.isEmpty else { return nil }
        let normalized = raw.replacingOccurrences(of: " KST", with: "")
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "Asia/Seoul")
        for format in ["yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm"] {
            formatter.dateFormat = format
            if let date = formatter.date(from: normalized) {
                return date
            }
        }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = parser.date(from: raw) {
            return date
        }
        parser.formatOptions = [.withInternetDateTime]
        return parser.date(from: raw)
    }

    func couponEndsSoon(_ credit: ResetCredit) -> Bool {
        guard credit.status == "available",
              let expiry = couponExpiryDate(credit.expires_at) else { return false }
        let secondsLeft = expiry.timeIntervalSinceNow
        return secondsLeft > 0 && secondsLeft <= 3 * 24 * 60 * 60
    }

    func couponDotColor(_ credit: ResetCredit) -> NSColor {
        if couponEndsSoon(credit) {
            return .systemOrange
        }
        return credit.status == "available" ? .systemGreen : .systemGray
    }

    func couponBadge(_ credit: ResetCredit) -> String? {
        couponEndsSoon(credit) ? t("finishes_soon") : nil
    }

    func couponType(_ desc: String?) -> String {
        guard let desc, !desc.isEmpty else { return "?" }
        if desc.lowercased().contains("inviting") {
            return t("coupon_referral")
        }
        return t("coupon_usage")
    }

    func actionItem(_ title: String, width: CGFloat = MenuRowLayout.width,
                    checkmark: Bool = false, destructive: Bool = false,
                    action: @escaping () -> Void) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.view = FixedMenuRowView(title: title, style: .action, action: action,
                                     checkmark: checkmark, destructive: destructive, width: width)
        return item
    }

    func submenuRow(_ title: String, submenu: NSMenu, width: CGFloat = MenuRowLayout.width,
                    dotColor: NSColor? = nil, badge: String? = nil) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.submenu = submenu
        item.view = FixedMenuRowView(title: title, style: .submenu, submenu: submenu,
                                     dotColor: dotColor, badge: badge, width: width)
        return item
    }

    func separatorRow(width: CGFloat = MenuRowLayout.width) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        item.isEnabled = false
        item.view = FixedMenuSeparatorView(width: width)
        return item
    }

    func formatUpdated(_ iso: String) -> String {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var date = parser.date(from: iso)
        if date == nil {
            parser.formatOptions = [.withInternetDateTime]
            date = parser.date(from: iso)
        }
        if date == nil {
            // generated_at has no timezone suffix; parse as local time.
            let local = DateFormatter()
            local.locale = Locale(identifier: "en_US_POSIX")
            local.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
            date = local.date(from: iso) ?? {
                local.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
                return local.date(from: iso)
            }()
        }
        guard let date else { return iso }
        let out = DateFormatter()
        out.locale = Locale(identifier: "en_US")
        out.dateFormat = "MMMM d, yyyy HH:mm"
        return out.string(from: date)
    }
}
