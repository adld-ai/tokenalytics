"""xAI Grok monthly credits and daily request quota usage."""
from __future__ import annotations
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

import oauth
import store
from . import util

PROVIDER = "xai"
AUTH = util.AUTH_OAUTH
CAPS = frozenset()

XAI = {
    "auth_url": "https://auth.x.ai/oauth2/authorize",
    "token_url": "https://auth.x.ai/oauth2/token",
    "client_id": "b1a00492-073a-47ea-816f-4c329264a828",
    "scope": "openid profile email offline_access grok-cli:access api:access",
    "port": 56121,
}


def LOGIN(incognito: bool = False) -> dict:
    verifier, challenge = oauth.gen_pkce()
    state = oauth.gen_state()
    nonce = secrets.token_hex(16)
    redirect = f"http://127.0.0.1:{XAI['port']}/callback"
    params = {
        "response_type": "code",
        "client_id": XAI["client_id"],
        "redirect_uri": redirect,
        "scope": XAI["scope"],
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce,
        "plan": "generic",
    }
    auth_url = f"{XAI['auth_url']}?{urllib.parse.urlencode(params)}"
    oauth.open_browser(auth_url, incognito)
    print(f"Waiting for xAI callback on port {XAI['port']}...")
    result = oauth.wait_for_callback(XAI["port"], host="127.0.0.1", path="/callback")
    if result.get("error"):
        raise RuntimeError(
            f"xAI OAuth error: {result.get('error_description', result['error'])}"
        )
    if result.get("state") != state:
        raise RuntimeError("xAI OAuth state mismatch")
    st, tok = oauth.http_post(XAI["token_url"], {
        "grant_type": "authorization_code",
        "client_id": XAI["client_id"],
        "code": result["code"],
        "redirect_uri": redirect,
        "code_verifier": verifier,
    })
    if st != 200:
        raise RuntimeError(f"xAI token exchange failed: {st} {tok}")
    claims = oauth.decode_jwt_payload(tok.get("id_token", ""))
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "id_token": tok.get("id_token", ""),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "account_id": claims.get("sub", ""),
        "email": claims.get("email", ""),
        "plan": "",
        "raw": tok,
    }


def REFRESH(refresh_token: str) -> dict:
    st, tok = oauth.http_post(XAI["token_url"], {
        "grant_type": "refresh_token",
        "client_id": XAI["client_id"],
        "refresh_token": refresh_token,
    })
    if st != 200:
        raise RuntimeError(f"xAI refresh failed: {st} {tok}")
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", refresh_token),
        "id_token": tok.get("id_token", ""),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "raw": tok,
    }


def _authorize(state: str, challenge: str) -> str:
    redirect = f"http://127.0.0.1:{XAI['port']}/callback"
    params = {
        "response_type": "code",
        "client_id": XAI["client_id"],
        "redirect_uri": redirect,
        "scope": XAI["scope"],
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": secrets.token_hex(16),
        "plan": "generic",
    }
    return f"{XAI['auth_url']}?{urllib.parse.urlencode(params)}"


def _exchange(code: str, state: str, verifier: str) -> dict:
    redirect = f"http://127.0.0.1:{XAI['port']}/callback"
    st, tok = oauth.http_post(XAI["token_url"], {
        "grant_type": "authorization_code",
        "client_id": XAI["client_id"],
        "code": code,
        "redirect_uri": redirect,
        "code_verifier": verifier,
    })
    if st != 200:
        raise RuntimeError(f"xAI token exchange failed: {st} {tok}")
    claims = oauth.decode_jwt_payload(tok.get("id_token", ""))
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "id_token": tok.get("id_token", ""),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "account_id": claims.get("sub", ""),
        "email": claims.get("email", ""),
        "plan": "",
        "raw": tok,
    }


BROWSER_FLOW = {
    "host": "127.0.0.1",
    "port": XAI["port"],
    "path": "/callback",
    "pkce": True,
    "authorize": _authorize,
    "exchange": _exchange,
}


def PLAN_LABEL(plan, item) -> tuple:
    p = (plan or "").strip()
    return (p or None, None)


def EXTRA(snap) -> dict:
    try:
        raw = json.loads(snap.get("raw_json") or "{}")
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    extra = raw.get("extra") or {}
    if not isinstance(extra, dict):
        return {}

    # Function-local import avoids a providers -> status import cycle.
    from status import iso_fmt, reset_fmt

    out = {
        "credits_used": extra.get("credits_used"),
        "credits_limit": extra.get("credits_limit"),
        "on_demand_cap": extra.get("on_demand_cap"),
        "billing_period_start": iso_fmt(extra.get("period_start")),
        "plan_start": iso_fmt(extra.get("period_start")),
        "plan_reset": iso_fmt(extra.get("period_end")),
        "rate_limit_remaining": extra.get("rate_limit_remaining"),
        "rate_limit_limit": extra.get("rate_limit_limit"),
        "rate_limit_reset": reset_fmt(extra.get("rate_limit_reset")),
    }
    return {key: value for key, value in out.items() if value is not None}


def _with_daily(snap: dict, daily: dict | None) -> dict:
    if not daily or "primary_used_pct" not in daily:
        return snap
    try:
        raw = json.loads(snap.get("raw_json") or "{}")
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    windows = raw.setdefault("windows", [])
    window = util.window(
        "daily",
        used_pct=daily["primary_used_pct"],
        reset_at=daily.get("primary_reset_at"),
    )
    # The legacy history path never archived the best-effort daily probe.
    window["history"] = False
    windows.append(window)
    if daily.get("rate_limit_remaining") is not None:
        raw.setdefault("extra", {})["daily_remaining"] = daily["rate_limit_remaining"]
    out = dict(snap)
    out["raw_json"] = json.dumps(raw)
    return out


def to_snapshot(body: dict) -> dict:
    """Map xAI billing and optional daily-probe data to a snapshot (pure)."""
    billing = body.get("billing") if "billing" in body else body
    config = billing.get("config", {})
    used = config.get("used", {}).get("val", 0)
    limit = config.get("monthlyLimit", {}).get("val", 0)
    period_end = config.get("billingPeriodEnd", "")
    period_start = config.get("billingPeriodStart", "")
    pct = (used / limit * 100) if limit > 0 else 0

    monthly = util.window(
        "monthly",
        label="credits",
        used_pct=pct,
        reset_at=period_end or None,
    )
    # The old xAI history key was "monthly", without the display-label suffix.
    monthly["history_kind"] = "monthly"
    if period_start:
        monthly["start"] = period_start
    raw = {"extra": {
        "credits_used": used,
        "credits_limit": limit,
        "on_demand_cap": config.get("onDemandCap", {}).get("val"),
        "period_start": period_start,
        "period_end": period_end,
        "rate_limit_remaining": f"{limit - used} credits",
        "rate_limit_limit": f"{limit} credits/month",
        "rate_limit_reset": period_end[:10] if period_end else "monthly",
    }}
    snap = util.snapshot(
        [monthly],
        raw=raw,
        status=body.get("status", "active"),
        status_message=body.get("status_message", ""),
    )
    return _with_daily(snap, body.get("daily"))


def _shape_error(source, resp):
    return {
        "status": "error",
        "status_message": f"{source}: unexpected response shape: {str(resp)[:120]}",
    }


def poll(conn, account, token):
    # Step 1: Query the billing API for monthly credit usage
    # cli-chat-proxy.grok.com/v1/billing returns real-time monthly usage
    at = token["access_token"]
    snap = {}
    try:
        req = urllib.request.Request(
            "https://cli-chat-proxy.grok.com/v1/billing", method="GET"
        )
        req.add_header("Authorization", f"Bearer {at}")
        req.add_header("X-XAI-Token-Auth", "xai-grok-cli")
        with urllib.request.urlopen(req, timeout=15) as response:
            resp = json.loads(response.read())
        if not isinstance(resp, dict):
            snap = _shape_error("billing", resp)
        else:
            snap = to_snapshot(resp)
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:120]
        snap = {
            "status": "error",
            "status_message": f"billing HTTP {e.code}: {msg}",
        }
    except urllib.error.URLError as e:
        snap = {"status": "error", "status_message": str(e.reason)}
    except json.JSONDecodeError as e:
        snap = _shape_error("billing", f"invalid JSON: {e}")

    # Step 2: Also probe the chat API for daily rate-limit headers
    body = json.dumps({
        "model": "grok-4",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    }).encode()
    req = urllib.request.Request(
        "https://api.x.ai/v1/chat/completions", data=body, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {at}")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            hdrs = dict(response.headers)
            daily = _xai_snap(hdrs, "active", "")
            snap = _with_daily(snap, daily)
    except urllib.error.HTTPError as e:
        hdrs = dict(e.headers)
        msg = e.read().decode(errors="replace")[:120]
        if e.code == 429:
            daily = _xai_snap(hdrs, "rate_limited", f"429: {msg}")
            if "primary_used_pct" not in daily:
                daily["primary_used_pct"] = 100.0
            snap = _with_daily(snap, daily)
            if snap["status"] == "active":
                snap["status"] = "rate_limited"
                snap["status_message"] = "daily rate limited"
        # Don't override error status from billing
    except urllib.error.URLError:
        pass  # Daily probe is best-effort

    store.save_snapshot(conn, account["id"], snap)
    store.log_event(
        conn,
        account["id"],
        "limit_poll",
        snap["status"] == "active",
        snap.get("status_message", ""),
    )


def _xai_snap(hdrs, status, msg):
    raw = {k: v for k, v in hdrs.items() if "ratelimit" in k.lower()}
    snap = {"status": status, "status_message": msg, "raw_json": json.dumps(raw)}
    # xAI exposes per-day request + token limits via headers.
    # Monthly limits exist (tier-based spend) but are NOT exposed via API headers.
    # Request-based rate limit (per-day window)
    limit_req = hdrs.get("x-ratelimit-limit-requests")
    remaining_req = hdrs.get("x-ratelimit-remaining-requests")
    if limit_req and remaining_req:
        lim = float(limit_req)
        rem = float(remaining_req)
        used = lim - rem
        snap["primary_used_pct"] = (used / lim * 100) if lim > 0 else 0
        snap["primary_window_s"] = 86400  # 24h
        snap["rate_limit_limit"] = str(int(lim))
        snap["rate_limit_remaining"] = str(int(rem))
    # Token-based rate limit (per-day)
    limit_tok = hdrs.get("x-ratelimit-limit-tokens")
    remaining_tok = hdrs.get("x-ratelimit-remaining-tokens")
    if limit_tok and remaining_tok:
        lim = float(limit_tok)
        rem = float(remaining_tok)
        used = lim - rem
        snap["secondary_used_pct"] = (used / lim * 100) if lim > 0 else 0
        snap["secondary_window_s"] = 86400
    # Reset timestamp (xAI returns a human-readable string like "1h23m45s" or "1d")
    reset_req = hdrs.get("x-ratelimit-reset-requests")
    if reset_req:
        snap["rate_limit_reset"] = reset_req
        # Try to parse as duration for primary_reset_at
        snap["primary_reset_at"] = _xai_parse_reset(reset_req)
    else:
        snap["rate_limit_reset"] = "daily"
    return snap


def _xai_parse_reset(s):
    """Parse xAI reset string like '1h23m45s' or '23h59m' into epoch time."""
    total = 0
    match = re.match(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", s)
    if match:
        d, h, mi, se = match.groups()
        if d:
            total += int(d) * 86400
        if h:
            total += int(h) * 3600
        if mi:
            total += int(mi) * 60
        if se:
            total += int(se)
    return time.time() + total if total > 0 else None
