"""Kiro credit usage.

Kiro writes its bearer token and profile ARN as plain JSON into the AWS SSO
cache, so both halves of the request come from one file and Token Bar needs
no login of its own. Read-only: the token is refreshed by the Kiro IDE, and
when the IDE has been closed long enough for it to expire the poll reports
that rather than trying to renew someone else's credential.

The endpoint is internal (no AWS/Kiro reference page documents it); it was
read out of the shipped extension and confirmed against a live 200.
"""
from __future__ import annotations
import os
import urllib.parse
from pathlib import Path

import store
from . import util

PROVIDER = "kiro"
AUTH = util.AUTH_LOCAL_FILE

TOKEN_PATH = Path(os.environ.get(
    "KIRO_AUTH_TOKEN_FILE",
    str(Path.home() / ".aws" / "sso" / "cache" / "kiro-auth-token.json")))
REGION = os.environ.get("KIRO_REGION", "us-east-1")
USAGE_URL = f"https://management.{REGION}.kiro.dev/getUsageLimits"


def _pct(used, limit):
    try:
        used, limit = float(used), float(limit)
    except (TypeError, ValueError):
        return None
    if limit <= 0:
        return None
    return max(0.0, min(100.0, 100.0 * used / limit))


def to_snapshot(body: dict) -> dict:
    """Map a getUsageLimits response to a snapshot (pure — the tested part).

    Credits reset on the UTC calendar month boundary, not a billing
    anniversary. nextDateReset arrives as an exponent-notation float of
    epoch *seconds* (1.7855424E9), which json parses as a float already.
    daysUntilReset and the singular `limits` both come back null in practice
    and are deliberately ignored.
    """
    windows = []
    for item in body.get("usageBreakdownList") or []:
        if not isinstance(item, dict):
            continue
        used = item.get("currentUsageWithPrecision", item.get("currentUsage"))
        limit = item.get("usageLimitWithPrecision", item.get("usageLimit"))
        pct = _pct(used, limit)
        if pct is None:
            continue
        reset = item.get("nextDateReset") or body.get("nextDateReset")
        windows.append(util.window(
            "monthly", used_pct=pct, reset_at=reset,
            label=(item.get("displayName") or "").lower() or None))
    sub = body.get("subscriptionInfo") or {}
    raw = {"subscription_type": sub.get("type"),
           "overage_status": util.dig(body, "overageConfiguration", "overageStatus"),
           "user_id": util.dig(body, "userInfo", "userId")}
    return util.snapshot(windows, plan=sub.get("subscriptionTitle"),
                         raw={k: v for k, v in raw.items() if v is not None})


def poll(conn, account, token):
    creds = util.read_json(TOKEN_PATH)
    access = (creds or {}).get("accessToken")
    profile_arn = (creds or {}).get("profileArn")
    if not access or not profile_arn:
        snap = util.error(f"no Kiro token at {TOKEN_PATH}")
    else:
        url = f"{USAGE_URL}?{urllib.parse.urlencode({'profileArn': profile_arn})}"
        st, body, _ = util.get_json(url, {"Authorization": f"Bearer {access}"})
        if st == 401:
            # The IDE owns this token; it renews on its own once reopened.
            snap = util.error("Kiro token expired — open Kiro to renew")
        elif st != 200 or not isinstance(body, dict):
            snap = util.error(f"getUsageLimits HTTP {st}: {str(body)[:120]}")
        else:
            snap = to_snapshot(body)
    store.save_snapshot(conn, account["id"], snap)
    store.log_event(conn, account["id"], "limit_poll",
                    snap["status"] == "active", snap.get("status_message", ""))
