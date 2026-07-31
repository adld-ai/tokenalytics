import Foundation

enum Language: String, CaseIterable {
    case en, ko, zh, ja

    var nativeName: String {
        switch self {
        case .en: return "English"
        case .ko: return "한국어"
        case .zh: return "中文"
        case .ja: return "日本語"
        }
    }

    static let storageKey = "TSBLanguage"
    static var current: Language {
        get {
            let raw = UserDefaults.standard.string(forKey: storageKey) ?? "en"
            return Language(rawValue: raw) ?? .en
        }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: storageKey) }
    }
}

enum MenuLayout: String, CaseIterable {
    case classic
    case usableFirst = "usable-first"

    var titleKey: String {
        switch self {
        case .classic: return "layout_classic"
        case .usableFirst: return "layout_usable_first"
        }
    }

    static let storageKey = "menuLayout"
    static var current: MenuLayout {
        get {
            let raw = UserDefaults.standard.string(forKey: storageKey) ?? MenuLayout.classic.rawValue
            return MenuLayout(rawValue: raw) ?? .classic
        }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: storageKey) }
    }
}
