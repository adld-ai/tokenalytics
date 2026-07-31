import Cocoa
import Combine

class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem!
    var loader = StatusLoader()
    var popover: NSPopover!
    var language: Language = .en
    var menuLayout: MenuLayout = .classic
    // 1s ticker: keeps LIMITED-section reset countdowns ticking while the
    // menu is open (usable-first layout only). Section moves happen on the
    // next menu open (menuNeedsUpdate re-derives phase client-side).
    var menuTicker: Timer?
    var limitedRows: [(row: FixedMenuRowView, account: Account)] = []
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

    func windowRiskColor(pct: Double, severity: String?, projected: Bool) -> NSColor {
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
