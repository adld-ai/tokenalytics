import Cocoa

private enum AccountSubmenuRow {
    case groupHeader(String)
    case info(String)
    case gauge(WindowInfo, String)
    case bullet(String)
    case warning(String)
    case separator
    case coupon(ResetCredit, String)
    case heartbeatAction(String)
    case swapAction(String)
    case reconnectAction(String)
    case deleteAction(String)

    var title: String {
        switch self {
        case .groupHeader(let title), .info(let title), .bullet(let title),
             .warning(let title), .heartbeatAction(let title),
             .swapAction(let title), .reconnectAction(let title),
             .deleteAction(let title):
            return title
        case .gauge(_, let title), .coupon(_, let title):
            return title
        case .separator:
            return "<separator>"
        }
    }
}

extension AppDelegate {
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
        let submenu = buildAccountSubmenu(acct)
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

    /// Ordered, UI-independent titles for every row in an account submenu.
    func submenuSummary(_ acct: Account) -> [String] {
        accountSubmenuRows(acct).map(\.title)
    }

    func buildAccountSubmenu(_ acct: Account) -> NSMenu {
        let submenu = NSMenu()
        let width: CGFloat = 420
        for row in accountSubmenuRows(acct) {
            let item = accountSubmenuItem(row, acct: acct, width: width)
            item.representedObject = row.title
            submenu.addItem(item)
        }
        return submenu
    }

    private func accountSubmenuRows(_ acct: Account) -> [AccountSubmenuRow] {
        var rows = statusGroup(acct)
        rows.append(contentsOf: limitSessionGroup(acct))

        if let credits = acct.reset_credits {
            rows.append(.separator)
            rows.append(.groupHeader("\(t("resets")) (\(credits.count))"))
            rows.append(contentsOf: credits.map {
                .coupon($0, formatCouponExpiry($0.expires_at))
            })
        }

        let details = detailLines(acct)
        if !details.isEmpty {
            rows.append(.separator)
            rows.append(contentsOf: details.map { .bullet("• \($0)") })
        }

        for window in acct.windows ?? [] {
            guard let exhaust = window.projected_exhaust_epoch,
                  let left = AppDelegate.timeLeft(exhaust) else { continue }
            let name = window.kind == "model_weekly" ? (window.label ?? "model") : window.kind
            rows.append(.warning("⚠︎ \(name): exhausts in ~\(left) at current pace"))
        }

        rows.append(.separator)
        let heartbeat = heartbeatRows(acct)
        rows.append(contentsOf: heartbeat)
        if !heartbeat.isEmpty { rows.append(.separator) }
        if acct.provider == "codex", acct.state?.usable == true {
            rows.append(.swapAction(t("swap_to_agent")))
        }
        rows.append(.reconnectAction(t("reconnect_agent")))
        rows.append(.deleteAction(t("delete_agent")))
        return rows
    }

    private func statusGroup(_ acct: Account) -> [AccountSubmenuRow] {
        var rows: [AccountSubmenuRow] = [.groupHeader(t("status"))]
        if let plan = planText(acct) { rows.append(.info(plan)) }
        if let line = subscriptionLine(acct) { rows.append(.info(line)) }
        if let start = planStartText(acct) { rows.append(.info(start)) }
        if let reset = planResetText(acct) { rows.append(.info(reset)) }
        if let created = acct.account_created, !created.isEmpty {
            rows.append(.info(L10n.label("account_created", created)))
        }
        if let history = acct.payment_history, !history.isEmpty {
            rows.append(.info(L10n.label("payment_history", history)))
        }
        if let expires = acct.token_expires, !expires.isEmpty {
            rows.append(.info(L10n.label("token_expires", expires)))
        }
        if let poll = acct.last_poll, !poll.isEmpty {
            rows.append(.info(L10n.label("last_poll", poll)))
        }
        return rows
    }

    private func windowLabel(_ window: WindowInfo) -> String {
        if let label = window.label, !label.isEmpty { return label }
        return window.kind == "model_weekly" ? "model" : window.kind
    }

    private func windowTitle(_ window: WindowInfo) -> String {
        let pct = String(format: "%.1f", window.used_pct ?? 0)
        return "\(windowLabel(window)): \(pct)% \(t("used"))"
    }

    private func windowResetText(_ window: WindowInfo?) -> String? {
        guard let reset = window?.reset_at_epoch else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "Asia/Seoul")
        formatter.dateFormat = "yyyy-MM-dd HH:mm"
        return formatter.string(from: Date(timeIntervalSince1970: reset))
    }

    private func limitSessionGroup(_ acct: Account) -> [AccountSubmenuRow] {
        let windows = acct.windows ?? []
        guard !windows.isEmpty || acct.credits_balance != nil else { return [] }
        var rows: [AccountSubmenuRow] = [
            .separator,
            .groupHeader(t("limit_session")),
        ]
        rows.append(contentsOf: windows.map { .gauge($0, windowTitle($0)) })
        if let balance = acct.credits_balance {
            rows.append(.info(L10n.label("additional_credits", String(format: "%.0f", balance))))
        }
        return rows
    }

    private func heartbeatRows(_ acct: Account) -> [AccountSubmenuRow] {
        guard acct.heartbeat_status != nil || acct.heartbeat_next != nil || acct.heartbeat_last != nil else {
            return []
        }
        let status: String
        switch acct.heartbeat_status {
        case "success": status = t("heartbeat_success")
        case "fail": status = t("heartbeat_fail")
        default: status = t("heartbeat_unknown")
        }
        var rows: [AccountSubmenuRow] = [
            .groupHeader(t("heartbeat")),
            .info("\(t("heartbeat")): \(status) · \(t("heartbeat_next")) \(acct.heartbeat_next ?? "?")"),
        ]
        if let last = acct.heartbeat_last {
            rows.append(.info("\(t("heartbeat_last")): \(last)"))
        }
        if let lastSuccess = acct.heartbeat_last_success {
            rows.append(.info("\(t("heartbeat_last_success")): \(lastSuccess)"))
        }
        if let message = acct.heartbeat_message, !message.isEmpty {
            rows.append(.info(message))
        }
        rows.append(.heartbeatAction(t("run_heartbeat_now")))
        return rows
    }

    private func accountSubmenuItem(_ row: AccountSubmenuRow, acct: Account,
                                    width: CGFloat) -> NSMenuItem {
        switch row {
        case .groupHeader(let title):
            return groupHeaderItem(title, width: width)
        case .info(let title):
            return infoItem(title, width: width)
        case .gauge(let window, _):
            var displayWindow = window
            if let label = window.label, !label.isEmpty {
                displayWindow.kind = label
                displayWindow.label = nil
            }
            let item = NSMenuItem(title: "", action: nil, keyEquivalent: "")
            item.isEnabled = false
            item.view = GaugeRowView(
                window: displayWindow,
                color: windowRiskColor(pct: window.used_pct ?? 0,
                                       severity: window.severity,
                                       projected: window.projected_exhaust_epoch != nil),
                width: width)
            return item
        case .bullet(let title):
            return bulletItem(title, width: width)
        case .warning(let title):
            return warningItem(title, width: width)
        case .separator:
            return separatorRow(width: width)
        case .coupon(let credit, let title):
            let detailWidth: CGFloat = 260
            let detail = NSMenu()
            detail.autoenablesItems = false
            detail.addItem(infoItem(L10n.label("coupon_reason_label", couponType(credit.description)),
                                    width: detailWidth))
            detail.addItem(infoItem(L10n.label("coupon_issued_label", formatCouponExpiry(credit.granted_at)),
                                    width: detailWidth))
            detail.addItem(infoItem(L10n.label("coupon_expire_label", formatCouponExpiry(credit.expires_at)),
                                    width: detailWidth))
            return submenuRow(title, submenu: detail, width: width,
                              dotColor: couponDotColor(credit), badge: couponBadge(credit))
        case .heartbeatAction(let title):
            return actionItem(title, width: width) { [weak self] in
                self?.loader.runHeartbeat(accountId: acct.id)
            }
        case .swapAction(let title):
            return actionItem(title, width: width) { [weak self] in
                self?.loader.swapToAgent(acct)
            }
        case .reconnectAction(let title):
            return actionItem(title, width: width) { [weak self] in
                self?.loader.reconnectAgent(acct)
            }
        case .deleteAction(let title):
            return actionItem(title, width: width, destructive: true) { [weak self] in
                self?.loader.confirmDeleteAgent(acct: acct)
            }
        }
    }

    /// Provider-specific facts that do not yet have a declared-window source.
    func detailLines(_ acct: Account) -> [String] {
        var lines: [String] = []
        if let message = acct.status_message, !message.isEmpty {
            lines.append(L10n.label("status", message))
        }
        if acct.provider == "claude",
           !(acct.windows ?? []).contains(where: { $0.kind == "model_weekly" }),
           let status = acct.fable_status, !status.isEmpty {
            lines.append("\(L10n.tr("fable_limit")): \(L10n.tr("fable_\(status)"))")
        }
        if acct.provider == "copilot" {
            if let sku = acct.access_sku { lines.append(L10n.label("sku", sku)) }
            if let quota = acct.rate_limit_limit {
                lines.append(L10n.label("quota_limit", quota))
            }
            if let reset = acct.rate_limit_reset {
                lines.append(L10n.label("quota_reset", reset))
            }
        }
        if acct.provider == "xai" {
            if let used = acct.credits_used, let limit = acct.credits_limit {
                lines.append("\(t("monthly")): \(Int(used))/\(Int(limit)) \(t("credits"))")
            }
            let monthly = (acct.windows ?? []).first(where: { $0.kind == "monthly" })
            if let reset = windowResetText(monthly) ?? acct.plan_reset {
                lines.append("  \(t("reset")): \(reset)")
            }
        }
        if let remaining = acct.rate_limit_remaining {
            lines.append(L10n.label("remaining", remaining))
        }
        if acct.provider != "copilot", let reset = acct.rate_limit_reset {
            lines.append(L10n.label("reset", reset))
        }
        if acct.provider != "copilot", let limit = acct.rate_limit_limit {
            lines.append(L10n.label("limit", limit))
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
}
