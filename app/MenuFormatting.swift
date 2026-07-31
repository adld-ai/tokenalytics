import Cocoa

extension AppDelegate {
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
            if let limit = acct.credits_limit {
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
        let start = acct.plan_start
        if let start, !start.isEmpty {
            return L10n.label("plan_started", start)
        }
        return nil
    }

    func planResetText(_ acct: Account) -> String? {
        let end: String?
        if acct.provider == "copilot" {
            let reset = (acct.windows ?? []).compactMap(\.reset_at_epoch).first
            if let reset {
                let formatter = DateFormatter()
                formatter.locale = Locale(identifier: "en_US_POSIX")
                formatter.timeZone = TimeZone(identifier: "Asia/Seoul")
                formatter.dateFormat = "yyyy-MM-dd"
                end = formatter.string(from: Date(timeIntervalSince1970: reset))
            } else {
                end = nil
            }
        } else {
            end = acct.plan_reset
        }
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
        guard hasMonthlyQuota(acct),
              let reset = (acct.windows ?? []).first(where: { $0.kind == "monthly" })?.reset_at_epoch
        else { return false }
        let hours = Date(timeIntervalSince1970: reset).timeIntervalSinceNow / 3600.0
        return hours > 0 && hours <= 24
    }

    func weeklyQuotaLow(_ acct: Account) -> Bool {
        guard hasWeeklyQuota(acct), let used = acct.secondary_used_pct else { return false }
        return used > 80
    }

    func monthlyQuotaLow(_ acct: Account) -> Bool {
        guard hasMonthlyQuota(acct),
              let window = (acct.windows ?? []).first(where: { $0.kind == "monthly" }),
              let used = window.used_pct_effective ?? window.used_pct
        else { return false }
        return used > 80
    }

    /// Compact top-level badge shown when a weekly/monthly quota resets within
    /// one day or has less than 20% remaining.
    func endSoonBadge(_ acct: Account) -> String? {
        guard weeklyResetEndsSoon(acct) || monthlyResetEndsSoon(acct) ||
              weeklyQuotaLow(acct) || monthlyQuotaLow(acct) else { return nil }
        return t("finishes_soon")
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
