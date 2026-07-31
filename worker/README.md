# token-bar-status (Cloudflare Worker)

Read-only mobile view of the same account/quota data the macOS menu bar shows.

## How it works

The Mac never exposes its loopback server to the internet. Instead:

1. The poller writes `secrets/status.json` (unchanged, still the local source of truth).
2. `backend/cloud_push.py --loop` watches that file and POSTs it to `/push` with `PUSH_TOKEN`.
3. The Worker stores the snapshot in KV (`STATUS_KV`, key `latest`).
4. Phones open `/`, enter the access code once, and the page reads `/api/status` with `VIEW_TOKEN`.

Push and view use separate secrets, so view access can be shared or revoked
without granting write access.

## Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/` | GET | none (page); data needs the code | Mobile dashboard |
| `/api/status` | GET | `VIEW_TOKEN` | Latest snapshot |
| `/push` | POST | `PUSH_TOKEN` | Store a snapshot |
| `/health` | GET | none | Liveness probe |

## Deploy

```bash
cd worker
wrangler deploy
```

Secrets (set once, rotate any time):

```bash
wrangler secret put PUSH_TOKEN
wrangler secret put VIEW_TOKEN
```

After rotating, update `secrets/cloud.env` next to `status.json` so the push
loop keeps authenticating:

```
TOKEN_BAR_WORKER_URL=https://token-bar-status.<subdomain>.workers.dev
TOKEN_BAR_PUSH_TOKEN=...
TOKEN_BAR_VIEW_TOKEN=...
```

## Continuous push

`com.tonye.tokenbar-cloudpush` (LaunchAgent) runs `cloud_push.py --loop`,
pushing within ~20s of each poll and re-pushing every ~10 minutes so a stale
`received_at` distinguishes "nothing changed" from "the Mac stopped reporting".

```bash
launchctl list | grep tokenbar-cloudpush
tail -f cloud_push.log
```

## Editing the dashboard

`dashboard.html` is inlined at build time via the `Text` rule in
`wrangler.toml`. Keep it a real file — the earlier version embedded this markup
in a `String.raw` template literal inside `index.js`, which preserved the `\``
escapes literally and shipped a page whose client JS could not parse.

Check it before deploying:

```bash
node --check src/index.js
```
