## Classroom view — every account on one wall screen

Tokenalytics already computes, per account, the worst window, its reset time, staleness and (when burn-rate allows) a projected exhaust time. This PR adds a read-only page that lays those out as one tile per account for someone watching many seats at once — an instructor running a hands-on session, a team lead with a pool of accounts.

![30 accounts, 1280×720](classroom/fixtures/screenshot.png)

- `classroom/index.html` — single file, no build, no dependencies; reads `../secrets/status.json` (or `?src=`) every 15 s. Sort: exhausted → soonest projected exhaust → highest used %. Stale windows greyed. Emails masked unless `?unmask=1`.
- `classroom/fixtures/` — a deterministic 30-account sample emitted with the exact key names from `backend/status.py`, plus tests (`test_keys.py`, `test_sort.js`, `screenshot.py`).
- **App untouched**: no file under `app/`, `backend/`, `core/`, `worker/` is modified, so the AGENTS.md `.dmg`-before-PR rule is not triggered.
- MIT, same as the repo.
