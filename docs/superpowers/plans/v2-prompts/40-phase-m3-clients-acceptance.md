# Prompt — Phase M3: clients + acceptance

You are working in `/Users/tonylee/solo/token-bar` on the TokenBar v2
refactor. Phase M2 is complete (vault + quota engine live). Read
first:

1. `docs/superpowers/plans/v2-prompts/README.md`
2. `docs/superpowers/specs/2026-08-01-tokenbar-v2-architecture.md` —
   binding: §5.5–5.6, S11–S13, S23, S25, §12 (budgets + observability),
   R9, R19, Q3
3. `docs/superpowers/plans/2026-08-01-tokenbar-v2-refactor.md` §8
4. `AGENTS.md` (build rules — they apply to every Swift change)

## Objective

Menu bar and browser panel live entirely on the core API; v1 backend
processes switched off; resource budgets proven over a 24 h soak.

## Tasks

1. **SSE.** `GET /api/v1/events`: per-client bounded channel (64),
   overflow → `resync` sentinel + disconnect, 250 ms coalescing flush,
   write timeouts (§12.3).
2. **Swift app rewrite of StatusLoader.** Replace file polling with:
   initial `GET /api/v1/state`, then SSE with jittered exponential
   backoff (1 s → 30 s cap). Delete/swap/reconnect/add become API
   calls (`DELETE /accounts/{id}`, `POST /routing/{provider}/pin`,
   reconnect endpoint). Delete the 30 s timer, all `Process`/
   `pool.py` plumbing, and every `AGENT_POOL_*` env line. Menu UI
   components (rows, gauges, badges) stay unchanged.
3. **Panel.** Core serves the browser panel; fold the window-history
   dashboard into it as a view fed by `window_history` tables (Q3).
4. **CLI shim** `cmd/tokenbar` (S11): health-check core (< 100 ms) →
   set provider base URL env/config → exec the real CLI; fall back to
   direct URL when unhealthy. Add `tokenbar doctor` (diagnose +
   restore direct mode, R9).
5. **Modes.** Per-provider `proxy` / `observe-only` / `disabled`
   (S23); global observer mode flag (S25).
6. **Watchdog (S13).** 3 core crashes in 60 s → rewrite CLI configs to
   direct endpoints + menu notification.
7. **Acceptance battery.** 24 h soak: RSS/CPU/goroutines logged
   hourly against §12.2 budgets; `/api/v1/health` wired to the menu
   warning badge; golden contract tests — Go payload schema fixtures
   decoded by the Swift test suite (R19); v1 launchd agents
   (`agentpool-poller`, `agentpool-heartbeat`) booted out with user
   approval and the menu verified fully live with zero v1 processes.

## Constraints

- Per `AGENTS.md`: build the app after Swift changes; build the
  `.dmg` before any PR; quit + relaunch the app after rebuilding.
- Any `bootout` / process kill requires explicit user approval.
- v1 `backend/` stays untouched until M4.

## Deliverables

1. Rebuilt + relaunched menu-bar app running against the core only.
2. 24 h soak report appended to spec §12.1 (budgets met or breach
   analysis).
3. Contract goldens + green Swift tests; `tokenbar doctor` demo.
4. Final report (Korean): deletion diffstat for the Swift rewrite,
   soak results, Go/No-Go for Phase M4.
