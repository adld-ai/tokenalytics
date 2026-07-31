import Foundation

struct StatusPayload: Codable {
    var generated_at: String
    var account_count: Int
    var heartbeat: HeartbeatSummary?
    var headline: Headline?
    var accounts: [Account]
    // Last auto-swap event (M4 swap engine; absent until then).
    var last_swap: LastSwap?
}

/// Placeholder for the M4 swap engine's "account_swapped" export.
/// All fields optional so the row simply renders nothing until the
/// backend starts emitting `last_swap`.
struct LastSwap: Codable {
    var provider: String?
    var from: String?
    var to: String?
    var at: String?
    var at_epoch: Double?
}

struct HeartbeatSummary: Codable {
    var status: String
    var next: String?
    var accounts: Int?
    var failed: Int?
}

struct Account: Codable, Identifiable {
    var id: Int
    var provider: String
    var email: String?
    var label: String?
    var plan: String?
    var status: String
    var status_message: String?
    var token_expires: String?
    var token_expired: Bool?
    var primary_used_pct: Double?
    var primary_reset: String?
    var secondary_used_pct: Double?
    var secondary_reset: String?
    var credits_balance: Double?
    var banked_resets: Int?
    var rate_limit_remaining: String?
    var rate_limit_reset: String?
    var rate_limit_limit: String?
    var plan_reset: String?
    var monthly_used: Double?
    var monthly_limit: Double?
    var monthly_used_pct: Double?
    var monthly_period_start: String?
    var monthly_period_end: String?
    var reset_credits: [ResetCredit]?
    var last_poll: String?
    var heartbeat_status: String?
    var heartbeat_last: String?
    var heartbeat_next: String?
    var heartbeat_message: String?
    // Claude subscription / window-status details
    var subscription_status: String?
    var billing_type: String?
    var rate_limit_tier: String?
    var extra_usage_enabled: Bool?
    var subscription_created: String?
    var member_since: String?
    var display_name: String?
    var org_name: String?
    var primary_status: String?
    var secondary_status: String?
    var binding_window: String?
    var overage_status: String?
    // Claude Fable model-scoped weekly window (separate weekly limit)
    var fable_used_pct: Double?
    var fable_reset: String?
    var fable_label: String?
    var fable_status: String?
    // Grok / Antigravity / Copilot / Devin subscription details
    var on_demand_cap: Int?
    var tier_id: String?
    var tier_description: String?
    var access_sku: String?
    var premium_entitlement: Int?
    var premium_overage: Int?
    var chat_unlimited: Bool?
    var completions_unlimited: Bool?
    var can_upgrade: Bool?
    var organizations: String?
    var credit_balance: Double?
    var plan_start: String?
    var plan_price: String?
    var active_tier: String?
    var paid_since: String?
    var renews_at: String?
    var expires_at: String?
    var account_created: String?
    var subscription_plan: String?
    var has_active_subscription: Bool?
    var is_active_subscription_gratis: Bool?
    var has_previously_paid_subscription: Bool?
    var payment_history: String?
    var billing_note: String?
    var github_email: String?
    var github_name: String?
    var tier_override: String?
    var heartbeat_last_success: String?
    var usage_windows: [UsageWindow]?
    var windows: [WindowInfo]?
    var live: LiveActivity?
    // Per-poll lifecycle classification (backend account_state, spec §1.2).
    // Optional so older status.json files still decode.
    var state: AccountState?
}

/// Exact per-account lifecycle state exported by the backend on every poll.
/// Every field is optional-tolerant: decoding must not break on payloads
/// written before this field existed.
struct AccountState: Codable {
    var auth: String?           // "ok" | "token_expired" | "error"
    var subscription: String?   // "paid" | "free" | "expired" | "renews_soon" | "unknown"
    var sub_renews_at: String?
    var sub_expires_at: String?
    var quota: String?          // "ok" | "warning" | "exhausted" | "unknown"
    var usable: Bool?
    var binding_window: WindowInfo?
}

struct ResetCredit: Codable {
    var title: String?
    var status: String?
    var expires_at: String?
    var granted_at: String?
    var description: String?
}

struct UsageWindow: Codable {
    var group: String?
    var window: String?
    var used_pct: Double?
    var reset: String?
}

struct WindowInfo: Codable {
    var kind: String
    var label: String?
    var used_pct: Double?
    var reset_at_epoch: Double?
    var severity: String?
    var is_active: Bool?
    var source: String?
    var as_of_epoch: Double?
    var projected_exhaust_epoch: Double?
    // Window phase fields (backend refresh_windows, spec §1.3). Optional so
    // older status.json files still decode.
    var phase: String?              // "live" | "reset"
    var used_pct_effective: Double?
    var stale: Bool?
}

struct Headline: Codable {
    var account_id: Int
    var provider: String
    var email: String?
    var kind: String
    var label: String?
    var used_pct: Double
    var reset_at_epoch: Double?
    var severity: String
}

struct LiveActivity: Codable {
    var provider: String?
    var event_epoch: Double?
    var last_total_tokens: Int?
    var last_cached_tokens: Int?
    var last_output_tokens: Int?
    var context_used_pct: Double?
    var tokens_60m: Int?
    var as_of_epoch: Double?
}
