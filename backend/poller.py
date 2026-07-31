"""Poller — hits limit endpoints for every account (adaptive: 300s base,
60s hot / 180s hot-claude, pre-reset capture near known boundaries).

Limit sources:
  claude:       api.anthropic.com/api/oauth/usage (five_hour/seven_day/limits[])
  copilot:      api.github.com/copilot_internal/user (quota_snapshots.premium_interactions)

The providers listed above predate the adapter registry and stay hand-written
here. Migrated and newer providers live in backend/providers/ and reach this
module through resolve_poller(); see that package's docstring.
"""
from __future__ import annotations
import json, os, re, sys, time, datetime, urllib.request, urllib.error
import providers, store, oauth, window_history, work_queue

POLL_INTERVAL = int(os.environ.get("AGENT_POOL_POLL_INTERVAL", "300"))  # 5 min
LOCAL_SYNC_INTERVAL_S = int(os.environ.get("LOCAL_SYNC_INTERVAL_S", "15"))

# Adaptive cadence: hot accounts (any window >= HOT_THRESHOLD_PCT used) poll
# faster — an early reset only destroys meaningful data when usage is high —
# and accounts within PRERESET_LEAD_S of a known reset get a fresh capture
# with retries.
HOT_THRESHOLD_PCT = float(os.environ.get("HOT_THRESHOLD_PCT", "70"))
HOT_INTERVAL_S = int(os.environ.get("HOT_INTERVAL_S", "60"))
PRERESET_LEAD_S = int(os.environ.get("PRERESET_LEAD_S", "300"))
PRERESET_RETRY_S = int(os.environ.get("PRERESET_RETRY_S", "60"))
PRERESET_FINAL_GAP_S = 30

RETRYABLE_STATUSES = (429, 500, 502, 503, 504)
HTTP_RETRIES = 2  # extra attempts after the first; backoff 1s then 2s


def _http_error_body(e):
    """Read an HTTPError body once; JSON when possible, text otherwise."""
    raw = e.read()
    try:
        return json.loads(raw)
    except Exception:
        return raw.decode(errors="replace")


def _send(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = raw.decode(errors="replace")
            return r.status, body, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, _http_error_body(e), dict(e.headers)
    except urllib.error.URLError as e:
        return 0, str(e.reason), {}


def _send_with_retry(req, timeout):
    """Bounded retry on 429/5xx and network errors (honors integer Retry-After)."""
    st, body, hdrs = 0, "", {}
    delay = 1.0
    for attempt in range(HTTP_RETRIES + 1):
        st, body, hdrs = _send(req, timeout)
        if st != 0 and st not in RETRYABLE_STATUSES:
            return st, body, hdrs
        if attempt == HTTP_RETRIES:
            break
        wait = delay
        retry_after = (hdrs or {}).get("Retry-After")
        if retry_after is not None:
            try:
                # Cap so total added latency stays bounded.
                wait = max(0.0, min(float(int(retry_after)), 10.0))
            except (TypeError, ValueError):
                pass
        time.sleep(wait)
        delay *= 2
    return st, body, hdrs


def _get(url, headers, timeout=15):
    req = urllib.request.Request(url, method="GET")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    return _send_with_retry(req, timeout)


def _post(url, data, headers, timeout=15):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    return _send_with_retry(req, timeout)


# ─── Claude oauth/usage ────────────────────────────────────────────────────
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


def poll_claude(conn, account, token):
    """Poll Claude via the quota-free oauth/usage endpoint (no probes)."""
    def _fetch(access_token):
        return _get(CLAUDE_USAGE_URL, {
            "Authorization": f"Bearer {access_token}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "oauth-2025-04-20",
        })

    st, body, _ = _fetch(token["access_token"])
    if st == 401 and token.get("refresh_token"):
        # One refresh + retry; a second 401 becomes an error snapshot.
        # The lock serializes rotating-refresh-token use across processes.
        try:
            with work_queue.exclusive("token_refresh"):
                latest = store.get_token(conn, account["id"]) or token
                if latest["access_token"] != token["access_token"]:
                    # Another process already refreshed while we waited.
                    token = latest
                else:
                    result = oauth.refresh_claude(token["refresh_token"])
                    store.save_token(conn, account["id"], result["access_token"],
                                     result.get("refresh_token"), result.get("id_token"),
                                     result.get("expires_at"), result.get("raw"))
                    store.log_event(conn, account["id"], "token_refresh", True, "")
                    token = store.get_token(conn, account["id"])
            st, body, _ = _fetch(token["access_token"])
        except Exception as e:
            store.log_event(conn, account["id"], "token_refresh", False, str(e))

    if st != 200 or not isinstance(body, dict):
        snap = {"status": "error",
                "status_message": f"oauth/usage HTTP {st}: {str(body)[:120]}"}
    else:
        snap = _claude_usage_snap(body, _claude_profile(token))
    store.save_snapshot(conn, account["id"], snap)
    store.log_event(conn, account["id"], "limit_poll", snap["status"] == "active",
                    snap.get("status_message", ""))


def _claude_usage_snap(body, profile):
    """Build a snapshot from the oauth/usage response body (pure function)."""
    snap = {"status": "active", "status_message": ""}
    rj = {"usage_api": body}
    if profile:
        rj["profile"] = profile
        if profile.get("plan"):
            snap["plan"] = profile["plan"]

    fh = body.get("five_hour") or {}
    if fh.get("utilization") is not None:
        snap["primary_used_pct"] = float(fh["utilization"])
        snap["primary_window_s"] = 18000
        reset = window_history._parse_iso_ts(fh.get("resets_at"))
        if reset:
            snap["primary_reset_at"] = reset
    sd = body.get("seven_day") or {}
    if sd.get("utilization") is not None:
        snap["secondary_used_pct"] = float(sd["utilization"])
        snap["secondary_window_s"] = 604800
        reset = window_history._parse_iso_ts(sd.get("resets_at"))
        if reset:
            snap["secondary_reset_at"] = reset

    limits = [l for l in (body.get("limits") or []) if isinstance(l, dict)]
    for lim in limits:
        if lim.get("kind") != "weekly_scoped":
            continue
        scope_model = ((lim.get("scope") or {}).get("model") or {})
        rj["fable"] = {
            "label": scope_model.get("display_name") or "scoped",
            "used_pct": float(lim["percent"]) if lim.get("percent") is not None else None,
            "reset_at": window_history._parse_iso_ts(lim.get("resets_at")),
            "status": lim.get("severity"),
        }
        break

    active = next((l for l in limits if l.get("is_active")), None)
    snap["rate_limit_remaining"] = (active or {}).get("severity") or "normal"
    snap["rate_limit_limit"] = "unified"
    if snap.get("primary_reset_at"):
        snap["rate_limit_reset"] = str(snap["primary_reset_at"])
    snap["raw_json"] = json.dumps(rj)
    return snap


def _claude_profile(token):
    """Fetch Claude subscription/account profile via the OAuth profile endpoint."""
    try:
        st, body, _ = _get("https://api.anthropic.com/api/oauth/profile", {
            "Authorization": f"Bearer {token['access_token']}",
            "anthropic-version": "2023-06-01",
        })
    except Exception:
        return None
    if st != 200 or not isinstance(body, dict):
        return None
    acct = body.get("account") or {}
    org = body.get("organization") or {}
    if acct.get("has_claude_max"):
        plan = "Claude Max"
    elif acct.get("has_claude_pro"):
        plan = "Claude Pro"
    else:
        ot = org.get("organization_type") or ""
        plan = ot.replace("_", " ").title() or None
    return {
        "plan": plan,
        "subscription_status": org.get("subscription_status"),
        "billing_type": org.get("billing_type"),
        "rate_limit_tier": org.get("rate_limit_tier"),
        "extra_usage_enabled": org.get("has_extra_usage_enabled"),
        "subscription_created_at": org.get("subscription_created_at"),
        "organization_type": org.get("organization_type"),
        "display_name": acct.get("display_name"),
        "full_name": acct.get("full_name"),
        "org_name": org.get("name"),
        "member_since": acct.get("created_at"),
    }
# ─── dispatch ──────────────────────────────────────────────────────────────
POLLERS = {
    "claude": poll_claude,
}


def resolve_poller(provider):
    """The poll callable for a provider, legacy table first.

    POLLERS stays authoritative so tests (and any future override) can patch a
    provider by assigning to it; adapters fill in everything else.
    """
    return POLLERS.get(provider) or providers.pollers().get(provider)


def _refresh_if_needed(conn, account, token):
    """Auto-refresh tokens that expire within 1 hour."""
    if not token or not token.get("refresh_token"):
        return token
    provider = account["provider"]
    refresh = oauth.resolve_refresh(provider)
    if refresh is None:
        return token
    if token.get("expires_at") and token["expires_at"] - time.time() < 3600:
        try:
            # Serialize refreshes across processes: refresh tokens rotate, so
            # concurrent refreshes (daemon + on-demand poll) can invalidate
            # each other. Inside the lock re-read the token and skip when it
            # was already refreshed while we waited.
            with work_queue.exclusive("token_refresh"):
                token = store.get_token(conn, account["id"]) or token
                if not (token.get("expires_at") and token["expires_at"] - time.time() < 3600):
                    return token
                result = refresh(token["refresh_token"])
                store.save_token(conn, account["id"], result["access_token"],
                                 result.get("refresh_token"), result.get("id_token"),
                                 result.get("expires_at"), result.get("raw"))
                store.log_event(conn, account["id"], "token_refresh", True, "")
                return store.get_token(conn, account["id"])
        except Exception as e:
            store.log_event(conn, account["id"], "token_refresh", False, str(e))
    return token


def _poll_one(conn, account) -> bool:
    """Poll one account. Returns True when the provider poll succeeded.

    Wraps the provider poller with closed-window detection: the previous
    successful snapshot is captured before the poll and compared with the
    freshly saved one right after, archiving any windows that closed in
    between. Detection failures never fail the poll.
    """
    token = store.get_token(conn, account["id"])
    if not token and providers.requires_token(account["provider"]):
        store.save_snapshot(conn, account["id"], {"status": "error", "status_message": "no token"})
        return False
    token = _refresh_if_needed(conn, account, token)
    poller = resolve_poller(account["provider"])
    if not poller:
        store.save_snapshot(conn, account["id"],
                            {"status": "error", "status_message": f"no poller for {account['provider']}"})
        return False
    # Capturing the baseline for detection must never fail the poll; on any
    # error skip detection (prev=None, no coupon hint) and poll anyway.
    try:
        prev = store.latest_successful_snapshot(conn, account["id"])
    except Exception as e:
        print(f"  pre-poll capture failed {account['provider']} #{account['id']}: {e}")
        prev = None
    try:
        poll_meta = poller(conn, account, token)
        print(f"  ✓ {account['provider']:12} {account['email'] or account['label']}")
    except Exception as e:
        store.save_snapshot(conn, account["id"], {"status": "error", "status_message": str(e)[:200]})
        store.log_event(conn, account["id"], "limit_poll", False, str(e))
        print(f"  ✗ {account['provider']:12} {account['email'] or account['label']}: {e}")
        return False
    if not isinstance(poll_meta, dict):
        poll_meta = {}
    prev_credits = poll_meta.get("reset_credit_baseline") or {}
    _archive_closed_windows(conn, account, prev, prev_credits)
    return True


def _archive_closed_windows(conn, account, prev, prev_credits):
    """Detect + archive windows closed since the previous successful snapshot.

    Coupon hint: a reset_credits row that was "available" before the poll and
    isn't afterwards (consumed or gone) marks a redeem from another device.
    """
    try:
        new = store.latest_snapshot(conn, account["id"])
        if not new or (prev and new["id"] == prev["id"]):
            return
        coupon_hint = False
        if prev_credits:
            cur = {c["credit_id"]: c["status"] for c in store.list_reset_credits(conn, account["id"])}
            coupon_hint = any(st == "available" and cur.get(cid) != "available"
                              for cid, st in prev_credits.items())
            _archive_credit_disappearances(conn, account, prev_credits, cur, coupon_hint)
        n = window_history.record_closed_windows(conn, account, prev, new, coupon_hint=coupon_hint)
        if n:
            print(f"  ⤷ archived {n} closed window(s): {account['provider']} #{account['id']}")
            try:
                import dashboard
                dashboard.generate(conn)
            except Exception as e:
                print(f"  dashboard generation failed: {e}")
    except Exception as e:
        print(f"  window-history detection failed: {e}")


def _archive_credit_disappearances(conn, account, prev_credits, cur, coupon_hint):
    """Mark credits that vanished since the previous poll in the ledger.

    Discriminator is the credit's expires_at: a past expiry means it expired
    unused; a future expiry means it was consumed (redeem from another device
    when coupon_hint is set) or provider-removed (gone). Our own redeems are
    marked earlier in redeem_reset, so those rows stay 'redeemed'.
    """
    import datetime
    disappeared = [cid for cid, st in prev_credits.items()
                   if st == "available" and cur.get(cid) is None]
    if not disappeared:
        return
    now_ts = time.time()
    hist = {r["credit_id"]: r for r in store.list_credit_history(conn, account["provider"])
            if r["account_id"] == account["id"]}
    changed = False
    for cid in disappeared:
        row = hist.get(cid)
        if not row or row.get("final_state") == "redeemed":
            continue
        exp = row.get("expires_at")
        exp_ts = None
        if exp:
            try:
                dt = datetime.datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
                exp_ts = dt.timestamp()
            except (ValueError, TypeError):
                exp_ts = None
        if exp_ts is not None and exp_ts < now_ts:
            state = "expired_unused"
        elif coupon_hint:
            state = "redeemed"
        else:
            state = "gone"
        store.mark_credit_final(conn, account["id"], cid, state)
        changed = True
    if changed:
        try:
            import dashboard
            dashboard.generate(conn)
        except Exception as e:
            print(f"  dashboard generation failed: {e}")


def poll_some(conn, accounts) -> None:
    """Poll the given accounts and export status.json once."""
    for a in accounts:
        # One account's unexpected failure must not abort the rest or the export.
        try:
            _poll_one(conn, a)
        except Exception as e:
            print(f"  ✗ poll failed {a['provider']} #{a['id']}: {e}")
    try:
        export_status(conn)
    except Exception as e:
        print(f"  export-status failed: {e}")


# Previous export payload, kept in memory so consecutive exports within this
# process (daemon loop, local-sync ticks) can be diffed for lifecycle events.
# First export after startup has no baseline → detect_transitions emits [].
_prev_export_payload: dict | None = None


def export_status(conn) -> None:
    """Export status.json, then detect + persist lifecycle transitions (§1.4)."""
    global _prev_export_payload
    import status
    payload = status.build_payload(conn)
    status.write_status(payload)
    try:
        import lifecycle
        ts = time.time()
        for ev in lifecycle.detect_transitions(_prev_export_payload, payload):
            store.save_lifecycle_event(conn, ts, ev["account_id"],
                                       ev["event"], ev["detail"])
    except Exception as e:
        # Event persistence must never break the export path the app reads.
        print(f"  lifecycle events failed: {e}")
    _prev_export_payload = payload
    # §3.2: automatic same-provider account swap, evaluated at this single
    # choke point after events are persisted. On a successful swap, rebuild
    # + rewrite so the app immediately sees payload["last_swap"] (which
    # build_payload reads back from lifecycle_events → survives restarts).
    try:
        import swap
        if swap.auto_swap_tick(conn, payload):
            payload = status.build_payload(conn)
            status.write_status(payload)
            _prev_export_payload = payload
    except Exception as e:
        # A failed swap evaluation must never break the export path either.
        print(f"  auto-swap failed: {e}")


def poll_account(conn, account) -> bool:
    """Poll a single account and refresh status.json. Returns True on success.

    Used by onboarding so a freshly-added account immediately has subscription
    data instead of waiting for the next 5-minute poll cycle.
    """
    ok = _poll_one(conn, account)
    try:
        export_status(conn)
    except Exception as e:
        print(f"  export-status failed: {e}")
    return ok


def run_once(conn) -> int:
    with work_queue.single_worker("poll") as acquired:
        if not acquired:
            print("poll already running; queued worker skipped")
            return 0
        accounts = store.list_accounts(conn)
        if not accounts:
            print("(no accounts to poll)")
            return 0
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Polling {len(accounts)} accounts...")
        poll_some(conn, accounts)
    return 0


def max_used_pct(provider, snap) -> float:
    """Highest used% across a snapshot's tracked windows (hotness signal)."""
    vals = [w["used_pct"] for w in window_history.timed_windows(provider, snap)]
    vals += [w["used_pct"] for w in window_history.drop_windows(provider, snap)]
    return max(vals, default=0.0)


def next_reset_at(provider, snap, now) -> float | None:
    """Earliest future reset timestamp among the snapshot's timed windows."""
    future = [w["reset_at"] for w in window_history.timed_windows(provider, snap)
              if w["reset_at"] > now]
    return min(future) if future else None


def compute_next_due(now, *, provider, last_poll_ts, last_success_ts, hot, reset_at) -> float:
    """Pure next-poll-time computation for one account.

    Base cadence POLL_INTERVAL; hot accounts use HOT_INTERVAL_S. When
    reset_at is within PRERESET_LEAD_S and no success has landed inside that
    lead window yet, wake at the lead start and retry every PRERESET_RETRY_S,
    last attempt no later than reset_at - PRERESET_FINAL_GAP_S. First success
    wins.
    """
    interval = HOT_INTERVAL_S if hot else POLL_INTERVAL
    due = last_poll_ts + interval
    if reset_at:
        lead_start = reset_at - PRERESET_LEAD_S
        deadline = reset_at - PRERESET_FINAL_GAP_S
        captured = last_success_ts is not None and last_success_ts >= lead_start
        if not captured and now <= deadline:
            if now < lead_start:
                candidate = lead_start
            else:
                candidate = min(max(last_poll_ts + PRERESET_RETRY_S, now), deadline)
            if candidate <= deadline:
                due = min(due, candidate)
    return due


_next_local_scan = 0.0


def _local_sync_tick(conn):
    """Scan local CLI logs at most every LOCAL_SYNC_INTERVAL_S; export on change."""
    global _next_local_scan
    if time.time() < _next_local_scan:
        return
    _next_local_scan = time.time() + LOCAL_SYNC_INTERVAL_S
    try:
        import local_sync
        if local_sync.scan(conn):
            export_status(conn)
    except Exception as e:
        print(f"  local sync failed: {e}")


def run_loop(conn) -> int:
    print(f"Poller daemon started. Base interval: {POLL_INTERVAL}s, hot: {HOT_INTERVAL_S}s, "
          f"pre-reset lead: {PRERESET_LEAD_S}s. Ctrl+C to stop.")
    # In-memory attempt times: copilot's hold-last-good path saves no snapshot
    # on a transient failure, so DB timestamps alone would re-poll it instantly.
    last_attempt: dict[int, float] = {}
    next_prune = 0.0  # prune retention once at startup, then daily
    while True:
        try:
            now = time.time()
            if now >= next_prune:
                next_prune = now + 86400
                try:
                    store.prune_old_rows(conn)
                except Exception as e:
                    print(f"  retention prune failed: {e}")
            accounts = store.list_accounts(conn)
            _local_sync_tick(conn)
            if not accounts:
                time.sleep(POLL_INTERVAL)
                continue
            due, wake = [], now + POLL_INTERVAL
            for a in accounts:
                snap = store.latest_snapshot(conn, a["id"])
                good = store.latest_successful_snapshot(conn, a["id"])
                last_poll_ts = max(float(snap["ts"]) if snap else 0.0,
                                   last_attempt.get(a["id"], 0.0))
                t_due = compute_next_due(
                    now,
                    provider=a["provider"],
                    last_poll_ts=last_poll_ts,
                    last_success_ts=float(good["ts"]) if good else None,
                    hot=bool(good) and max_used_pct(a["provider"], good) >= HOT_THRESHOLD_PCT,
                    reset_at=next_reset_at(a["provider"], good, now) if good else None,
                )
                if t_due <= now:
                    due.append(a)
                else:
                    wake = min(wake, t_due)
            if due:
                with work_queue.single_worker("poll") as acquired:
                    if acquired:
                        stamp = datetime.datetime.now().strftime("%H:%M:%S")
                        print(f"[{stamp}] Polling {len(due)}/{len(accounts)} due accounts...")
                        for a in due:
                            last_attempt[a["id"]] = time.time()
                        poll_some(conn, due)
                        continue
                print("poll already running; waiting")
                time.sleep(5)
                continue
            time.sleep(max(1.0, min(wake - time.time(), LOCAL_SYNC_INTERVAL_S)))
        except KeyboardInterrupt:
            print("\nPoller stopped.")
            return 0
        except Exception as e:
            # Never let a single bad cycle kill the daemon (LaunchAgent would
            # crash-loop). Log, pause briefly so a persistent bug can't spin.
            print(f"poll cycle error: {e}")
            time.sleep(5)


# ─── redeem reset credit ───────────────────────────────────────────────────
def redeem_reset(conn, account_id) -> int:
    a = store.get_account(conn, account_id)
    if not a:
        print(f"Account {account_id} not found")
        return 1
    if a["provider"] != "codex":
        print("Reset credits only available for Codex accounts")
        return 1
    token = store.get_token(conn, account_id)
    if not token:
        print("No token for this account")
        return 1
    credits = store.list_reset_credits(conn, account_id)
    available = [c for c in credits if c["status"] == "available"]
    if not available:
        print("No available banked reset credits")
        return 1
    from status import iso_fmt_exact
    print(f"{len(available)} available reset credits:")
    for i, c in enumerate(available):
        exp = iso_fmt_exact(c["expires_at"]) or c["expires_at"]
        print(f"  [{i}] {c['title'] or c['credit_id']}  expires: {exp}")
    try:
        idx = int(input("Pick one to redeem (number): "))
    except (ValueError, EOFError, KeyboardInterrupt):
        print("Cancelled")
        return 1
    if not (0 <= idx < len(available)):
        print(f"Invalid selection: {idx} (choose 0-{len(available) - 1})")
        return 1
    credit = available[idx]
    import uuid
    # Hold the poll lock through consume + ledger + re-poll so the daemon
    # can't poll (and rewrite reset_credits) mid-redemption.
    with work_queue.exclusive("poll"):
        codex_adapter = providers.get("codex")
        st, resp, _ = _post(f"{codex_adapter.WHAM}/wham/rate-limit-reset-credits/consume",
                         {"credit_id": credit["credit_id"], "redeem_request_id": str(uuid.uuid4())},
                         {"Authorization": f"Bearer {token['access_token']}",
                          "ChatGPT-Account-Id": a["account_id"], "User-Agent": "agent-pool/1.0"})
        if st == 200:
            print(f"✓ Redeemed: {credit['title']}")
            # Mark the credit as redeemed in the ledger before the re-poll wipes it
            # from reset_credits, so it is never misclassified as expired_unused.
            store.mark_credit_redeemed(conn, account_id, credit["credit_id"])
            # Archive the closing windows now — before the confirmation re-poll —
            # so the coupon row exists even if that re-poll fails.
            try:
                n = window_history.archive_coupon_redeem(conn, a, credit["credit_id"])
                if n:
                    print(f"  ⤷ archived {n} window(s) as coupon reset")
            except Exception as e:
                print(f"  window-history archive failed: {e}")
            # Re-poll to show updated state
            resolve_poller("codex")(conn, a, token)
            return 0
        else:
            print(f"Redeem failed: HTTP {st} {resp}")
            return 1
