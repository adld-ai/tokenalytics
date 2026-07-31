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

}
