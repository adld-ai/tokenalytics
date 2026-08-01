# Prompt — Phase M0: relay spike

You are working in `/Users/tonylee/solo/token-bar` on the TokenBar v2
refactor. Phase P is complete (v1 patches committed, heartbeat retired,
daemon inventory written into spec §15.3). Read first:

1. `docs/superpowers/plans/v2-prompts/README.md`
2. `docs/superpowers/specs/2026-08-01-tokenbar-v2-architecture.md` —
   binding clauses: S1–S6 (dumb pipe), S17 (verbatim headers), §12
   (budgets), plan §5 (this phase)
3. `docs/superpowers/plans/2026-08-01-tokenbar-v2-refactor.md` §3, §5

## Objective

Prove the risk-minimized core premise: a Go binary relays one real
codex CLI request byte-verbatim, stream intact, within budget. If this
fails, v2 stops here cheaply.

## Tasks

1. Scaffold `core/` Go module per plan §3 layout:
   `cmd/tokenbar-core/main.go` (config: port `9417`, upstream base
   URL, token file path), `internal/relay/`.
2. Implement the relay as a custom reverse proxy — do NOT use
   `httputil.ReverseProxy` defaults (it appends `X-Forwarded-For`,
   violating S17). Requirements:
   - forward every client header unchanged; replace ONLY the
     `Authorization` value with the configured account token;
   - never add `X-Forwarded-For` / `Via` / `Forwarded`;
   - stream responses with flush per chunk; ≤ 64 KB in-flight buffer
     per direction (S5);
   - downstream disconnect cancels the upstream request via context
     (§12.3 goroutine-leak safeguard).
3. Soak harness `core/cmd/soak` (or script): replays recorded codex
   request shapes — streaming, non-streaming, and abort-mid-stream —
   against the relay.
4. Stream-integrity test: for identical recorded request fixtures,
   byte-diff `direct-to-upstream` vs `proxied` responses. Must be
   identical (excluding hop-by-hop headers, which must be listed
   explicitly in the test).
5. Add `goleak` verification to the streaming tests. Measure idle
   RSS/CPU and under 100 sequential streams; append results to spec
   §12.1's measured-baselines table.
6. Live check: point a real codex CLI at the core
   (`openai_base_url = http://127.0.0.1:9417/v1`) and complete one
   turn end-to-end.

## Constraints

- No DB, no account pool, no routing — one configured credential only.
- No translation/parsing of request or response bodies (S1/S2).
- Do not touch `backend/` (frozen) or `app/` (M3).
- No vendored third-party proxy code (S3).

## Deliverables

1. `core/` module with tests green (`go test ./...`, goleak clean).
2. Soak report appended to spec §12.1 (RSS/CPU idle + load vs §12.2
   budgets; require ≥ 50% headroom).
3. Stream-integrity test results (byte-diff clean).
4. Final report (Korean): what was built, measurements, and a
   Go/No-Go for Phase M1 with any premise violations discovered.
