import Cocoa

extension AppDelegate {
    func statusColor(_ status: String) -> NSColor {
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

    func addHeartbeatStatus(_ submenu: NSMenu, acct: Account, width: CGFloat) {
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

}
