# Provider adapter sync — design

Date: 2026-07-31
Status: implemented (framework), adapters pending research sign-off
Research: `docs/research/2026-07-31-provider-usage-extraction.md`

## Goal

Token Bar syncs 6 subscriptions today (codex, claude, xai, antigravity,
copilot, devin). The ask is 17, adding cursor, factory droid, kiro,
opencode, cline, kilo code, hermes-agent, ollama, kimi code, z.ai coding
plan, and the alibaba/qwen token plan.

The blocker was never any single vendor API — it was that "a provider" is
spelled out in six places, and that the poll path assumes every account has
an OAuth token Token Bar itself minted.

## 1. Why the old shape did not scale

Adding one provider used to mean editing all of these:

| # | Place | What it hardcoded |
|---|-------|-------------------|
| 1 | `oauth.LOGIN_FUNCS` / `REFRESH_FUNCS` / `PROVIDERS` | login + refresh |
| 2 | `poller.POLLERS` | the poll function |
| 3 | `store.SCHEMA` → `limit_snapshots` columns | that provider's metrics |
| 4 | `status.normalize_windows()` | an `elif provider ==` branch |
| 5 | `window_history.timed_windows()` / `drop_windows()` | a second `elif` chain |
| 6 | `store.save_snapshot()` field list | the new columns again |

Item 3 is the worst of them. `limit_snapshots` had grown provider-specific
columns — `daily_quota_remaining_percent` (devin), `monthly_period_end`
(xai), `limited_user_reset_date` (copilot) — so every new vendor with a
differently-shaped quota wanted its own columns, and each set of columns
needed matching branches in items 4, 5 and 6 to be read back out.

Two further assumptions excluded whole classes of tool:

- **`_poll_one` failed closed on a missing token.** Fine for OAuth
  providers. Fatal for ollama (localhost, no credential at all) and for
  opencode/cline/kilo code, whose credential is the vendor CLI's own config
  file, not something Token Bar mints.
- **`local_sync.py` was hardcoded to codex + claude.** It is the right idea
  — read the CLI's own session logs, zero network, zero quota — but it was
  written as two bespoke scanners rather than a reusable source kind.

## 2. What changed

### 2.1 Declared windows: raw_json is the schema

An adapter no longer reports through columns. It reports a list of windows,
which `util.snapshot()` serializes into `raw_json["windows"]`:

```python
util.snapshot(
    [util.window("5h", used_pct=61.0, reset_at=1767225600.0),
     util.window("weekly", remaining_pct=40.0, label="GLM-4.7")],
    plan="coding-plan-max",
)
```

Both readers now check that key before their legacy branches:

- `status.declared_windows()` (`backend/status.py`) — display
- `window_history.declared()` (`backend/window_history.py`) — closed-window
  archiving, and through `poller.max_used_pct()` / `next_reset_at()`, the
  hot-poll and pre-reset scheduler

An adapter that declares windows owns the snapshot outright, empty list
included: `[]` means "I looked, there is no quota data", and must not fall
through to a legacy column branch that would answer with stale values.

Field handling, decided once so adapters stay literal transcriptions:

| Field | Rule |
|-------|------|
| `used_pct` / `remaining_pct` | pass whichever the vendor reports; `remaining_pct` is inverted and clamped by the reader |
| `reset_at` / `reset_at_epoch` | epoch number or ISO-8601 string, both accepted |
| `kind` | vendor's window name; derived from `window_s` when absent |
| `label` | disambiguates same-kind windows; slugged into the history key (`weekly` + `GLM-4.7` → `weekly_glm_4_7`) so per-model quotas never collide on one row |
| `source` | `api` \| `local` \| `gateway`, per window |
| `boundary` | hint for windows with no reset timestamp (devin-style daily) |

Net effect: **a new provider needs no migration and no branch.**

### 2.2 Adapter registry

`backend/providers/` — one module per provider:

```python
PROVIDER = "kimi"
AUTH     = util.AUTH_API_KEY
def poll(conn, account, token): ...
```

`providers.load()` discovers them, `register()` validates them, and
`poller.resolve_poller()` consults `POLLERS` first and the registry second —
legacy pollers keep priority so existing test doubles that patch `POLLERS`
still work. Discovery is best-effort: an adapter that fails to import is
recorded in `providers.errors()` and skipped, because one vendor changing
their CLI must not stop the daemon polling the other sixteen.

### 2.3 Four auth kinds, two of them tokenless

| `AUTH` | Credential | Token row |
|--------|-----------|-----------|
| `AUTH_OAUTH` | Token Bar runs the dance | yes |
| `AUTH_API_KEY` | user pastes a key | yes |
| `AUTH_LOCAL_FILE` | the vendor CLI's own credential file | no |
| `AUTH_NONE` | none — localhost or disk only | no |

`providers.requires_token()` gates `_poll_one`, defaulting to `True` for
anything unregistered so every legacy poller keeps its original behavior.
This is the change that admits ollama, opencode, cline and kilo code.

`AUTH_LOCAL_FILE` is the interesting one: for a tool the user has already
logged into, Token Bar reads that CLI's credential rather than asking for a
second login. No new OAuth client, no key to paste.

## 3. Source kinds

The user asked which extraction routes are available. They are now the
adapter's menu, in descending order of robustness:

| Kind | Mechanism | Cost | Breaks when |
|------|-----------|------|-------------|
| `official API` | documented usage/billing endpoint | 1 request | rarely |
| `OAuth API` | first-party endpoint the vendor's own client calls | 1 request | vendor rotates client/endpoint |
| `local file` | vendor CLI's credential + session/state files | zero network | CLI changes its on-disk format |
| `CLI command` | run the vendor CLI, parse JSON stdout | process spawn | flag/output changes |
| `headers` | cheap probe request, read `x-ratelimit-*` | 1 minimal request | vendor stops sending headers |
| `gateway` | local proxy the CLI is pointed at, counts tokens | zero extra | CLI pins certs or ignores base-URL env |

Ordering matters per provider, not globally: an adapter should try the
cheapest *accurate* source and fall back. A local file that says 61% is
worth more than a probe request that burns quota to learn the same thing.

`gateway` is the only one that produces data no vendor endpoint exposes —
per-request token counts in real time — and the only one that is
approximate for subscription quota, since it sees what this machine spent,
not what the account spent. It is a supplement, never the primary source.

## 4. Per-provider adapter plan

From `docs/research/2026-07-31-provider-usage-extraction.md`; see that
document for citations and for what could not be verified.

**Shipped** (both `AUTH_LOCAL_FILE`, both confirmed against a live 200
during research):

| Provider | Source | Notes |
|----------|--------|-------|
| `kimi` | `GET api.kimi.com/coding/v1/usages` + `~/.kimi-code/credentials/kimi-code.json` | weekly + rolling 5h windows, plan tier |
| `kiro` | `GET management.<region>.kiro.dev/getUsageLimits` + `~/.aws/sso/cache/kiro-auth-token.json` | monthly credit pool, UTC month boundary |

**Ready to build, evidence strong:**

| Provider | Source | Blocker |
|----------|--------|---------|
| `cursor` | `POST api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage` | token is in the macOS Keychain, so the adapter needs a `security find-generic-password` read — a new credential path for this repo |
| `kilo` | `GET api.kilo.ai/api/trpc/kiloPass.getState` | none; `~/.local/share/kilo/auth.json` is plaintext. Unverified by live call |
| `droid` | `GET api.factory.ai/api/billing/limits` | credential file is encrypted; ship as `AUTH_API_KEY` with a user-supplied `fk-` key instead |
| `zai` | `GET api.z.ai/api/monitor/usage/quota/limit` | endpoint schema is third-party reverse-engineering, never called live. Parse defensively; retry auth without the `Bearer` prefix on 401 |

**Cumulative-only** — these expose spend, not headroom, so they belong in a
different UI affordance than a quota window:

| Provider | Source | Why not a window |
|----------|--------|------------------|
| `opencode` | `~/.local/share/opencode/opencode.db` `session` table | Zen has no balance endpoint at all; quota surfaces only on 4xx |
| `qwen` | `~/.qwen/usage/token-usage-YYYY-MM.jsonl` | vendor states remaining quota is not queryable |
| `hermes` | `~/.hermes/state.db` | rate-limit state is in-memory only, lost when the process exits |
| `cline` | `state/taskHistory.json` (two possible paths) | balance API needs a token that VS Code keeps in SecretStorage |

**Plan tier only:** `ollama` — `POST localhost:11434/api/me` returns the plan
and nothing else. Two upstream issues asking for a usage endpoint were closed
as duplicates. The UI should say so rather than show an empty meter.

Sequencing note: the cumulative-only group needs a display decision before
code. A window with no reset and no ceiling is not a window, and forcing one
into `windows[]` would make the headline selector rank a spend total against
real quota percentages.

## 5. Verification

`python3 -m pytest backend -q` — 357 passing (275 baseline + 82 new).

New coverage:

- `test_declared_windows.py` — declared windows in display normalization
- `test_declared_history.py` — the same windows in history detection and in
  the hotness/pre-reset scheduler
- `test_providers.py` — registry validation, helper semantics, and a
  round-trip proving a snapshot survives store → status → history with no
  schema column
- `test_poller_adapters.py` — poller resolution and the token gate, both
  directions
- `test_adapter_kimi_kiro.py` — the two shipped adapters against the payload
  shapes those vendors actually send (quoted numbers, omitted zero keys,
  exponent-notation epochs, null fields the docs imply are always present)

`app/TokenStatusBar.swift` compiles clean (`swiftc -parse-as-library`).

Two things outside the backend needed fixing for this to work end to end:

- **`build.sh` bundled only top-level `backend/*.py`.** The new `providers/`
  package would have been missing from the shipped `.app`, and since
  `poller.py` imports it unconditionally, every poll would have failed in the
  installed app while passing in the repo. The loop now copies the package.
- **The dropdown iterated a hardcoded `providerOrder` and dropped anything
  not in it.** A new provider would sync correctly and stay invisible.
  Unknown providers are now appended after the known ones.

## 6. Deliberately not done

- **No migration of the six existing providers.** Their columns and
  branches still work and are covered by the existing suite. Moving them
  onto declared windows is mechanical but it is churn with regression risk
  and no user-visible gain; do it per-provider if one needs changing anyway.
- **No generalization of `local_sync.py` yet.** It should become an
  adapter source kind, but it also feeds `live_activity` (context %, tokens
  in the last hour), which is a different concern from quota windows.
