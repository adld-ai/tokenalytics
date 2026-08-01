# Prompt — Phase M2: auth vault + quota engine

You are working in `/Users/tonylee/solo/token-bar` on the TokenBar v2
refactor. Phase M1 is complete (single-writer pool + routing live).
Read first:

1. `docs/superpowers/plans/v2-prompts/README.md`
2. `docs/superpowers/specs/2026-08-01-tokenbar-v2-architecture.md` —
   binding: S4, S16, S20–S22, §5.4, §12.3, §14
3. `docs/superpowers/plans/2026-08-01-tokenbar-v2-refactor.md` §7
4. v1 reference code to port FROM: `backend/providers/*.py`,
   `backend/oauth.py`, `backend/window_history.py` (read-only)

## Objective

Credentials sealed in Keychain; quota state harvested from real
traffic with zero enforcement-risky scheduled behavior.

## Tasks

1. **Keychain vault (S16).** Implement the `vault` interface from M1
   against macOS Keychain (`security` framework via cgo-free wrapper
   or `/usr/bin/security`); DB stores references only. Migration:
   re-encrypt all imported token rows; verify with a DB dump that no
   plaintext token remains.
2. **OAuth/device flows.** Port per provider from v1 Python adapters
   to Go behind `POST /api/v1/accounts`: codex, claude, xai,
   antigravity (browser OAuth + loopback callback), copilot (device
   flow), devin/kimi (API key). The browser-flow UA exception is
   documented (spec §15.2) — do not "fix" it.
3. **Refresh-on-use (S21).** Singleflight per account; refresh at 80%
   of TTL; only when routing a request for that account. No scheduled
   refresh anywhere.
4. **Harvest (S4).** Tee tap on the relay for openai + anthropic:
   read-only observation of rate-limit headers and metered body
   fields; failures logged and dropped, never propagated. Port the
   window model semantics from v1 `window_history.py`/`status.py`
   including its test corpus as Go table tests.
5. **Idle poll (S22).** Interval ≥ 15 min, ±20% jitter, strictly
   serialized per provider, skip accounts with recent harvest,
   exponential backoff on 429. Single scheduler goroutine with a
   next-due heap; worker pool of 4 (§12.3). No heartbeat traffic of
   any kind (S20).
6. **State exposure.** Quota model surfaces in `GET /api/v1/state`
   (windows, reset times, reset credits) using the v1 payload shape
   plus `schema_version`.

## Constraints

- Quota model is display-only (advisory): routing MUST NOT read it
  (S4, §13.3). Enforce with an explicit package boundary test.
- v1 `backend/` remains read-only reference; do not patch it.

## Deliverables

1. Green tests; keychain verification (DB dump contains no token
   plaintext).
2. Harvest-vs-reality spot check: compare core quota numbers against
   provider dashboards for 2 accounts; record divergence.
3. Idle-poll cadence proof (log excerpt showing jitter + serialization).
4. Final report (Korean): ported-flow matrix per provider, harvest
   coverage, Go/No-Go for Phase M3.
