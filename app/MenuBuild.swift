import Cocoa

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
    func addLiveActivityRow(_ menu: NSMenu, payload: StatusPayload) {
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

}
