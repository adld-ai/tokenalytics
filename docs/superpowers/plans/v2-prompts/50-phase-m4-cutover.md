# Prompt — Phase M4: cutover & cleanup

You are working in `/Users/tonylee/solo/token-bar` on the TokenBar v2
refactor. Phase M3 is complete (clients live, 24 h soak green, v1
daemons off). Read first:

1. `docs/superpowers/plans/v2-prompts/README.md`
2. `docs/superpowers/specs/2026-08-01-tokenbar-v2-architecture.md` —
   binding: §6 (TOKENBAR_HOME), Q1–Q3, R17, §15.4 (matrix to close)
3. `docs/superpowers/plans/2026-08-01-tokenbar-v2-refactor.md` §9, §11
4. `AGENTS.md`

## Objective

One binary, one plist, one DB, one data dir — with a rehearsed
rollback.

## Tasks

1. **Legacy move.** `git mv backend legacy/backend` (unmodified — it
   is the rollback path, R17). Update references (tests that must now
   target `core/`, docs). Keep `legacy/` out of build paths.
2. **launchd (Q1).** The app generates and installs
   `~/Library/LaunchAgents/com.tonye.tokenbar-core.plist` on install:
   `KeepAlive.SuccessfulExit=false`, `ThrottleInterval=10`,
   stdout/stderr to `~/.tokenbar/logs/`. Remove the retired v1 plists
   (`agentpool-poller`, `agentpool-heartbeat`, `tokenbar-cloudpush` —
   Q2) with user approval.
3. **Data unification.** Migrate canonical data to `~/.tokenbar`
   (`TOKENBAR_HOME`, spec §6): DB + history import from the v1 data
   dir chosen in Phase P; retire the shadow dir
   `~/solo/token-status-bar` (archive, do not delete, with user
   approval).
4. **Rollback rehearsal.** Execute the documented rollback once:
   repoint CLI base URLs to direct, `launchctl bootout` the core,
   relaunch one legacy daemon from `legacy/`, verify the menu (legacy
   build) shows state; then roll forward again. Record timings.
5. **Docs sweep.** Rewrite README/CLAUDE.md/AGENTS.md for v2 (build
   = `go build ./...` + `build.sh`; run = app-managed launchd agent).
   Mark every row of the spec §15.4 traceability matrix complete.
6. **Final verification.** Full test suites (Go + Swift), app build,
   `.dmg` build per AGENTS.md, relaunch the app.

## Constraints

- Every destructive step (plist removal, dir archival, bootout) needs
  explicit user approval; present the full list up front.
- `legacy/` must remain runnable — do not "clean it up".

## Deliverables

1. Single-binary install: app + embedded core, one launchd plist.
2. Rollback rehearsal log (timings, issues).
3. Updated docs; spec §15.4 matrix closed.
4. Built `.app` + `.dmg`, app relaunched.
5. Final report (Korean): cutover summary, rollback results, residual
   items, and the v2-closeout statement.
