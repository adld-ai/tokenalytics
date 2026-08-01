# Prompt — Phase P: pre-flight

You are working in `/Users/tonylee/solo/token-bar` on the TokenBar v2
refactor. Read first, in this order:

1. `docs/superpowers/plans/v2-prompts/README.md`
2. `docs/superpowers/specs/2026-08-01-tokenbar-v2-architecture.md`
   (§15.3 and §15.5 are your task source)
3. `docs/superpowers/plans/2026-08-01-tokenbar-v2-refactor.md` §4
4. `AGENTS.md`

## Objective

Lock the v1 baseline and produce the operational inventory that Phase
M1 depends on. No v2 code is written in this phase.

## Tasks (spec plan §4, P1–P5)

1. **P1 — commit v1 safety patches.** The working tree contains two
   uncommitted fixes: `cmd_remove` poll-lock in `backend/pool.py` (+
   `backend/test_remove.py`) and `AGENT_POOL_HISTORY_DIR` plumbing in
   `app/StatusLoader.swift`. Run `cd backend && python3 -m pytest -q`
   (expect 393+ passed), then commit them as one v1 safety commit on a
   `codex/` branch or main, per repo convention.
2. **P2 — retire heartbeat.** Inspect
   `~/Library/LaunchAgents/com.tonye.agentpool-heartbeat.plist`,
   `launchctl bootout gui/$(id -u)/com.tonye.agentpool-heartbeat`
   (escalated; ask the user first), remove the plist, and note in the
   report that v1 heartbeat traffic ("hi" every 5 h) is permanently
   off (spec S20).
3. **P3 — daemon inventory.** Run `launchctl list | grep -i -E
   "tonye|tokenbar|agentpool"` and `ps` (escalated) to determine which
   live process writes
   `~/solo/token-status-bar/secrets/status.json`, given that the
   installed plists point at a nonexistent
   `~/solo/token-status-bar/backend/pool.py`. Record exact PID,
   executable path, env (`AGENT_POOL_DB` etc.), and launchd label.
4. **P4 — data-dir decision + plist hygiene.** Decide the canonical
   v1 data dir (default recommendation: repo `secrets/` until v2's
   `~/.tokenbar` exists). Bootout or repair broken plists; stop
   `com.tonye.tokenbar-cloudpush` (spec Q2). Do not delete any DB.
5. **P5 — backups.** Copy `secrets/pool.db` (after
   `PRAGMA wal_checkpoint(TRUNCATE)`), `status.json`, and all three
   plists into `secrets/recovery/2026-08-01/`.

## Constraints

- Ask before any `bootout`, `rm` of plists, or process kill; these
  are destructive and need user approval.
- Do not modify any provider account data or tokens.
- Do not start v2 code, branches for M0, or directory renames.

## Deliverables

1. Commit with the two v1 patches (report the hash).
2. `docs/superpowers/specs/2026-08-01-tokenbar-v2-architecture.md`
   §15.3 updated: replace the "undetermined" inventory items with the
   findings from P3/P4 (who writes what, which plists were retired,
   canonical data dir).
3. Backup directory `secrets/recovery/2026-08-01/` populated.
4. Final report (Korean): inventory summary, what was stopped/retired,
   backup contents, and a Go/No-Go for Phase M0.
