# TokenBar Full Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish what `docs/superpowers/specs/2026-07-31-provider-adapter-sync-design.md`
started — migrate the six legacy providers (codex, claude, xai, antigravity,
copilot, devin) onto the declared-windows adapter framework so "a provider"
lives in exactly one file, and split the 2,968-line Swift monolith
`app/TokenStatusBar.swift` into focused files with a characterization-test
harness.

**Architecture:** Swift work goes first (pure moves, compile-verified, then a
test harness, then windows-first rendering) because the backend migration
removes the per-provider flat fields from `status.json` that today's
per-provider Swift submenus read. Backend migration is per-provider behind a
golden window-parity test; legacy read branches are quarantined into one
module for historical DB rows, then everything registry-driven.

**Tech Stack:** Swift (plain `swiftc`, no Xcode/SPM), Python 3.9+ stdlib-only
backend, `unittest`-style tests run via `python3 -m pytest backend -q`,
`build.sh` hand-rolled bundling.

## Global Constraints

- Interview seed (2026-07-31, recorded in `~/.agents/state/decisions.jsonl`):
  full refactor of backend + Swift app; **no new providers** — kimi/kiro plus
  the six legacy migrations prove "new provider = 1 file"; `status.json`
  contract may change **only** with simultaneous updates on both sides.
- Commit style: short imperative subject like the existing log
  (`Handle ended Copilot subscriptions`). **No AI/agent attribution lines**
  (`Co-Authored-By` etc.) — user rule overrides harness default.
- One logical unit (usually one file or one file+its test) per commit.
- Test command: `python3 -m pytest backend -q` from repo root.
  Baseline before this plan: **357 passed, 25 subtests**. Never commit red.
- Per `AGENTS.md`: before any PR, `bash build.sh` must produce the `.app`
  and `bash build.sh --dmg` the `.dmg`; after building, quit the old
  instance (`osascript -e 'tell application "TokenStatusBar" to quit'`) and
  `open /Applications/TokenStatusBar.app`.
- Quantitative acceptance (measured in Task 6.3):
  - `elif/if provider ==` chains in `poller.py`, `status.py`,
    `window_history.py`, `oauth.py`, `store.py` non-quarantine code: **0**
    (the single quarantine module `backend/legacy_windows.py` is the only
    place legacy branches survive, and only for pre-migration DB rows).
  - No Swift file over **600 lines** except `Localization.swift`
    (dictionary literal); no backend module over **800 lines**.
  - No import cycles (`python3 -c "import poller"` from `backend/` works;
    adapters never import `poller`).
- Out of scope (explicitly, per spec §6 and the interview): generalizing
  `local_sync.py`; the 9 not-yet-built adapters (cursor, droid, zai, …);
  `swap.py`'s codex/claude swap mechanics beyond the `CAPS` flag in Task 6.2.

---

## Phase 0 — Baseline: commit the in-flight work

The working tree carries the whole adapter framework uncommitted. Land it as
reviewable units before touching anything else.

### Task 0.1: Commit the adapter framework and declared-windows readers

**Files:**
- Commit (new): `backend/providers/__init__.py`, `backend/providers/util.py`
- Commit (modified): `backend/status.py`, `backend/window_history.py`,
  `backend/poller.py`, `backend/test_window_history.py`
- Commit (new tests): `backend/test_declared_windows.py`,
  `backend/test_declared_history.py`, `backend/test_poller_adapters.py`,
  `backend/test_providers.py`

**Interfaces:**
- Produces: the committed registry API later tasks call —
  `providers.load()`, `providers.register(mod)`, `providers.pollers()`,
  `providers.requires_token(name)`, `providers.names()`, `providers.errors()`,
  `providers.reset_cache()`; `util.window(kind, **fields)`,
  `util.snapshot(windows, *, plan=None, raw=None, status="active", ...)`,
  `util.AUTH_OAUTH/AUTH_API_KEY/AUTH_LOCAL_FILE/AUTH_NONE`;
  `status.declared_windows(rj, src, as_of)`; `window_history.declared(...)`;
  `poller.resolve_poller(provider)`.

- [ ] **Step 1: Verify the tree is green before committing**

Run: `python3 -m pytest backend -q`
Expected: `357 passed, 25 subtests passed`

- [ ] **Step 2: Commit in dependency order, one unit each**

Run each commit; after each, run `python3 -m pytest backend -q`. If a test
file imports a module from a later commit (collection error), move that test
file into the later commit rather than reordering code.

```bash
git add backend/providers/__init__.py backend/providers/util.py
git commit -m "Add provider adapter registry"

git add backend/status.py backend/test_declared_windows.py
git commit -m "Read adapter-declared windows in status display"

git add backend/window_history.py backend/test_window_history.py backend/test_declared_history.py
git commit -m "Archive adapter-declared windows in history"

git add backend/poller.py backend/test_poller_adapters.py backend/test_providers.py
git commit -m "Route polling through the adapter registry"
```

- [ ] **Step 3: Commit the shipped adapters and packaging**

```bash
git add backend/providers/kimi.py backend/providers/kiro.py backend/test_adapter_kimi_kiro.py
git commit -m "Add Kimi and Kiro usage adapters"

git add build.sh
git commit -m "Bundle provider adapters into the app build"

git add app/TokenStatusBar.swift
git commit -m "Append unknown providers to the dropdown"
```

- [ ] **Step 4: Commit the rest**

```bash
git add backend/reset_announcements.py
git commit -m "Record late-July Codex reset announcements"

git add docs/research docs/superpowers/specs/2026-07-31-provider-adapter-sync-design.md
git commit -m "Add provider usage research and adapter sync design"

git add worker backend/cloud_push.py
git commit -m "Add Cloudflare Worker mobile dashboard"

printf 'ck-price-review/\n' >> .gitignore
git add .gitignore
git commit -m "Ignore local price-review screenshots"
```

(`ck-price-review/` is four PNG screenshots — scratch material, not source.
If the user wants them kept, move them under `docs/research/` instead.)

- [ ] **Step 5: Verify clean tree and green suite**

Run: `git status --short` → empty. `python3 -m pytest backend -q` → 357 passed.

---

## Phase 1 — Split the Swift monolith (behavior-identical moves)

Every task here is a pure move: cut lines from `TokenStatusBar.swift`, paste
into a new file, promote `private` members that now cross file boundaries to
internal (delete the `private` keyword — the compiler is the arbiter: build
each step and fix exactly the access errors it reports). No logic edits.

Known cross-file promotions (from the structure survey; line numbers refer to
the pre-split monolith):
- `AppDelegate.windowRiskColor` (1599), `AppDelegate.limitedRows` (1565),
  `AppDelegate.menuTicker` (1564) — used by the menu extension.
- Extension-internal members that end up in different files:
  `startMenuTicker`/`stopMenuTicker`/`tickCountdowns` (2011–2033),
  `statusColor` (2035), `heartbeatColor` (2044), `addHeartbeatStatus` (2095),
  `windowKindLabel`/`bindingSummary`/`limitedReason`/`limitedRowTitle`/
  `blockedReason` (1826–1886), `statusGroup` (2499), `limitSessionGroup`
  (2521), `addLiveActivityRow` (1765), `AccountSection` (1789), and every
  row-factory helper (2800–2943).

Typecheck loop (fast, no bundling):

```bash
swiftc -typecheck -parse-as-library app/*.swift
```

### Task 1.1: Multi-file compilation + extract Models.swift

**Files:**
- Modify: `build.sh:28-32`
- Create: `app/Models.swift` (monolith lines 6–189)
- Modify: `app/TokenStatusBar.swift` (remove moved lines)

**Interfaces:**
- Produces: `Models.swift` holding `StatusPayload`, `LastSwap`,
  `HeartbeatSummary`, `Account`, `AccountState`, `ResetCredit`,
  `UsageWindow`, `WindowInfo`, `Headline`, `LiveActivity` — all `Codable`,
  unchanged. Every later Swift task consumes these types by name.

- [ ] **Step 1: Point build.sh at all Swift files**

In `build.sh`, replace the single-file argument:

```bash
swiftc -framework Cocoa -framework SwiftUI \
  "$DIR/app/"*.swift \
  -o "$BUILD_DIR/$APP_NAME" \
  -parse-as-library \
  2>&1
```

(The glob does not recurse, so the later `app/Tests/` directory stays out of
the app binary.)

- [ ] **Step 2: Move lines 6–189 into `app/Models.swift`**

New file starts with `import Foundation` (the structs need nothing else);
delete those lines from `TokenStatusBar.swift`, keeping its `import Cocoa`,
`import Combine`, `import SwiftUI` header.

- [ ] **Step 3: Typecheck**

Run: `swiftc -typecheck -parse-as-library app/*.swift`
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add build.sh app/Models.swift app/TokenStatusBar.swift
git commit -m "Extract status models into Models.swift"
```

### Task 1.2: Extract StatusLoader.swift

**Files:**
- Create: `app/StatusLoader.swift` (monolith lines 192–571; header
  `import Cocoa`, `import Combine`, `import SwiftUI`)
- Modify: `app/TokenStatusBar.swift`

**Interfaces:**
- Produces: `class StatusLoader: ObservableObject` unchanged — `@Published
  var payload`, `@Published var lastError`, `start()`, `stop()`, `reload()`,
  `runPoll()`, `runHeartbeat()`, `addAgent(...)`, `swapToAgent(...)`,
  `reconnectAgent(...)`, `deleteAgent(...)`, `openPanel()`,
  `static parseStatusDate(_:)` (promote to internal if `private`).

- [ ] **Step 1: Move lines 192–571 into `app/StatusLoader.swift`**
- [ ] **Step 2: Typecheck; fix any `private`→internal the compiler names**
- [ ] **Step 3: Commit**

```bash
git add app/StatusLoader.swift app/TokenStatusBar.swift
git commit -m "Extract StatusLoader into its own file"
```

### Task 1.3: Extract MenuRowViews.swift, Preferences.swift, Localization.swift

**Files:**
- Create: `app/MenuRowViews.swift` (lines 574–919: `MenuRowLayout`,
  `FixedMenuSeparatorView`, `FixedMenuRowView` + nested `Style`,
  `GaugeRowView`, `AccountRowWithGauges`)
- Create: `app/Preferences.swift` (lines 922–942 `Language`,
  1522–1541 `MenuLayout`)
- Create: `app/Localization.swift` (lines 944–1519 `L10n`)
- Modify: `app/TokenStatusBar.swift`

**Interfaces:**
- Produces: `MenuRowLayout.width`/`.standardHeight` (internal — they are
  default parameter values in row-factory signatures), `FixedMenuRowView`,
  `FixedMenuRowView.Style`, `GaugeRowView(window:...)`,
  `AccountRowWithGauges`, `Language.current`, `MenuLayout.current`,
  `L10n.lang` (the one global mutable — stays `static var` on `L10n`),
  `L10n.tr/label/usedLine/bool`.

- [ ] **Step 1: Move the three ranges into the three files** (one commit each
  is fine; `MenuRowViews.swift` header `import Cocoa`, the other two
  `import Foundation`)
- [ ] **Step 2: Typecheck after each move**
- [ ] **Step 3: Commit**

```bash
git add app/MenuRowViews.swift app/TokenStatusBar.swift
git commit -m "Extract custom menu row views"
git add app/Preferences.swift app/Localization.swift app/TokenStatusBar.swift
git commit -m "Extract preferences and localization tables"
```

### Task 1.4: Extract AppEntry.swift and AppDelegate.swift

**Files:**
- Create: `app/AppEntry.swift` — **only** lines 1544–1553
  (`@main struct TokenStatusBarApp`). Keeping `@main` alone in one file is
  what lets the test harness (Phase 2) compile everything else.
- Create: `app/AppDelegate.swift` — lines 1555–1693 (class body: lifecycle,
  status item, icon drawing, `timeLeft`, `windowRiskColor`, `limitedRows`,
  `menuTicker`, `quitApp`)
- Modify: `app/TokenStatusBar.swift` (now contains only the
  `extension AppDelegate: NSMenuDelegate`)

**Interfaces:**
- Produces: `AppDelegate` with these members promoted to internal because the
  menu extension (other files) uses them: `loader`, `statusItem`,
  `limitedRows`, `menuTicker`, `windowRiskColor(_:)`, `static timeLeft(_:)`,
  `quitApp` (`@objc`). `applicationWillTerminate` calls `stopMenuTicker()`
  which lives in the extension — that stays internal too.

- [ ] **Step 1: Move the two ranges; typecheck; fix access errors**
- [ ] **Step 2: Commit**

```bash
git add app/AppEntry.swift app/AppDelegate.swift app/TokenStatusBar.swift
git commit -m "Extract app entry point and delegate"
```

### Task 1.5: Split the menu extension

**Files:** (all new files start `import Cocoa` and declare
`extension AppDelegate { ... }`; the `NSMenuDelegate` conformance stays on
exactly one of them)
- Create: `app/MenuBuild.swift` — delegate hooks + classic `buildMenu` +
  live-activity row + countdown ticker (lines 1696–1787, 2011–2033)
- Create: `app/MenuUsableFirst.swift` — `AccountSection`, classification
  helpers, `buildUsableFirstMenu`, `lastSwapItem` (1789–2009)
- Create: `app/MenuStatusRows.swift` — status/heartbeat colors + rows
  (2035–2112)
- Create: `app/MenuAccounts.swift` — account row + submenu dispatch
  (2114–2184) + per-provider submenu builders (2456–2602) + `detailLines` +
  `providerDisplayName` (2604–2708)
- Create: `app/MenuFormatting.swift` — plan/price/date/quota formatting
  (2186–2454) + coupon helpers (2845–2917) + `formatUpdated` (2944–2967)
- Create: `app/MenuFooter.swift` — footer + settings submenus (2710–2798)
- Create: `app/MenuRowFactory.swift` — `titleItem`…`separatorRow`
  (2800–2843, 2919–2943)
- Delete: `app/TokenStatusBar.swift` (empty after this move)

**Interfaces:**
- Produces: unchanged method names, now internal:
  `buildMenu(into:)`, `buildUsableFirstMenu(...)`, `accountItem(...)`,
  `buildAccountSubmenu` dispatch (`submenuRow`), `detailLines(_:) -> [String]`
  (exact existing signatures — read them at the cited lines when moving),
  `t(_:)`, row factories `titleItem/headerItem/groupHeaderItem/bulletItem/
  infoItem/warningItem/actionItem/submenuRow/separatorRow`.

- [ ] **Step 1: Move one file range at a time, typecheck between moves**
- [ ] **Step 2: Delete the now-empty `TokenStatusBar.swift`**
- [ ] **Step 3: Full build + relaunch + visual check**

```bash
bash build.sh
```

Then relaunch per AGENTS.md and visually verify: menu opens, both layouts
(classic and usable-first via Settings), one submenu per provider, language
switch works.

- [ ] **Step 4: Commit (one commit per extracted file, message pattern:)**

```bash
git commit -m "Split menu construction into MenuBuild.swift"   # etc. per file
```

### Task 1.6: Update stale docs

**Files:**
- Modify: `README.md:173`, `README.ko.md:169` (both claim a one-file app),
  `AGENTS.md` if it mentions the single file.

- [ ] **Step 1: Update the build/architecture wording to "swiftc compiles
  `app/*.swift`"**
- [ ] **Step 2: Commit**

```bash
git add README.md README.ko.md AGENTS.md
git commit -m "Document the multi-file Swift app layout"
```

---

## Phase 2 — Swift characterization harness

The app has zero tests. Before any behavior-affecting Swift change (Phase 3),
pin current behavior.

### Task 2.1: test.sh + first characterization tests

**Files:**
- Create: `test.sh` (repo root)
- Create: `app/Tests/TestMain.swift`
- Create: `app/Tests/fixture-status.json`

**Interfaces:**
- Consumes: everything in `app/*.swift` except `AppEntry.swift`.
- Produces: `TestMain.expect(_:_:)` used by all later Swift tests; the
  fixture file used by Phase 3 rendering tests.

- [ ] **Step 1: Write `test.sh`**

```bash
#!/usr/bin/env bash
# Compile and run the Swift characterization tests (excludes the @main app).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DIR/build"
SOURCES=()
for f in "$DIR"/app/*.swift; do
  [[ "$(basename "$f")" == AppEntry.swift ]] && continue
  SOURCES+=("$f")
done
swiftc -parse-as-library -framework Cocoa -framework SwiftUI \
  "${SOURCES[@]}" "$DIR"/app/Tests/*.swift -o "$DIR/build/swift-tests"
exec "$DIR/build/swift-tests"
```

`chmod +x test.sh`

- [ ] **Step 2: Write the runner + decode characterization**

`app/Tests/TestMain.swift`:

```swift
import Foundation

@main
struct TestMain {
    static var failures = 0
    static func expect(_ cond: Bool, _ label: String) {
        if cond { print("ok - \(label)") }
        else { failures += 1; print("FAIL - \(label)") }
    }

    static func main() {
        testStatusDecode()
        testFormatting()
        if failures > 0 { print("\(failures) FAILURES"); exit(1) }
        print("all swift tests passed")
    }

    static func fixtureURL() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .appendingPathComponent("fixture-status.json")
    }

    static func testStatusDecode() {
        let data = try! Data(contentsOf: fixtureURL())
        let p = try! JSONDecoder().decode(StatusPayload.self, from: data)
        expect(p.accounts.count == 2, "fixture has 2 accounts")
        expect(p.accounts[0].provider == "codex", "provider decodes")
        expect(p.accounts[0].windows?.first?.kind == "5h", "window kind decodes")
        expect(p.headline?.used_pct != nil, "headline decodes")
        expect(p.accounts[1].state?.usable != nil, "state decodes")
    }

    static func testFormatting() {
        // Characterize current outputs of pure helpers. Read the real
        // signatures in MenuFormatting.swift and assert what they return
        // TODAY for representative inputs (this pins behavior; it does not
        // define desired behavior). Cover at least: normalizePlan,
        // planPrice, shortMonthDay, formatUpdated, endSoonBadge,
        // couponEndsSoon. Instantiate the delegate: AppDelegate() is a
        // plain NSObject subclass and safe off the run loop.
        let d = AppDelegate()
        _ = d // add expect(...) lines per helper
    }
}
```

(The `testFormatting` body is filled in this same task — the field names and
exact expected strings come from running the helpers once and freezing the
output. That freeze IS the characterization.)

- [ ] **Step 3: Write `app/Tests/fixture-status.json`**

A synthetic payload — no real emails/ids — covering the decode surface:

```json
{
  "generated_at": "2026-07-31T09:00:00+09:00",
  "account_count": 2,
  "heartbeat": {"status": "ok", "next": "2026-07-31T09:05:00+09:00", "accounts": 2, "failed": 0},
  "headline": {"provider": "codex", "kind": "5h", "used_pct": 61.0,
               "reset_at_epoch": 1785400000, "severity": "warning"},
  "accounts": [
    {"id": 1, "provider": "codex", "email": "a@example.com", "plan": "plus",
     "status": "active",
     "windows": [{"kind": "5h", "used_pct": 61.0, "reset_at_epoch": 1785400000,
                  "severity": "warning", "is_active": true, "source": "api"}],
     "state": {"auth": "ok", "subscription": "paid", "quota": "warning",
               "usable": true, "binding_window": "5h"}},
    {"id": 2, "provider": "kimi", "email": "b@example.com", "plan": "coding-plan",
     "status": "active",
     "windows": [{"kind": "weekly", "used_pct": 12.5, "label": "GLM-4.7",
                  "reset_at_epoch": 1785900000, "source": "api"}],
     "state": {"auth": "ok", "subscription": "paid", "quota": "ok",
               "usable": true, "binding_window": "weekly"}}
  ],
  "last_swap": {"provider": "codex", "from": "a@example.com",
                "to": "c@example.com", "at": "2026-07-30T22:00:00+09:00",
                "at_epoch": 1785358800}
}
```

Adjust field names to match `Models.swift` exactly (the structs are the
source of truth; the decode test fails loudly on a mismatch).

- [ ] **Step 4: Run and freeze**

Run: `bash test.sh`
Expected: `all swift tests passed`

- [ ] **Step 5: Commit**

```bash
git add test.sh app/Tests/
git commit -m "Add Swift characterization test harness"
```

---

## Phase 3 — Windows-first rendering in the app

Why now: after Phase 5, migrated providers stop filling the per-provider flat
fields in `status.json` (`daily_quota_remaining_percent`,
`monthly_period_end`, `limited_user_reset_date`, …). The six per-provider
submenu builders read exactly those fields, so they must be replaced by a
single windows-driven builder **before** the backend migration starts.

### Task 3.1: One generic account submenu

**Files:**
- Modify: `app/MenuAccounts.swift` — replace `buildCodexSubmenu`,
  `buildClaudeSubmenu`, `buildGrokSubmenu`, `buildAntigravitySubmenu`,
  `buildCopilotSubmenu`, `buildDevinSubmenu` and the dispatch switch with one
  `buildAccountSubmenu(_ acct: Account) -> NSMenu`
- Modify: `app/Tests/TestMain.swift` — submenu-content characterization
- Modify: `app/Tests/fixture-status.json` — grow to one account per legacy
  provider (6) + kimi, each with representative `windows`, `state`, `plan`

**Interfaces:**
- Consumes: `statusGroup` and `limitSessionGroup` (the already-shared
  builders at pre-split lines 2499/2521), `detailLines`, `GaugeRowView`.
- Produces: `buildAccountSubmenu(_:) -> NSMenu` composed of, in order:
  `statusGroup` rows → one gauge row per `windows[]` entry →
  `limitSessionGroup` → `detailLines` bullets → account actions
  (swap/reconnect/delete, unchanged). Also a pure helper
  `submenuSummary(_ acct: Account) -> [String]` returning the row titles in
  order, used by tests.

- [ ] **Step 1: Write the failing characterization test**

Before touching the builders, add to `TestMain`:

```swift
static func testSubmenuSummaries() {
    let data = try! Data(contentsOf: fixtureURL())
    let p = try! JSONDecoder().decode(StatusPayload.self, from: data)
    let d = AppDelegate()
    for acct in p.accounts {
        let lines = d.submenuSummary(acct)
        expect(!lines.isEmpty, "\(acct.provider) submenu has rows")
        expect(lines.allSatisfy { !$0.contains("nil") },
               "\(acct.provider) has no nil leakage")
    }
}
```

Run: `bash test.sh` — FAILS (`submenuSummary` undefined).

- [ ] **Step 2: Implement `submenuSummary` + `buildAccountSubmenu`**

`submenuSummary` produces the ordered row titles; `buildAccountSubmenu`
renders them through the row factories. Then delete the six per-provider
builders and point the dispatch site (pre-split 2114–2184) at the generic
builder. Provider-specific information that only lived in flat fields
(codex credits, xai billing dates, copilot SKU dates) must instead come from
`windows[]` labels and `detailLines` — if a piece of information has no
surviving source yet, keep reading its flat field here and note it; Task 5.x
for that provider must emit it as a window `label` or `state` field, and this
file drops the flat read in the same commit as that migration.

- [ ] **Step 3: Run tests**

Run: `bash test.sh` → all pass. `python3 -m pytest backend -q` → 357 passed.

- [ ] **Step 4: Build, relaunch, visually compare each provider's submenu
  against the pre-change app** (differences allowed only where noted in the
  commit message)

- [ ] **Step 5: Commit**

```bash
git add app/MenuAccounts.swift app/Tests/
git commit -m "Render account submenus from declared windows"
```

---

## Phase 4 — Backend: parity harness + protocol extension

### Task 4.1: Golden window-parity harness

**Files:**
- Create: `backend/test_migration_parity.py`
- Create: `backend/fixtures/golden/` (one JSON per provider, generated)

**Interfaces:**
- Produces: `capture_golden(provider, snap)` / `assert_parity(provider,
  adapter_snapshot)` used by every Task 5.x. Golden files freeze, per
  provider: `status.normalize_windows(provider, snap)` output AND the
  history keys from `window_history.timed_windows` + `drop_windows`, for a
  representative legacy column-snapshot.

- [ ] **Step 1: Write the harness**

```python
"""Golden parity for the legacy->adapter migration.

For each legacy provider we freeze (a) the windows[] the legacy column
branches produce and (b) the history keys, from a representative snapshot.
The provider's adapter must reproduce both through the declared path.

Regenerate goldens ONLY before a provider's migration starts:
  GOLDEN_UPDATE=1 python3 -m pytest backend/test_migration_parity.py -q
"""
import json, os, unittest

os.environ.setdefault("AGENT_POOL_DB", "/tmp/parity.db")  # match conftest style
import status
import window_history

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "golden")


def _strip_volatile(windows):
    # as_of/source vary per run; parity is about shape + numbers + keys.
    out = []
    for w in windows:
        out.append({k: v for k, v in sorted(w.items()) if k not in ("as_of",)})
    return out


def capture_or_compare(name, value):
    path = os.path.join(GOLDEN_DIR, name + ".json")
    if os.environ.get("GOLDEN_UPDATE"):
        os.makedirs(GOLDEN_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump(value, f, indent=2, sort_keys=True)
        return value
    with open(path) as f:
        return json.load(f)


class ParityCase(unittest.TestCase):
    """Subclass per provider in Task 5.x:

    provider = "devin"
    legacy_snap = {...columns...}       # from the provider's existing test
    def adapter_snapshot(self): ...     # run providers/<name>.to_snapshot
    """
    provider = None

    def test_windows_parity(self):
        if self.provider is None:
            self.skipTest("base")
        golden = capture_or_compare(
            self.provider + "_windows",
            _strip_volatile(status.normalize_windows(self.provider,
                                                     self.legacy_snap)))
        got = _strip_volatile(
            status.normalize_windows(self.provider, self.adapter_snapshot()))
        self.assertEqual(golden, got)


if __name__ == "__main__":
    unittest.main()
```

(Extend with the history-key assertion the same way, using
`window_history.timed_windows` — same capture/compare shape. The
`legacy_snap` fixtures come from the provider's existing tests:
`test_claude_usage.py`, `test_copilot_poll.py`, `test_agy_usage.py`,
`test_status_windows.py` already build exactly these dicts — copy, don't
invent.)

- [ ] **Step 2: Run (base class skips)**

Run: `python3 -m pytest backend/test_migration_parity.py -q`
Expected: `1 skipped` (or passes trivially)

- [ ] **Step 3: Commit**

```bash
git add backend/test_migration_parity.py
git commit -m "Add golden parity harness for provider migration"
```

### Task 4.2: Adapter protocol — oauth hooks

**Files:**
- Modify: `backend/providers/__init__.py`
- Modify: `backend/oauth.py:712-728` (registries), `917-926` (`BROWSER_FLOWS`)
- Test: `backend/test_providers.py` (extend)

**Interfaces:**
- Produces (new optional module attributes an adapter may define):
  `LOGIN` (callable), `REFRESH` (callable), `BROWSER_FLOW` (dict, same shape
  as `oauth.BROWSER_FLOWS` values), `CAPS` (frozenset of {"heartbeat",
  "swap"}), `PLAN_LABEL` (callable `snap -> str|None`),
  `EXTRA` (callable `snap -> dict|None`).
- Produces (registry accessors): `providers.login_funcs() -> dict`,
  `providers.refresh_funcs() -> dict`, `providers.browser_flows() -> dict`,
  `providers.caps(name) -> frozenset`, `providers.hook(name, attr) ->
  callable|None`.
- Produces (oauth): `oauth.resolve_login(provider)`,
  `oauth.resolve_refresh(provider)`, `oauth.known_providers()` — legacy dict
  first, registry second, exactly the `poller.resolve_poller` pattern. The
  registry import inside `oauth.py` is **function-local** (adapters'
  `util.py` imports `oauth`; a top-level back-import would cycle).

- [ ] **Step 1: Write failing tests** (in `test_providers.py`: a fake module
  with `LOGIN`/`REFRESH`/`CAPS` registered via `register()`; assert the
  accessors surface them and `oauth.resolve_login` finds them after
  `providers.reset_cache()`)
- [ ] **Step 2: Run** → FAIL (attributes unknown)
- [ ] **Step 3: Implement** — accessors mirror `pollers()` (iterate
  `load()`, `getattr(mod, "LOGIN", None)`); `register()` validates `CAPS ⊆
  {"heartbeat", "swap"}` and callables when present; `oauth`'s three lookup
  sites route through the new resolvers (all callers of `LOGIN_FUNCS[...]`,
  `REFRESH_FUNCS[...]`, `PROVIDERS`, `BROWSER_FLOWS[...]` — grep them)
- [ ] **Step 4: Run** → pass; full suite green
- [ ] **Step 5: Commit**

```bash
git add backend/providers/__init__.py backend/oauth.py backend/test_providers.py
git commit -m "Resolve login and refresh through the adapter registry"
```

---

## Phase 5 — Migrate the six legacy providers

One task per provider, easiest first:
**5.1 devin → 5.2 copilot → 5.3 xai → 5.4 antigravity → 5.5 codex → 5.6 claude.**

Every task follows the same recipe (spelled out once here, then per-task
specifics). "Move" means cut from the source file and paste into the adapter
module — the code already exists and is under test; do not rewrite it.

**Migration recipe (applies to each Task 5.x):**

1. **Golden first.** Add `class <Name>Parity(ParityCase)` to
   `test_migration_parity.py` with `legacy_snap` copied from the provider's
   existing test fixtures, run once with `GOLDEN_UPDATE=1` **before touching
   any code**, and commit the golden JSON.
2. **Create `backend/providers/<name>.py`:**
   - `PROVIDER = "<name>"`; `AUTH = util.AUTH_OAUTH` (devin:
     `util.AUTH_API_KEY`).
   - Move the poll body from `poller.py` (`poll_devin` 798, `poll_copilot`
     628, `poll_xai` 338, `poll_antigravity` 484, `poll_codex` 118,
     `poll_claude` 216 — pre-migration line numbers) into a pure
     `to_snapshot(body)` mapper + `poll(conn, account, token)`, the
     kimi/kiro shape (`providers/kimi.py:74-186` is the template).
   - Replace the final `store.save_snapshot(...)` column payload with
     `util.snapshot([...windows...], plan=..., raw={...})`. The window list
     reproduces exactly what the provider's `normalize_windows` branch
     computed (branch lines: devin 539–548, copilot 534–538, xai 523–533,
     antigravity 548–556, codex/claude 503–522) — **same `kind` strings, so
     history keys stay continuous**. Non-window per-provider facts the Swift
     app still needs go into `raw` (surfaced by `EXTRA`) or window `label`s.
   - Move the provider's oauth functions (`login_*`, `refresh_*`,
     `_authorize_*` — oauth.py 239–705, 738–915) into the module as
     `LOGIN`/`REFRESH`/`BROWSER_FLOW`. Shared dance helpers stay in
     `oauth.py`.
   - Define `CAPS`: codex/claude `{"heartbeat", "swap"}`, antigravity
     `{"heartbeat"}`, others `frozenset()`.
   - Move that provider's `plan_label` branch (status.py 723–773) into
     `PLAN_LABEL`, and its `provider_extra` branch (status.py 325–385, xai +
     antigravity only) into `EXTRA`.
3. **Delete the legacy entries:** the provider's key in `poller.POLLERS`,
   `oauth.LOGIN_FUNCS`/`REFRESH_FUNCS`/`BROWSER_FLOWS`, and its moved
   branches. **Leave the `normalize_windows`/`timed_windows`/`drop_windows`
   branches in place until Task 6.1** — old DB rows still flow through them.
4. **Retarget the provider's existing tests** (`test_claude_usage.py`,
   `test_copilot_poll.py`, `test_agy_usage.py`, parts of
   `test_onboarding.py`, `test_refresh_windows.py`) at the adapter module —
   the assertions stay, the import path changes.
5. **Run:** parity test green, full suite green, then a live smoke:
   `python3 backend/pool.py poll` and check `secrets/status.json` shows the
   provider's windows.
6. **Swift follow-through:** if Task 3.1 left a flat-field read for this
   provider, move that data into the adapter's windows/`EXTRA` and delete
   the flat read in `app/MenuAccounts.swift` now. `bash test.sh` green.
7. **Commit** (message pattern):

```bash
git commit -m "Migrate devin polling to a provider adapter"
```

**Per-task specifics:**

### Task 5.1: devin
`AUTH_API_KEY`; windows: `daily` (from `daily_quota_remaining_percent`,
`remaining_pct` semantics, `boundary` per the 539–548 branch) + `weekly` if
present. No oauth move (devin has none — `login_devin` oauth.py:687 becomes
`LOGIN`). Special case: none in `_poll_one`.

### Task 5.2: copilot
Windows from the 534–538 branch (`limited_user_reset_date` → monthly-style
window). Keep the ended-subscription handling recently added (see commit
`b203a67`) — its tests in `test_copilot_poll.py` move with it.

### Task 5.3: xai
Windows from 523–533 (`monthly_period_end` billing window). `EXTRA` takes the
xai branch of `provider_extra` (status.py:339-343).

### Task 5.4: antigravity
`EXTRA` takes status.py:344-384. Also move the antigravity credential-reload
special case out of `poller._refresh_if_needed` (poller.py:1053) into the
adapter's `REFRESH`, and the heartbeat branches (heartbeat.py:201,204,219)
stay but are gated by `CAPS` in Task 6.2. `agy_usage.py` becomes an import of
the adapter module (or moves into `providers/antigravity.py` if under 300
lines combined).

### Task 5.5: codex
Largest poll body (poller.py:118-215). The credit-baseline special case in
`_poll_one` (poller.py:1091) moves into the adapter's `poll`. Codex credits
display (status.py:932) moves to `EXTRA`. `CAPS = {"heartbeat", "swap"}`.

### Task 5.6: claude
The `_fable` window helper (window_history.py:99-109) reproduces inside the
adapter's window emission (parity test proves it). `CAPS = {"heartbeat",
"swap"}`. After this task, `poller.POLLERS` and `oauth.LOGIN_FUNCS` /
`REFRESH_FUNCS` / `BROWSER_FLOWS` are **empty dicts**.

---

## Phase 6 — Legacy teardown + registry-driven remainder

### Task 6.1: Quarantine the legacy read branches

**Files:**
- Create: `backend/legacy_windows.py`
- Modify: `backend/status.py:487-566` (`normalize_windows`),
  `backend/window_history.py:189-271` (`timed_windows`/`drop_windows`),
  delete `_fable`/`_agy_usage_windows` (window_history.py:99-136)
- Modify: `backend/store.py:306-320` (`save_snapshot` fields shrink to the
  generic subset: `status`, `status_message`, `plan`, `raw_json`, `source` +
  whatever generic rate-limit fields non-migrated call sites still pass —
  grep callers first), SCHEMA comments mark provider columns deprecated
  (columns stay: historical rows)

**Interfaces:**
- Produces: `legacy_windows.normalize(provider, snap)`,
  `legacy_windows.timed(provider, snap)`, `legacy_windows.drop(provider,
  snap)` — verbatim moves of the elif chains, called **only** when
  `"windows" not in raw_json` (pre-migration DB rows). Module docstring
  states the deletion condition: once every account's snapshots within the
  history scan window are declared-shaped, delete this file.

- [ ] **Step 1: Move the chains; the three call sites become
  `declared-first, legacy_windows fallback`**
- [ ] **Step 2: Full suite green** (existing window tests exercise the
  fallback path via old-shaped fixtures — they must keep passing unchanged)
- [ ] **Step 3: Commit**

```bash
git add backend/legacy_windows.py backend/status.py backend/window_history.py backend/store.py
git commit -m "Quarantine legacy window branches for old snapshots"
```

### Task 6.2: Registry-driven remainder

**Files:**
- Modify: `backend/pool.py:99` (onboarding gate: route by
  `providers.auth_kind()` — oauth → browser flow, api_key → key prompt,
  local_file/none → plain `add`), `pool.py:75,95,102,163,242,262`
- Modify: `backend/heartbeat.py:31` (`PROVIDERS` → providers with
  `"heartbeat" in caps`), `backend/swap.py:36` (`SWAP_PROVIDERS` → `"swap"
  in caps`; the codex/claude-specific swap mechanics stay put)
- Modify: `backend/dashboard.py:382` (`PROV` list → rendered from the
  payload's actual providers, registry order first)
- Modify: `backend/status.py` — `plan_label` (723–773) and `provider_extra`
  (325–385) become `providers.hook(name, "PLAN_LABEL")` /
  `hook(name, "EXTRA")` lookups with the current generic fallback;
  `HEARTBEAT_PROVIDERS` (line 11) → caps lookup; `account_state` (797–888)
  branches: migrate the per-provider conditions onto `state`-relevant
  declared data — if a branch cannot be expressed generically, move it into
  that provider's adapter as an optional `ACCOUNT_STATE` hook (same pattern
  as `PLAN_LABEL`; add to `register()` validation)

- [ ] **Step 1: One failing test per site** (extend `test_onboarding.py`,
  `test_lifecycle.py`, `test_status_windows.py`: a registered fake provider
  with caps/hooks appears in heartbeat selection, onboarding routing, plan
  labels)
- [ ] **Step 2: Implement site by site, committing per file:**

```bash
git commit -m "Route onboarding by adapter auth kind"       # pool.py
git commit -m "Select heartbeat and swap providers by capability"  # heartbeat.py, swap.py
git commit -m "Drive dashboard provider order from the payload"    # dashboard.py
git commit -m "Resolve plan labels and extras through adapter hooks"  # status.py
```

### Task 6.3: Quantitative audit

**Files:**
- Create: `backend/test_structure.py`

- [ ] **Step 1: Write the audit as a test so it can't regress**

```python
"""Structural guarantees from the 2026-07-31 refactor plan."""
import os, re, unittest

BACKEND = os.path.dirname(os.path.abspath(__file__))
PIPELINE = ["poller.py", "status.py", "window_history.py", "oauth.py", "store.py"]
PROVIDER_BRANCH = re.compile(r'provider\s*(?:==|in)\s*[("\']')


class StructureTest(unittest.TestCase):
    def test_no_provider_branches_in_pipeline(self):
        for fname in PIPELINE:
            src = open(os.path.join(BACKEND, fname)).read()
            hits = [ln for ln in src.splitlines() if PROVIDER_BRANCH.search(ln)]
            self.assertEqual(hits, [], f"{fname} still branches on provider")

    def test_module_size_ceiling(self):
        for fname in os.listdir(BACKEND):
            if fname.endswith(".py") and not fname.startswith("test_"):
                n = len(open(os.path.join(BACKEND, fname)).readlines())
                self.assertLessEqual(n, 800, f"{fname} is {n} lines")


if __name__ == "__main__":
    unittest.main()
```

Add the Swift-side ceiling to `test.sh` (before the compile):

```bash
for f in "$DIR"/app/*.swift; do
  n=$(wc -l < "$f")
  case "$(basename "$f")" in Localization.swift) max=1200;; *) max=600;; esac
  if [ "$n" -gt "$max" ]; then echo "$f is $n lines (max $max)"; exit 1; fi
done
```

- [ ] **Step 2: Run; fix any file over the ceiling by splitting along the
  Phase 1 boundaries**
- [ ] **Step 3: Commit**

```bash
git add backend/test_structure.py test.sh
git commit -m "Enforce structural ceilings from the refactor plan"
```

---

## Phase 7 — Final verification & docs

### Task 7.1: Full acceptance run

- [ ] **Step 1:** `python3 -m pytest backend -q` → all green (count grows
  past 357; record the number)
- [ ] **Step 2:** `bash test.sh` → all swift tests passed
- [ ] **Step 3:** `bash build.sh` then `bash build.sh --dmg` → both succeed
- [ ] **Step 4:** Quit + relaunch per AGENTS.md; visually verify: both menu
  layouts, every provider submenu, language switch, Poll Now, Add New Agent
  entries for each auth kind
- [ ] **Step 5:** Live poll smoke: `python3 backend/pool.py poll` →
  `secrets/status.json` has `windows[]` for every active account and the
  dashboard (`python3 backend/pool.py dashboard`) renders history continuity
  across the migration date (same window keys before/after)

### Task 7.2: Update the design doc & README

**Files:**
- Modify: `docs/superpowers/specs/2026-07-31-provider-adapter-sync-design.md`
  — §6 "Deliberately not done" first bullet is now done; update Status line
- Modify: `README.md` / `README.ko.md` — architecture section (adapter
  registry, multi-file app, `test.sh`)

- [ ] **Step 1: Edit; commit**

```bash
git add docs/superpowers/specs/2026-07-31-provider-adapter-sync-design.md README.md README.ko.md
git commit -m "Document the completed adapter migration"
```

---

## Execution order & PR slicing

Each phase is a natural PR (Phase 5 can be one PR per provider if review
size matters). Every PR: suite green + `.dmg` builds first (AGENTS.md).

| PR | Contents | Risk |
|----|----------|------|
| 1 | Phase 0 (baseline commits) | none — already-working code |
| 2 | Phase 1 + 2 (Swift split + harness) | low — pure moves |
| 3 | Phase 3 (windows-first rendering) | medium — UI change, characterized |
| 4 | Phase 4 (parity harness + oauth hooks) | low |
| 5–10 | Phase 5 per provider | medium — golden-gated |
| 11 | Phase 6 (teardown + registry) | medium |
| 12 | Phase 7 (verify + docs) | none |
