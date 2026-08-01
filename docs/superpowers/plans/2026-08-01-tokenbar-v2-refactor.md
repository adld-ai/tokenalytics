# TokenBar v2 — complete refactoring plan

Date: 2026-08-01
Status: approved direction, ready to execute
Spec: `docs/superpowers/specs/2026-08-01-tokenbar-v2-architecture.md`
(normative clauses S1–S26, risk register §10, resource budget §12,
enforcement analysis §14, alignment audit §15 — all binding here)

This plan is the executable companion to the spec. Every phase lists
tasks, touched files, and exit criteria. Clause references (S#) are
mandatory acceptance conditions, not guidelines.

## 1. Objective

Replace the v1 observer architecture (4 writers → SQLite → status.json
→ 30 s file polling) with a single-writer, proxy-in-the-loop core:

- one Go binary (`tokenbar-core`): byte-verbatim relay + account pool +
  routing + quota engine + management API/SSE
- one Swift menu bar app: thin SSE client (existing UI retained)
- zero file-rendezvous, zero credential-file rewriting, zero
  enforcement-risky traffic (heartbeat, metronome polling, fleet
  refresh all removed)

## 2. Non-negotiable constraints (from spec)

1. Single writer: only `tokenbar-core` touches state (§2, §13).
2. Dumb pipe: byte-verbatim relay; no translation layer (S1–S6).
3. Advisory quota: routing reacts only to real upstream signals
   (S7–S10).
4. Fail-open: CLI shim + automatic direct mode (S11–S13).
5. No evasion: verbatim headers, no cloaking/spoofing (S17–S18).
6. Continuity-safe failover (S19); no heartbeat (S20); refresh-on-use
   (S21); human-shaped idle polling (S22); per-provider modes (S23);
   observer-mode retreat (S25).
7. Resource budgets: core ≤ 60 MB idle / ≤ 150 MB p95, ≈ 0% idle CPU
   (§12).

## 3. Target repository layout

```
token-bar/
  core/                  # Go module: tokenbar-core
    cmd/tokenbar-core/   # main: listener, lifecycle, launchd integration
    cmd/tokenbar/        # CLI shim (S11) + management CLI
    internal/relay/      # byte-verbatim proxy (S1–S6, S17)
    internal/pool/       # accounts, credentials, keychain vault (S16)
    internal/routing/    # policies, cooldowns, failover (S7–S10, S19, S24)
    internal/harvest/    # request-path quota tap (S4), idle poll (S22)
    internal/api/        # management REST + SSE (§5.5, S14–S15)
    internal/state/      # SQLite store, payload schema, goldens
    internal/observe/    # health, pprof, decision log (§12.4)
  app/                   # Swift menu bar (existing; StatusLoader replaced)
  backend/               # v1 Python — frozen at M0, retired to legacy/ at M4
  docs/
```

## 4. Phase P — pre-flight (before any v2 code)

Prerequisite inventory and safety locks, per spec §15.3/§15.5.

| # | Task | Exit criteria |
|---|---|---|
| P1 | Commit the two uncommitted v1 safety patches (cmd_remove poll-lock, AGENT_POOL_HISTORY_DIR) | clean tree; pytest 393+ green |
| P2 | Retire heartbeat: `launchctl bootout gui/$(id -u)/com.tonye.agentpool-heartbeat`, remove plist, delete heartbeat-loop from docs | no `hi` traffic; menu heartbeat row shows "disabled" |
| P3 | Daemon inventory: identify what actually writes `~/solo/token-status-bar/secrets/status.json` (broken plist paths vs live writers); dump `launchctl list` for the three labels | written inventory appended to spec §15.3 |
| P4 | Choose the canonical data dir (recommend repo `secrets/` until v2's `~/.tokenbar`), fix or bootout the broken plists, stop cloud push (Q2) | one writer set, one data dir, documented |
| P5 | Snapshot backups: `pool.db` (WAL-checkpointed copy) + `status.json` + plists into `secrets/recovery/2026-08-01/` | restorable snapshot |

## 5. Phase M0 — relay spike (proof of the risk-minimized core)

Goal: one real codex request relayed through a Go binary with the
stream intact. No DB, no pool — one hardcoded credential.

Tasks:

1. `go mod init`; `cmd/tokenbar-core` with config (port, one upstream,
   token file path).
2. `internal/relay`: custom reverse proxy (NOT `httputil.ReverseProxy`
   default — XFF clause S17): verbatim header pass-through,
   `Authorization` value replacement only, streaming flush per chunk,
   ≤ 64 KB in-flight buffer (S5), ctx-cancel propagation (§12.3).
3. Soak harness: script replaying recorded codex CLI request shapes
   (streaming + non-streaming + abort-mid-stream).
4. Stream-integrity test: byte-diff upstream-direct vs proxied
   response for identical request fixtures (must be identical).
5. goleak on the test suite; RSS/CPU measured idle and under 100
   sequential streams; results appended to spec §12.1.

Exit criteria: codex CLI pointed at the core completes a real turn;
byte-diff clean; goleak clean; budgets from §12.2 met with ≥ 50%
headroom.

## 6. Phase M1 — pool, routing, single writer

Goal: the core owns accounts; delete/add/pin via API; v1 races become
impossible by construction.

Tasks:

1. `internal/state`: SQLite (modernc.org/sqlite), schema carried from
   v1 (`accounts`, `tokens`, `lifecycle_events`, `refresh_log`,
   `window_history`) + `schema_version`; async single-writer queue
   (S6); WAL, nightly backup job (R11).
2. `internal/pool`: account CRUD; v1 `pool.db` importer + cliproxy
   auth-dir importer (dry-run default, identity keyed on upstream
   account id — R16).
3. `internal/routing`: policies `pin` (default, S9), `fill-first`;
   cooldown table with TTL eviction (S10); failover on hard signals
   only, one retry, session-initial requests only (S7–S9, S19);
   atomic-swap routing table (S6).
4. `internal/api`: `POST/DELETE /api/v1/accounts`,
   `POST /api/v1/routing/{provider}/pin`, `GET /api/v1/state`;
   bearer auth (S14); deny-by-default payload schema + token-pattern
   CI scan (S15).
5. Regression tests codifying the v1 bug scenarios as impossible:
   delete-versus-poll, FK-after-delete, stale-list rewrite.

Exit criteria: all v1 race regression tests pass by construction;
delete reflected in `/state` in < 50 ms; importers verified against
real `pool.db` + `~/.cli-proxy-api`.

## 7. Phase M2 — auth vault + quota engine

Goal: credentials secured; quota state without enforcement-risky
traffic.

Tasks:

1. Keychain vault (S16): tokens sealed in macOS Keychain, DB holds
   references; migration re-encrypts v1-imported rows.
2. OAuth/device flows ported per provider from v1 adapters
   (codex, claude, xai, antigravity, copilot, devin, kimi), behind
   `POST /api/v1/accounts`; browser flows drive the loopback callback
   exactly as v1 (documented S18 exception).
3. Refresh-on-use (S21): singleflight per account, refresh at 80% TTL,
   only when routing a request for that account.
4. `internal/harvest`: tee tap for openai + anthropic headers/body
   meter (S4); window model ported from v1 `window_history.py`
   semantics with its test corpus.
5. Idle poll per S22: ≥ 15 min, ±20% jitter, serialized per provider,
   skip harvest-covered accounts, 429 backoff; single scheduler
   goroutine + worker pool of 4 (§12.3).

Exit criteria: quota visible for all v1 providers with zero scheduled
fleet traffic; keychain verified (no plaintext token in DB dump);
harvest vs provider dashboard spot-check within noise.

## 8. Phase M3 — clients + acceptance

Goal: menu bar and panel live on the API; v1 daemons can be switched
off per provider.

Tasks:

1. SSE: `/api/v1/events` with bounded per-client channels, `resync`
   sentinel, 250 ms coalescing (§12.3).
2. Swift app: `StatusLoader` → API client (`GET /state` + SSE,
   jittered backoff); delete/swap/reconnect/add become API calls;
   30 s timer, subprocess plumbing, and all `AGENT_POOL_*` env code
   deleted; menu UI components unchanged.
3. Browser panel served by core (Q3: window-history dashboard folded
   in as a panel view, data from `window_history` tables).
4. `cmd/tokenbar` CLI shim (S11): health-check → base-URL injection →
   exec real CLI; direct fallback; `tokenbar doctor` (R9).
5. Per-provider modes `proxy`/`observe-only`/`disabled` (S23) +
   global observer mode (S25).
6. Automatic direct mode watchdog (S13): 3 crashes/60 s → rewrite CLI
   configs direct + notify.
7. Acceptance battery: resource budgets §12.2 measured over 24 h soak;
   `/api/v1/health` budgets wired to menu warning badge; golden
   contract tests (Go schema → Swift decode, R19).

Exit criteria: v1 poller/heartbeat launchd agents booted out; menu
fully live with zero v1 backend processes; budgets green for 24 h.

## 9. Phase M4 — cutover & cleanup

Tasks:

1. `backend/` → `legacy/` (unmodified, for rollback R17); v1 launchd
   plists removed; cloud push plist removed (Q2).
2. App-generated launchd plist for `tokenbar-core` (Q1):
   `KeepAlive.SuccessfulExit=false`, `ThrottleInterval=10`.
3. Data unification: migrate to `~/.tokenbar` (`TOKENBAR_HOME`, §6);
   history import from v1 DB; shadow data dirs retired.
4. Docs sweep: README/CLAUDE.md/AGENTS.md rewritten for v2; spec §15.4
   matrix marked complete.

Exit criteria: one binary, one plist, one DB, one data dir; rollback
path (repoint base URL + relaunch legacy) rehearsed once.

## 10. Testing strategy

| Layer | What | When |
|---|---|---|
| Unit | routing, cooldowns, harvest parsers, payload schema | every phase |
| Regression | v1 race scenarios as impossible-by-construction | M1 |
| Stream integrity | byte-diff direct vs proxied fixtures | M0, then CI |
| Leak | goleak on all streaming tests | M0, then CI |
| Contract | Go payload goldens decoded by Swift tests | M3 |
| Soak | 24 h: RSS/CPU/goroutines within §12.2; no event storms | M3 |
| Security | token-pattern scan over all emitted payloads | M1, then CI |

## 11. Rollback strategy

- Any phase: repoint CLI base URL to provider direct (documented +
  `tokenbar doctor` automates).
- M4 and later: `legacy/` backend + saved plists (P5) restore v1 in
  minutes; v2 never writes to v1's DB.
- Observer mode (S25) is the permanent middle ground.

## 12. Risk → phase mapping (spec §10)

| Risk | Eliminated/capped in |
|---|---|
| R1 stream corruption | M0 integrity tests |
| R2, R18 | M0 (no translation, no vendoring) |
| R3, R19, R24 | M1 routing + S19 |
| R4, R14 | M2 harvest advisory-only |
| R5, R7, R15 | M1–M2 (S15–S16) |
| R9, R10, R13 | M3 shim + watchdog + soak |
| R11 | M1 backups + S6 |
| R15, R16, R17 | P + M4 |
| Ban vectors E1–E11 | P2 + M2 (S17–S26 throughout) |

## 13. Sequencing notes

- P is hours, not days; its inventory unblocks everything.
- M0 is deliberately tiny — its job is to fail cheap if the dumb-pipe
  premise is wrong.
- M1 and M2 are the bulk of the work; M3 is mostly deletion in the
  Swift app (the best kind of diff).
- No v1 feature work after M0 starts (spec §15.5).
