import Cocoa

enum MenuRowLayout {
    static let width: CGFloat = 320
    static let standardHeight: CGFloat = 24
}

final class FixedMenuSeparatorView: NSView {
    init(width: CGFloat = MenuRowLayout.width) {
        super.init(frame: NSRect(x: 0, y: 0, width: width, height: 9))
        wantsLayer = true
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        NSColor.separatorColor.setStroke()
        let path = NSBezierPath()
        path.move(to: NSPoint(x: 12, y: bounds.midY))
        path.line(to: NSPoint(x: bounds.width - 12, y: bounds.midY))
        path.lineWidth = 1
        path.stroke()
    }
}

final class FixedMenuRowView: NSView {
    enum Style {
        case header
        case title
        case info
        case action
        case submenu
        case groupHeader
        case bullet
        case warning
    }

    private let style: Style
    private let action: (() -> Void)?
    private let submenu: NSMenu?
    private let dotColor: NSColor?
    private let hollowDot: Bool
    private let accentNumbers: Bool
    private let accentPercent: Bool
    private let warnPercent: Bool
    private let accentResetTime: Bool
    private let checkmark: Bool
    private let destructive: Bool
    private var rawTitle: String
    private let badgeText: String?
    private let label = NSTextField(labelWithString: "")
    private let chevron = NSTextField(labelWithString: "›")
    private let check = NSTextField(labelWithString: "✓")
    private let badgeLabel = NSTextField(labelWithString: "")
    private let dotLayer = CALayer()
    private let highlightLayer = CALayer()
    private var hovered = false

    init(title: String, style: Style, action: (() -> Void)? = nil, submenu: NSMenu? = nil,
         dotColor: NSColor? = nil, hollowDot: Bool = false,
         accentNumbers: Bool = false, accentPercent: Bool = false,
         warnPercent: Bool = false, accentResetTime: Bool = false,
         checkmark: Bool = false, badge: String? = nil, destructive: Bool = false,
         width: CGFloat = MenuRowLayout.width) {
        self.style = style
        self.action = action
        self.submenu = submenu
        self.dotColor = dotColor
        self.hollowDot = hollowDot
        self.accentNumbers = accentNumbers
        self.accentPercent = accentPercent
        self.warnPercent = warnPercent
        self.accentResetTime = accentResetTime
        self.checkmark = checkmark
        self.destructive = destructive
        self.rawTitle = title
        self.badgeText = badge
        super.init(frame: NSRect(x: 0, y: 0, width: width, height: MenuRowLayout.standardHeight))

        wantsLayer = true
        highlightLayer.cornerRadius = 5
        highlightLayer.isHidden = true
        layer?.addSublayer(highlightLayer)

        if let dotColor {
            dotLayer.cornerRadius = 4
            if hollowDot {
                // Hollow dot: outline only (blocked accounts).
                dotLayer.backgroundColor = NSColor.clear.cgColor
                dotLayer.borderColor = dotColor.cgColor
                dotLayer.borderWidth = 1.5
            } else {
                dotLayer.backgroundColor = dotColor.cgColor
            }
            layer?.addSublayer(dotLayer)
        }

        switch style {
        case .header:
            label.font = NSFont.systemFont(ofSize: 11, weight: .medium)
        case .title:
            label.font = NSFont.systemFont(ofSize: NSFont.menuFont(ofSize: 0).pointSize, weight: .semibold)
        case .groupHeader:
            label.font = NSFont.systemFont(ofSize: 11, weight: .bold)
        case .warning:
            label.font = NSFont.systemFont(ofSize: NSFont.menuFont(ofSize: 0).pointSize, weight: .medium)
        default:
            label.font = NSFont.menuFont(ofSize: 0)
        }
        label.textColor = baseLabelColor
        label.lineBreakMode = .byTruncatingTail
        applyTitle(highlighted: false)
        addSubview(label)

        chevron.font = NSFont.menuFont(ofSize: 0)
        chevron.textColor = .secondaryLabelColor
        chevron.alignment = .center
        chevron.isHidden = style != .submenu
        addSubview(chevron)

        check.font = NSFont.menuFont(ofSize: 0)
        check.textColor = .white
        check.alignment = .center
        check.isHidden = !(style == .action && checkmark)
        addSubview(check)

        if let badgeText {
            badgeLabel.stringValue = badgeText
            badgeLabel.font = NSFont.systemFont(ofSize: 10, weight: .medium)
            badgeLabel.textColor = .systemOrange
            badgeLabel.alignment = .right
            addSubview(badgeLabel)
        }
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    /// Replace the row text in place (used by the 1s menu ticker so reset
    /// countdowns keep ticking while the menu stays open).
    func updateTitle(_ title: String) {
        guard title != rawTitle else { return }
        rawTitle = title
        applyTitle(highlighted: hovered && (style == .action || style == .submenu))
    }

    private func applyTitle(highlighted: Bool) {
        let base = highlighted ? NSColor.white : baseLabelColor
        if style == .bullet {
            let attr = NSMutableAttributedString(
                string: rawTitle, attributes: [.font: label.font as Any, .foregroundColor: base])
            // Shrink only the leading bullet glyph; keep text at normal size.
            if !rawTitle.isEmpty {
                attr.addAttribute(.font, value: NSFont.systemFont(ofSize: 7),
                                  range: NSRange(location: 0, length: 1))
            }
            label.attributedStringValue = attr
            return
        }
        if accentPercent, !highlighted {
            let attr = NSMutableAttributedString(
                string: rawTitle, attributes: [.font: label.font as Any, .foregroundColor: base])
            if let r = rawTitle.range(of: "[0-9]+(\\.[0-9]+)?%", options: .regularExpression) {
                attr.addAttribute(.foregroundColor, value: warnPercent ? NSColor.systemOrange : NSColor.systemGreen,
                                  range: NSRange(r, in: rawTitle))
            }
            if accentResetTime,
               let r = rawTitle.range(of: "\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}", options: .regularExpression) {
                attr.addAttribute(.foregroundColor, value: NSColor.systemOrange,
                                  range: NSRange(r, in: rawTitle))
            }
            label.attributedStringValue = attr
            return
        }
        guard accentNumbers, !highlighted else {
            label.attributedStringValue = NSAttributedString(
                string: rawTitle, attributes: [.font: label.font as Any, .foregroundColor: base])
            return
        }
        let attr = NSMutableAttributedString(
            string: rawTitle, attributes: [.font: label.font as Any, .foregroundColor: base])
        let ns = rawTitle as NSString
        ns.enumerateSubstrings(in: NSRange(location: 0, length: ns.length),
                               options: .byComposedCharacterSequences) { sub, range, _, _ in
            if let sub, sub.rangeOfCharacter(from: .decimalDigits) != nil {
                attr.addAttribute(.foregroundColor, value: NSColor.systemGreen, range: range)
            }
        }
        label.attributedStringValue = attr
    }

    override func layout() {
        super.layout()
        highlightLayer.frame = bounds.insetBy(dx: 6, dy: 2)
        let showCheck = style == .action && checkmark
        let labelX: CGFloat = dotColor == nil ? (showCheck ? 30 : 14) : 28
        dotLayer.frame = NSRect(x: 14, y: bounds.midY - 4, width: 8, height: 8)
        check.frame = NSRect(x: 12, y: 4, width: 16, height: 16)
        // Reserve space on the right for badge (when present) + chevron.
        let badgeW: CGFloat = badgeText == nil ? 0 : 80
        let rightInset: CGFloat = (style == .submenu ? 28 : labelX) + badgeW
        label.frame = NSRect(x: labelX, y: 4, width: bounds.width - labelX - rightInset, height: 16)
        if badgeText != nil {
            let badgeHeight = ceil(badgeLabel.intrinsicContentSize.height)
            badgeLabel.frame = NSRect(
                x: bounds.width - 25 - badgeW,
                y: floor((bounds.height - badgeHeight) / 2),
                width: badgeW - 4,
                height: badgeHeight
            )
        }
        chevron.frame = NSRect(x: bounds.width - 25, y: 4, width: 13, height: 16)
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(
            rect: bounds,
            options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
            owner: self
        ))
    }

    override func mouseEntered(with event: NSEvent) {
        hovered = true
        applyHighlight()
    }

    override func mouseExited(with event: NSEvent) {
        hovered = false
        applyHighlight()
    }

    private func applyHighlight() {
        let highlighted = hovered && (style == .action || style == .submenu)
        highlightLayer.isHidden = !highlighted
        highlightLayer.backgroundColor = NSColor.controlAccentColor.withAlphaComponent(0.92).cgColor
        applyTitle(highlighted: highlighted)
        chevron.textColor = highlighted ? .white : .secondaryLabelColor
        check.textColor = .white
    }

    private var baseLabelColor: NSColor {
        if destructive { return .systemRed }
        switch style {
        case .header, .info, .bullet: return .secondaryLabelColor
        case .warning: return .systemOrange
        case .title, .action, .submenu, .groupHeader: return .labelColor
        }
    }

    override func mouseDown(with event: NSEvent) {
        switch style {
        case .action:
            enclosingMenuItem?.menu?.cancelTracking()
            action?()
        case .submenu:
            guard let submenu else { return }
            submenu.popUp(positioning: nil, at: NSPoint(x: bounds.maxX - 4, y: bounds.maxY - 2), in: self)
        case .header, .title, .info, .groupHeader, .bullet, .warning:
            break
        }
    }
}

/// One thin usage gauge: [label | bar | pct · time-left].
final class GaugeRowView: NSView {
    private let info: WindowInfo
    private let color: NSColor

    init(window: WindowInfo, color: NSColor, width: CGFloat) {
        self.info = window
        self.color = color
        super.init(frame: NSRect(x: 0, y: 0, width: width, height: 16))
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    private func kindLabel() -> String {
        if info.kind == "model_weekly" { return info.label ?? "model" }
        if let label = info.label, info.kind == "monthly" { return label }
        return info.kind
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let pct = max(0, min(100, info.used_pct ?? 0))
        let labelX: CGFloat = 28
        let rightW: CGFloat = 96
        let attrsLabel: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 10.5),
            .foregroundColor: NSColor.secondaryLabelColor,
        ]
        let label = kindLabel()
        let desiredLabelW = ceil((label as NSString).size(withAttributes: attrsLabel).width)
        let maxLabelW = max(62, bounds.width - labelX - rightW - 70)
        let labelW = min(max(62, desiredLabelW), maxLabelW)
        let barX = labelX + labelW + 6
        let barW = bounds.width - barX - rightW - 16
        (label as NSString).draw(
            with: NSRect(x: labelX, y: 2, width: labelW, height: 14),
            options: [.truncatesLastVisibleLine], attributes: attrsLabel)

        let track = NSRect(x: barX, y: 5.5, width: barW, height: 5)
        NSColor.quaternaryLabelColor.setFill()
        NSBezierPath(roundedRect: track, xRadius: 2.5, yRadius: 2.5).fill()
        if pct > 0 {
            let fill = NSRect(x: barX, y: 5.5, width: barW * pct / 100.0, height: 5)
            color.setFill()
            NSBezierPath(roundedRect: fill, xRadius: 2.5, yRadius: 2.5).fill()
        }

        var right = "\(Int(pct.rounded()))%"
        if let left = AppDelegate.timeLeft(info.reset_at_epoch) { right += " · \(left)" }
        let attrsRight: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 10.5, weight: .regular),
            .foregroundColor: NSColor.secondaryLabelColor,
        ]
        let size = (right as NSString).size(withAttributes: attrsRight)
        (right as NSString).draw(
            at: NSPoint(x: bounds.width - 16 - size.width, y: 2),
            withAttributes: attrsRight)
    }
}

/// Account row + its gauge bars stacked into one menu-item view.
final class AccountRowWithGauges: NSView {
    /// The title row, exposed so the 1s menu ticker can update countdowns.
    let rowView: FixedMenuRowView

    init(row: FixedMenuRowView, gauges: [GaugeRowView], width: CGFloat) {
        self.rowView = row
        let gaugeH: CGFloat = 16
        let pad: CGFloat = gauges.isEmpty ? 0 : 4
        let height = MenuRowLayout.standardHeight + CGFloat(gauges.count) * gaugeH + pad
        super.init(frame: NSRect(x: 0, y: 0, width: width, height: height))
        row.setFrameOrigin(NSPoint(x: 0, y: height - MenuRowLayout.standardHeight))
        addSubview(row)
        for (i, g) in gauges.enumerated() {
            g.setFrameOrigin(NSPoint(x: 0, y: CGFloat(gauges.count - 1 - i) * gaugeH + 2))
            g.setFrameSize(NSSize(width: width, height: gaugeH))
            addSubview(g)
        }
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
}
