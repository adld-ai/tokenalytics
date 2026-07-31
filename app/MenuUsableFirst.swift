import Cocoa

extension AppDelegate {
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
    func limitedRowTitle(_ acct: Account, now: Double) -> String {
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

}
