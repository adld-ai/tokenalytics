# Prompt — Phase M1: pool, routing, single writer

You are working in `/Users/tonylee/solo/token-bar` on the TokenBar v2
refactor. Phase M0 is complete (byte-verbatim relay proven, budgets
met). Read first:

1. `docs/superpowers/plans/v2-prompts/README.md`
2. `docs/superpowers/specs/2026-08-01-tokenbar-v2-architecture.md` —
   binding: §5.2–5.5, S6–S10, S14–S15, S19, S24, §6, R11/R16
3. `docs/superpowers/plans/2026-08-01-tokenbar-v2-refactor.md` §6

## Objective

The core becomes the single writer: accounts, credentials, routing
decisions, and state all live behind its API. The v1 race class
(delete-resurrection, FK-after-delete, stale-list rewrite) becomes
impossible by construction.

## Tasks

1. `internal/state`: SQLite via `modernc.org/sqlite` (pure Go).
   Carry v1 schema (`accounts`, `tokens`, `lifecycle_events`,
   `refresh_log`, `window_history`) + `schema_version`. WAL,
   `synchronous=NORMAL`, async single-writer queue so the request path
   never blocks on the DB (S6), nightly checkpointed backup with 7-day
   retention (R11).
2. `internal/pool`: account CRUD. Importers: (a) v1 `secrets/pool.db`,
   (b) cliproxy `~/.cli-proxy-api/*.json`. Dry-run by default printing
   the identity mapping; identity keyed on upstream account id, never
   email (R16).
3. `internal/routing`: policies `pin` (default, S9) and `fill-first`;
   cooldown table with TTL eviction (S10); failover only on hard
   signals (429-quota / 401 / 403), one retry max, session-initial
   requests only — continuity markers (`previous_response_id`,
   conversation/session ids) disable failover (S19); routing table
   updates via atomic swap (S6).
4. `internal/api`: bearer-token auth on all `/api` routes (S14);
   `POST /api/v1/accounts`, `DELETE /api/v1/accounts/{id}`,
   `POST /api/v1/routing/{provider}/pin`, `GET /api/v1/state`.
   Deny-by-default payload schema; CI test scanning every emitted
   payload for token-shaped strings (S15).
5. Regression tests proving the v1 scenarios cannot recur:
   delete racing a state read, snapshot write for a deleted id,
   stale-list payload rewrite after delete. Frame each as a test that
   would have failed in v1 and cannot fail here (single writer).
6. Wire the M0 relay to the routing table (replace the hardcoded
   credential with pool-routed credentials).

## Constraints

- No OAuth login flows yet (M2); import-only for credentials.
- No keychain yet (M2) — but isolate token access behind a `vault`
  interface so M2 is a drop-in.
- `DELETE` response must be reflected in `GET /api/v1/state` in
  < 50 ms (measure in test).
- Do not touch `backend/` or `app/`.

## Deliverables

1. Green `go test ./...` including the v1-race regression suite.
2. Importer verified against the real `secrets/pool.db` and
   `~/.cli-proxy-api` (dry-run output in the report).
3. Delete→state propagation measurement.
4. Final report (Korean): architecture notes, test matrix, Go/No-Go
   for Phase M2.
