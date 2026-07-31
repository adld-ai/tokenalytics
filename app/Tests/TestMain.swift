import Cocoa

@main
struct TestMain {
    static var failures = 0

    static func expect(_ cond: Bool, _ label: String) {
        if cond { print("ok - \(label)") }
        else { failures += 1; print("FAIL - \(label)") }
    }

    static func main() {
        if CommandLine.arguments.contains("--record-golden-submenus") {
            try! legacySubmenuDump().write(
                to: goldenURL(), atomically: true, encoding: .utf8)
            print("recorded \(goldenURL().path)")
            return
        }
        testStatusDecode()
        testFormatting()
        testGoldenSubmenus()
        if failures > 0 { print("\(failures) FAILURES"); exit(1) }
        print("all swift tests passed")
    }

    static func fixtureURL() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .appendingPathComponent("fixture-status.json")
    }

    static func goldenURL() -> URL {
        fixtureURL().deletingLastPathComponent()
            .appendingPathComponent("golden-submenus.txt")
    }

    static func testStatusDecode() {
        let data = try! Data(contentsOf: fixtureURL())
        let p = try! JSONDecoder().decode(StatusPayload.self, from: data)
        expect(p.accounts.count == 7, "fixture has 7 accounts")
        expect(p.accounts[0].provider == "codex", "provider decodes")
        expect(p.accounts[0].windows?.first?.kind == "5h", "window kind decodes")
        expect(p.headline?.used_pct != nil, "headline decodes")
        expect(p.accounts[1].state?.usable != nil, "state decodes")
    }

    static func rowTitle(_ item: NSMenuItem) -> String {
        if item.view is FixedMenuSeparatorView { return "<separator>" }
        if let view = item.view,
           let label = view.subviews.compactMap({ $0 as? NSTextField }).first {
            return label.stringValue
        }
        return item.title
    }

    static func legacySubmenuDump() -> String {
        L10n.lang = .en
        let data = try! Data(contentsOf: fixtureURL())
        let payload = try! JSONDecoder().decode(StatusPayload.self, from: data)
        let delegate = AppDelegate()
        var lines: [String] = []
        for account in payload.accounts {
            lines.append("[\(account.provider)]")
            let item = delegate.accountItem(account)
            lines.append(contentsOf: item.submenu!.items.map(rowTitle))
        }
        return lines.joined(separator: "\n") + "\n"
    }

    static func testGoldenSubmenus() {
        let expected = try! String(contentsOf: goldenURL(), encoding: .utf8)
        expect(legacySubmenuDump() == expected, "account submenus match golden")
    }

    static func testFormatting() {
        let data = try! Data(contentsOf: fixtureURL())
        let payload = try! JSONDecoder().decode(StatusPayload.self, from: data)
        let delegate = AppDelegate()
        var account = payload.accounts[0]
        account.secondary_used_pct = 81

        let couponFormatter = DateFormatter()
        couponFormatter.locale = Locale(identifier: "en_US_POSIX")
        couponFormatter.timeZone = TimeZone(identifier: "Asia/Seoul")
        couponFormatter.dateFormat = "yyyy-MM-dd HH:mm:ss 'KST'"
        let coupon = ResetCredit(
            title: nil,
            status: "available",
            expires_at: couponFormatter.string(from: Date().addingTimeInterval(24 * 60 * 60)),
            granted_at: nil,
            description: nil
        )

        let normalizedPlan = delegate.normalizePlan(account)
        let price = delegate.planPrice(account)
        let monthDay = delegate.shortMonthDay("2026-08-01T00:00:00+09:00")
        let updated = delegate.formatUpdated("2026-07-31T09:00:00")
        let endSoon = delegate.endSoonBadge(account)
        let couponIsEnding = delegate.couponEndsSoon(coupon)

        expect(normalizedPlan == "Plus", "normalizePlan formats Codex Plus")
        expect(price == "$20", "planPrice formats Codex Plus price")
        expect(monthDay == "08-01", "shortMonthDay formats ISO date")
        expect(updated == "July 31, 2026 09:00", "formatUpdated formats local timestamp")
        expect(endSoon == "End Soon", "endSoonBadge labels low weekly quota")
        expect(couponIsEnding == true, "couponEndsSoon detects expiry within 3 days")
    }
}
