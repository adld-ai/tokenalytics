import Cocoa
import Combine
import SwiftUI

// ─── Models ───────────────────────────────────────────────────────────────

// ─── Status Loader ────────────────────────────────────────────────────────

// ─── Menu Row Design (ported from codex-status-bar) ───────────────────────

// ─── Language Mode ─────────────────────────────────────────────────────────


// ─── Dropdown layout experiment (spec §2.1) ────────────────────────────────

// ─── Menu Bar App ─────────────────────────────────────────────────────────


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
