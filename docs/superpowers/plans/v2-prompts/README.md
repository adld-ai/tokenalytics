# TokenBar v2 — phase execution prompts

One prompt file per phase. Feed them to the coding agent in order;
each assumes the previous phase's exit criteria are met.

| File | Phase | Summary |
|---|---|---|
| `00-phase-p-preflight.md` | P | commit safety patches, retire heartbeat, daemon inventory, data-dir decision, backups |
| `10-phase-m0-relay-spike.md` | M0 | Go byte-verbatim relay spike + stream-integrity proof |
| `20-phase-m1-pool-routing.md` | M1 | pool, routing, single-writer store, account API |
| `30-phase-m2-vault-quota.md` | M2 | keychain vault, OAuth ports, harvest + idle poll |
| `40-phase-m3-clients-acceptance.md` | M3 | SSE, Swift client, panel, shim, budgets soak |
| `50-phase-m4-cutover.md` | M4 | legacy move, launchd, data unification, docs |

Binding documents (read first, in every phase):

1. `docs/superpowers/specs/2026-08-01-tokenbar-v2-architecture.md`
   (normative clauses S1–S26)
2. `docs/superpowers/plans/2026-08-01-tokenbar-v2-refactor.md`
   (phase tasks + exit criteria)
3. `AGENTS.md` (build rules: build the app after code changes; `.dmg`
   before any PR; relaunch the menu-bar app after rebuild)
