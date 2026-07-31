"""Data shaping for the self-contained window-history dashboard."""
from __future__ import annotations
import datetime, json

import providers, store, window_history
from window_history import fmt_local


def dashboard_data(conn) -> list[dict]:
    rows = []
    for r in store.list_window_history(conn):
        if r["window_kind"].startswith("5h"):
            continue
        try:
            details = json.loads(r["details"]) if r["details"] else {}
        except (TypeError, ValueError):
            details = {}
        if not isinstance(details, dict):
            details = {}
        rows.append({
            "provider": r["provider"],
            "account": r["email"] or r["label"] or f"#{r['account_id']}",
            "account_id": r["account_id"],
            "window_kind": r["window_kind"],
            "window_start": r["window_start"],
            "window_end": r["window_end"],
            "window_end_label": fmt_local(r["window_end"]),
            "final_used_pct": r["final_used_pct"],
            "reset_cause": r["reset_cause"],
            "staleness_s": details.get("staleness_s"),
            "ongoing": False,
        })
    for a in store.list_accounts(conn):
        snap = store.latest_successful_snapshot(conn, a["id"])
        if not snap:
            continue
        acct = a["email"] or a["label"] or f"#{a['id']}"
        windows = (window_history.timed_windows(a["provider"], snap)
                   + window_history.drop_windows(a["provider"], snap))
        for w in windows:
            if w["kind"].startswith("5h") or w["kind"] in (
                    "daily", "monthly", "monthly_premium", "monthly_chat"):
                continue
            if w.get("used_pct") is None:
                continue
            rows.append({
                "provider": a["provider"],
                "account": acct,
                "account_id": a["id"],
                "window_kind": w["kind"],
                "window_start": None,
                "window_end": None,
                "window_end_label": "ongoing",
                "final_used_pct": float(w["used_pct"]),
                "reset_cause": "ongoing",
                "staleness_s": None,
                "ongoing": True,
            })
    return rows


def provider_order(rows: list[dict]) -> list[str]:
    """Providers present in the payload, with registered adapters first."""
    actual = list(dict.fromkeys(row["provider"] for row in rows))
    registered = [name for name in providers.names() if name in actual]
    return registered + [name for name in actual if name not in registered]


def _coupon_status(row: dict, now: datetime.datetime | None = None) -> str:
    """Normalize ledger states and expire stale available rows at render time."""
    state = row.get("final_state") or "available"
    if state == "expired_unused":
        return "expired"
    if state != "available":
        return state
    expires_at = row.get("expires_at")
    if not expires_at:
        return state
    try:
        expires = datetime.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return state
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return "expired" if expires <= now.astimezone(datetime.timezone.utc) else state


def coupon_data(conn, now: datetime.datetime | None = None) -> list[dict]:
    """Codex reset-credit ledger: every credit ever seen, with its final state."""
    rows = []
    accounts = {a["id"]: a for a in store.list_accounts(conn)}
    for r in store.list_credit_history(conn, provider="codex"):
        account = accounts.get(r["account_id"], {})
        snap = store.latest_snapshot(conn, r["account_id"])
        description = r["description"] or ""
        credit_type = "referral" if "invit" in description.lower() else "usage reward"
        rows.append({
            "provider": r["provider"],
            "account": f"#{r['account_id']} " + (
                r["email"] or r["label"] or f"account {r['account_id']}"
            ),
            "plan": (snap.get("plan") if snap else None) or account.get("plan") or "",
            "credit_id": r["credit_id"],
            "title": r["title"] or "",
            "credit_type": credit_type,
            "description": description or r["title"] or "",
            "granted_at": r["granted_at"] or "",
            "expires_at": r["expires_at"] or "",
            "first_seen_at": r["first_seen_at"],
            "last_seen_at": r["last_seen_at"],
            "final_state": r["final_state"] or "available",
            "status": _coupon_status(r, now=now),
            "final_seen_at": r["final_seen_at"] or None,
            "redeemed_at": r["redeemed_at"] or None,
        })
    rows.sort(key=lambda row: (row["granted_at"], row["account"], row["credit_id"]))
    for number, row in enumerate(rows, start=1):
        row["number"] = number
    return rows


def account_data(conn) -> list[dict]:
    """Codex subscription rows for the account table, kept in raw UTC/ISO."""
    rows = []
    for account in store.list_accounts(conn):
        if account["provider"] != "codex":
            continue
        snap = store.latest_snapshot(conn, account["id"])
        meta = store.get_subscription_meta(conn, account["id"]) or {}
        active = meta.get("has_active_subscription")
        rows.append({
            "account_id": account["id"],
            "email": account["email"] or account["label"] or f"#{account['id']}",
            "plan": (snap.get("plan") if snap else None) or account["plan"] or "",
            "paid_since": meta.get("paid_since") or "",
            "renews_at": meta.get("renews_at") or meta.get("expires_at") or "",
            "auto_renew": "yes" if active and meta.get("renews_at") else (
                "no" if active is not None else ""
            ),
            "account_created_at": meta.get("account_created_at") or "",
        })
    return rows
