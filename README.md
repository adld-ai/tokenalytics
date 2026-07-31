<p align="center">
  <img src="./public/assets/readme/token-status-bar-icon.png" alt="Token Status Bar app icon on transparent background" width="140">
</p>

<h1 align="center">TokenBar</h1>

<p align="center">
  <em>Token status for every AI user. Straight from your macOS menu bar.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.0.2-111111?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/macOS-14%2B-111111?style=flat-square" alt="macOS 14+">
  <img src="https://img.shields.io/badge/Swift-menu%20bar-111111?style=flat-square" alt="Swift menu bar">
  <img src="https://img.shields.io/badge/Python-3.9%2B-111111?style=flat-square" alt="Python 3.9+">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-111111?style=flat-square" alt="License: MIT"></a>
</p>

<p align="center">
  <sub><a href="./README.md">English</a> &middot; <a href="./README.ko.md">한국어</a></sub>
</p>

<p align="center">
  <a href="https://github.com/bytonylee/token-status-bar/releases/latest/download/TokenStatusBar.dmg"><img src="./public/assets/readme/download-macos.png" alt="Download TokenStatusBar.dmg for Mac OS" width="270"></a>
</p>

<p align="center">
  <img src="./public/assets/readme/token-status-bar-hero.png" alt="Token Status Bar hero banner showing token quota status across multiple AI providers in a macOS menu bar" width="720">
</p>

---

> *TokenBar manages every AI coding-agent account you own — OpenAI Codex,
> Anthropic Claude, xAI / Grok, Google Antigravity, GitHub Copilot, and Devin
> — from a single macOS menu bar. Every poll classifies each account's exact
> subscription (paid / free / expired / renews-soon) and quota (ok / warning /
> exhausted) state, rolls stale windows forward the moment they reset, and can
> automatically swap credentials to a fresh account when the active one runs
> dry — so you're never caught mid-work with a dead token.*

Click the menu to see providers grouped with a green / yellow / red
availability dot per account, drill into a per-account submenu, or hit
**Poll Now** for a fresh fetch.

> Built for people juggling several agent accounts who want to know at a glance
> which one still has quota, which is about to reset, and which token is about
> to expire — without opening a dashboard.

**The Python backend polls each provider and writes `secrets/status.json` —
adaptive cadence: 5-minute base, 60-second polling for hot accounts, and a
~15-second local session sync; the Swift app reads it every 30 seconds.
Onboarding is a one-click `Add New Agent` menu item: browser-OAuth providers
launch the OAuth flow directly, GitHub Copilot opens Terminal to show its
device code, and Devin asks for its API key in an in-app prompt. No scraping
where a real API exists.**

## Features

- Menu-bar dropdown grouped by provider, with a green / yellow / red availability
  dot per account.
- Per-account submenu with plan, status, token expiry, and quota windows.
- Real-time quota for every supported provider (no scraping where an API exists).
- Background poller (5-minute base interval, 60-second hot polling, ~15-second
  local sync) plus on-demand **Poll Now**.
- One-click **Add New Agent** onboarding — browser OAuth in the background,
  Copilot's device-code flow in Terminal, Devin via an in-app API-key prompt.
- Exact subscription and quota state every poll — stale windows roll forward
  the moment they reset, so the dot never lies.
- Zero-touch account swap — when the active Codex account exhausts its
  quota, TokenBar automatically swaps in a usable same-provider account
  (guardrails: cooldown, no swap on stale data or mid-session, notified
  every time).
- Full lifecycle audit trail — every reset, paid/expired transition, and
  swap is recorded and queryable.

## Supported providers

| Provider          | Key           | Auth          |
|-------------------|---------------|---------------|
| OpenAI Codex      | `codex`       | OAuth (browser) |
| Anthropic Claude  | `claude`      | OAuth (browser) |
| xAI / Grok        | `xai`         | OAuth (browser) |
| Google Antigravity| `antigravity` | OAuth (browser) |
| GitHub Copilot    | `copilot`     | OAuth (device flow) |
| Devin             | `devin`       | API key       |

### Current status coverage

| Provider | Usage / quota status | Subscription period status |
|----------|----------------------|----------------------------|
| OpenAI Codex | Plan, 5h / weekly usage, reset credits | Not exposed by the current authenticated `wham/usage` response |
| Anthropic Claude | Plan, 5h / weekly usage | Subscription start only (`subscription_created_at`) |
| xAI / Grok | Monthly credits, daily request/token limits | Start and end exposed by the billing API |
| Google Antigravity | Tier and model quota | Not exposed by the current Code Assist endpoints |
| GitHub Copilot | Premium/chat quota and monthly reset | Reset/end only (`quota_reset_date`) |
| Devin | Daily/weekly quota and credit balance | Start and end exposed by `GetUserStatus` |

## How it works

Two pipelines share one adapter registry. **Onboarding** asks the provider
adapter which auth kind and login hooks it supports, then stores the resulting
account in `pool.db`. **Polling** dispatches to that same adapter, which emits
provider-neutral quota windows. The backend writes those windows to
`secrets/status.json`, and the multi-file Swift app renders them without
provider-specific menu code.

### Flow

```mermaid
flowchart TD
    A["Add New Agent<br/>(menu or CLI)"] --> B[providers.load registry]
    B --> C{Adapter auth path?}
    C -->|OAuth browser| D[PKCE flow]
    C -->|OAuth device flow| E[Device code]
    C -->|API key| F[Devin API key]
    C -->|Local file| V[Vendor CLI credentials]
    C -->|None| X[No credentials]
    D --> G[account identity + plan]
    E --> G
    F --> G
    V --> G
    X --> G
    G --> H[(pool.db)]

    I[poll-loop daemon<br/>5-min base, 60s hot] --> J[poller.run_loop]
    K["Poll Now<br/>(on demand)"] --> L[poller.run_once]
    J --> M[for each account]
    L --> M
    M --> N[resolve provider adapter]
    N --> O{token expiring?}
    O -->|yes| P[adapter refresh hook]
    P --> H
    O -->|no or tokenless| Q[adapter poll]
    Q --> R[declared windows]
    R --> S[(pool.db snapshot)]
    S --> T[status.json]
    T --> U["TokenStatusBar.app<br/>reads every 30s"]
    U --> W[menu bar dropdown + dots]
```

### Onboarding — connecting an account

```mermaid
flowchart TD
    A["Add New Agent (menu) /<br/>pool.py add &lt;provider&gt; (CLI)"] --> B[providers.load]
    B --> C[adapter AUTH + login hooks]
    C -->|OAuth browser| D1["adapter browser flow<br/>PKCE callback → user approves"]
    C -->|Device flow| D2["adapter login hook<br/>device code → token polling"]
    C -->|API key| D3["secure prompt<br/>adapter validates key"]
    C -->|Local file| D4["adapter reads vendor CLI credentials"]
    C -->|None| D5[no credential setup]
    D1 --> E["access + refresh token"]
    D2 --> E
    D3 --> E
    D4 --> E
    D5 --> E
    E --> F["account identity + plan"]
    F --> G["store.upsert_account<br/>save token when required"]
    G --> H[(pool.db)]
```

### Polling — getting the quota info

```mermaid
flowchart TD
    A["poll-loop daemon (5-min base, 60s hot)"] --> B[pool.py poll-loop → poller.run_loop]
    C["Poll Now (on demand)"] --> D[pool.py poll → poller.run_once]
    B --> E[for each account in store.list_accounts]
    D --> E
    E --> F[providers.get account.provider]
    F --> G{adapter requires a token?}
    G -->|yes| H["load token; run adapter REFRESH when needed"]
    G -->|no| J[adapter reads local source]
    H --> K[adapter poll]
    J --> K
    K --> L["util.snapshot(windows[])"]
    L --> I[(pool.db)]
    I --> M["status.cmd_export → status.json"]
    M --> N["TokenStatusBar.app reads every 30s → dropdown UI + dots"]
```

## Requirements

- macOS 14 (Sonoma) or later — the app targets `LSMinimumSystemVersion` 14.0.
- Xcode command-line tools (`swiftc`) to build the app.
- Python 3.9+ for the polling backend.

## Layout

| Path                 | Purpose |
|----------------------|---------|
| `app/*.swift`        | Multi-file Swift menu-bar UI compiled directly with `swiftc`. |
| `app/Tests/`         | Swift characterization fixtures and golden submenu coverage. |
| `build.sh`           | Compiles and bundles the app; `--dmg` creates the release image. |
| `test.sh`            | Enforces Swift file ceilings, compiles the test harness, and runs its assertions. |
| `backend/providers/*.py` | Auto-discovered registry: one adapter per provider, including auth, polling, capabilities, and window mapping. |
| `backend/pool.py`    | CLI: onboarding, polling, status export. |
| `backend/poller.py`  | Registry-driven polling cadence and snapshot orchestration. |
| `backend/status.py`  | Writes `status.json` for the app to read. |
| `backend/store.py`   | SQLite storage (`pool.db`). |
| `backend/oauth.py`   | Shared OAuth orchestration over adapter-declared login and refresh hooks. |
| `secrets/status.json` | Snapshot consumed by the menu-bar app (git-ignored). |
| `secrets/pool.db`    | SQLite account/quota store (git-ignored). |

Data lives under `~/solo/token-status-bar/secrets/` by default (`pool.db`,
`status.json`). Override with the `AGENT_POOL_DB` and `AGENT_POOL_STATUS_JSON`
environment variables.

## Build & run the app

```bash
./test.sh
./build.sh
./build.sh --dmg
open /Applications/TokenStatusBar.app
```

The app reads `secrets/status.json` every 30 seconds and shows a chart icon in
the menu bar.

## CLI usage

```bash
python3 backend/pool.py add <provider> [label]   # onboard via OAuth (codex|claude|xai|antigravity|copilot)
python3 backend/pool.py add-devin <api_key> [label]
python3 backend/pool.py list                     # list all accounts
python3 backend/pool.py remove <account_id>
python3 backend/pool.py status                   # accounts + latest limit status
python3 backend/pool.py poll                     # one poll cycle (hits all APIs)
python3 backend/pool.py poll-loop                # run the poller daemon (5-min base interval)
python3 backend/pool.py refresh <account_id>     # refresh one token
python3 backend/pool.py refresh-all              # refresh all expiring tokens
python3 backend/pool.py export-status            # write status.json
```

## Background poller (launchd, manual setup)

No launchd plist ships with this repo — the background poller is a manual
setup. To keep `secrets/status.json` fresh, create
`~/Library/LaunchAgents/com.tonye.agentpool-poller.plist` yourself with a
`ProgramArguments` entry that runs `python3 <repo>/backend/pool.py poll-loop`
and `RunAtLoad`/`KeepAlive` set to true, then load it:

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.tonye.agentpool-poller.plist
```

After editing `poller.py`, restart the daemon so it loads the new code:

```bash
launchctl kickstart -k "gui/$(id -u)/com.tonye.agentpool-poller"
```

Alternatively, skip launchd and run `python3 backend/pool.py poll-loop` in any
terminal session (or rely on the menu's **Poll Now**).

## Poll Now vs Refresh Display

- **Poll Now** — actively calls every provider's API, updates `pool.db` and
  `status.json`, then reloads. Slower; fetches fresh numbers.
- **Refresh Display** — only re-reads the cached `status.json` from disk.
  Instant; no network.

## License

[MIT](./LICENSE)
