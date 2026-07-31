"""Anthropic Claude quota usage, subscription profile, and OAuth flow."""
from __future__ import annotations
import datetime
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import oauth
import store
import work_queue
from . import util

PROVIDER = "claude"
AUTH = util.AUTH_OAUTH
CAPS = frozenset({"heartbeat", "swap"})

CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
CLAUDE = {
    "auth_url": "https://claude.ai/oauth/authorize",
    "token_url": "https://api.anthropic.com/v1/oauth/token",
    "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
    "scope": (
        "user:profile user:inference user:sessions:claude_code "
        "user:mcp_servers user:file_upload"
    ),
    "port": 54545,
}

RETRYABLE_STATUSES = (429, 500, 502, 503, 504)
HTTP_RETRIES = 2
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def LOGIN(incognito: bool = False) -> dict:
    verifier, challenge = oauth.gen_pkce()
    state = oauth.gen_state()
    redirect = f"http://localhost:{CLAUDE['port']}/callback"
    params = {
        "code": "true",
        "client_id": CLAUDE["client_id"],
        "response_type": "code",
        "redirect_uri": redirect,
        "scope": CLAUDE["scope"],
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{CLAUDE['auth_url']}?{urllib.parse.urlencode(params)}"
    oauth.open_browser(auth_url, incognito)
    print(f"Waiting for Claude callback on port {CLAUDE['port']}...")
    result = oauth.wait_for_callback(
        CLAUDE["port"], host="localhost", path="/callback"
    )
    if result.get("error"):
        raise RuntimeError(
            f"Claude OAuth error: "
            f"{result.get('error_description', result['error'])}"
        )
    if result.get("state") != state:
        raise RuntimeError("Claude OAuth state mismatch")
    st, tok = oauth.http_post_json(CLAUDE["token_url"], {
        "grant_type": "authorization_code",
        "client_id": CLAUDE["client_id"],
        "code": result["code"],
        "state": state,
        "redirect_uri": redirect,
        "code_verifier": verifier,
    }, {"User-Agent": USER_AGENT})
    if st != 200:
        raise RuntimeError(f"Claude token exchange failed: {st} {tok}")
    email = ""
    account_id = ""
    if isinstance(tok, dict):
        acct = tok.get("account") or {}
        email = acct.get("email_address", "")
        account_id = acct.get("uuid", "")
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "id_token": tok.get("id_token", ""),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "account_id": account_id,
        "email": email,
        "plan": "",
        "raw": tok,
    }


def REFRESH(refresh_token: str) -> dict:
    st, tok = oauth.http_post_json(CLAUDE["token_url"], {
        "grant_type": "refresh_token",
        "client_id": CLAUDE["client_id"],
        "refresh_token": refresh_token,
    }, {"User-Agent": USER_AGENT})
    if st != 200:
        raise RuntimeError(f"Claude refresh failed: {st} {tok}")
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", refresh_token),
        "id_token": tok.get("id_token", ""),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "raw": tok,
    }


def _authorize(state: str, challenge: str) -> str:
    redirect = f"http://localhost:{CLAUDE['port']}/callback"
    params = {
        "code": "true",
        "client_id": CLAUDE["client_id"],
        "response_type": "code",
        "redirect_uri": redirect,
        "scope": CLAUDE["scope"],
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{CLAUDE['auth_url']}?{urllib.parse.urlencode(params)}"


def _exchange(code: str, state: str, verifier: str) -> dict:
    redirect = f"http://localhost:{CLAUDE['port']}/callback"
    st, tok = oauth.http_post_json(CLAUDE["token_url"], {
        "grant_type": "authorization_code",
        "client_id": CLAUDE["client_id"],
        "code": code,
        "state": state,
        "redirect_uri": redirect,
        "code_verifier": verifier,
    }, {"User-Agent": USER_AGENT})
    if st != 200:
        raise RuntimeError(f"Claude token exchange failed: {st} {tok}")
    email, account_id = "", ""
    if isinstance(tok, dict):
        acct = tok.get("account") or {}
        email = acct.get("email_address", "")
        account_id = acct.get("uuid", "")
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "id_token": tok.get("id_token", ""),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "account_id": account_id,
        "email": email,
        "plan": "",
        "raw": tok,
    }


BROWSER_FLOW = {
    "host": "localhost",
    "port": CLAUDE["port"],
    "path": "/callback",
    "pkce": True,
    "authorize": _authorize,
    "exchange": _exchange,
}


def PLAN_LABEL(plan, item) -> tuple:
    p = (plan or "").strip()
    labels = {
        "claude pro": ("Claude Pro", "$20/mo"),
        "claude max": ("Claude Max", "$100/mo"),
    }
    return labels.get(p.lower(), (p or None, None))


def EXTRA(snap) -> dict:
    """Export Claude subscription facts that are not declared windows."""
    out: dict = {}
    if not snap or not snap.get("raw_json"):
        return out
    try:
        raw = json.loads(snap["raw_json"])
    except Exception:
        return out
    if not isinstance(raw, dict):
        return out

    from status import iso_fmt, next_monthly_anniversary, reset_fmt, ts_fmt, KST

    profile = raw.get("profile") or {}
    ratelimit = raw.get("ratelimit") or {}
    fable = raw.get("fable") or {}
    extra = raw.get("extra") or {}
    if fable:
        if fable.get("used_pct") is not None:
            out["fable_used_pct"] = fable["used_pct"]
        if fable.get("reset_at") is not None:
            out["fable_reset"] = ts_fmt(fable["reset_at"])
        if fable.get("label"):
            out["fable_label"] = fable["label"]
        if fable.get("status"):
            out["fable_status"] = fable["status"]
    if profile:
        out["subscription_status"] = profile.get("subscription_status")
        out["billing_type"] = profile.get("billing_type")
        out["rate_limit_tier"] = profile.get("rate_limit_tier")
        out["extra_usage_enabled"] = profile.get("extra_usage_enabled")
        out["subscription_created"] = iso_fmt(
            profile.get("subscription_created_at")
        )
        out["plan_start"] = iso_fmt(profile.get("subscription_created_at"))
        anniversary = next_monthly_anniversary(
            profile.get("subscription_created_at")
        )
        if anniversary:
            out["plan_reset"] = anniversary.astimezone(KST).strftime(
                "%Y-%m-%d %H:%M"
            )
        out["member_since"] = iso_fmt(profile.get("member_since"))
        out["display_name"] = profile.get("display_name")
        out["org_name"] = profile.get("org_name")

    usage = raw.get("usage_api") or {}
    limits = [
        limit for limit in (usage.get("limits") or [])
        if isinstance(limit, dict)
    ]
    if limits:
        by_kind = {limit.get("kind"): limit for limit in limits}
        if by_kind.get("session"):
            out["primary_status"] = by_kind["session"].get("severity")
        if by_kind.get("weekly_all"):
            out["secondary_status"] = by_kind["weekly_all"].get("severity")
        active = next((limit for limit in limits if limit.get("is_active")), None)
        if active:
            label = {
                "session": "5h",
                "weekly_all": "weekly",
            }.get(active.get("kind"))
            if label is None:
                scope_model = ((active.get("scope") or {}).get("model") or {})
                label = scope_model.get("display_name") or active.get("kind")
            out["binding_window"] = label
        usage_extra = usage.get("extra_usage") or {}
        if usage_extra.get("is_enabled"):
            out["extra_usage_enabled"] = True
            if usage_extra.get("utilization") is not None:
                out["extra_usage_used_pct"] = float(
                    usage_extra["utilization"]
                )
    elif ratelimit:
        out["primary_status"] = ratelimit.get(
            "anthropic-ratelimit-unified-5h-status"
        )
        out["secondary_status"] = ratelimit.get(
            "anthropic-ratelimit-unified-7d-status"
        )
        fallback_pct = ratelimit.get(
            "anthropic-ratelimit-unified-fallback-percentage"
        )
        if fallback_pct is not None:
            try:
                out["fallback_used_pct"] = float(fallback_pct) * 100
            except (TypeError, ValueError):
                pass
        claim = ratelimit.get(
            "anthropic-ratelimit-unified-representative-claim"
        )
        out["binding_window"] = {
            "five_hour": "5h",
            "seven_day": "weekly",
        }.get(claim, claim)
        out["overage_status"] = ratelimit.get(
            "anthropic-ratelimit-unified-overage-status"
        )

    if isinstance(extra, dict):
        out["rate_limit_remaining"] = extra.get("rate_limit_remaining")
        out["rate_limit_limit"] = extra.get("rate_limit_limit")
        if extra.get("rate_limit_reset") is not None:
            out["rate_limit_reset"] = reset_fmt(extra["rate_limit_reset"])
    return {key: value for key, value in out.items() if value is not None}


def _parse_iso_ts(value) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.timestamp()


def _window(usage, limits, usage_kind, limit_kind, kind, window_s):
    payload = usage.get(usage_kind) or {}
    if payload.get("utilization") is None:
        return None
    limit = limits.get(limit_kind) or {}
    reset_at = _parse_iso_ts(payload.get("resets_at"))
    window = util.window(
        kind,
        used_pct=float(payload["utilization"]),
        reset_at=reset_at,
        window_s=window_s,
        severity=limit.get("severity"),
        is_active=limit.get("is_active"),
    )
    if reset_at is None:
        window["history"] = False
    return window


def _fable_window(limit) -> tuple[dict, dict | None]:
    scope_model = ((limit.get("scope") or {}).get("model") or {})
    fable = {
        "label": scope_model.get("display_name") or "scoped",
        "used_pct": (
            float(limit["percent"])
            if limit.get("percent") is not None
            else None
        ),
        "reset_at": _parse_iso_ts(limit.get("resets_at")),
        "status": limit.get("severity"),
    }
    if fable["used_pct"] is None:
        return fable, None
    window = util.window(
        "model_weekly",
        label=fable["label"],
        used_pct=fable["used_pct"],
        reset_at=fable["reset_at"],
        severity=fable["status"],
    )
    if fable["reset_at"]:
        window["history_kind"] = "weekly_fable"
    else:
        window["history"] = False
    return fable, window


def to_snapshot(body: dict) -> dict:
    """Map captured Claude usage and profile responses to a snapshot."""
    usage = body.get("usage") or {}
    profile = body.get("profile")
    raw = {"usage_api": usage}
    if profile:
        raw["profile"] = profile

    limit_list = [
        limit for limit in (usage.get("limits") or [])
        if isinstance(limit, dict)
    ]
    limits = {limit.get("kind"): limit for limit in limit_list}
    windows = []
    primary = _window(usage, limits, "five_hour", "session", "5h", 18000)
    if primary:
        windows.append(primary)
    secondary = _window(
        usage, limits, "seven_day", "weekly_all", "weekly", 604800
    )
    if secondary:
        windows.append(secondary)

    for limit in limit_list:
        if limit.get("kind") != "weekly_scoped":
            continue
        fable, window = _fable_window(limit)
        raw["fable"] = fable
        if window:
            windows.append(window)
        break

    active = next((limit for limit in limit_list if limit.get("is_active")), None)
    extra = {
        "rate_limit_remaining": (active or {}).get("severity") or "normal",
        "rate_limit_limit": "unified",
    }
    if primary and primary.get("reset_at"):
        extra["rate_limit_reset"] = str(primary["reset_at"])
    raw["extra"] = extra
    return util.snapshot(
        windows,
        plan=profile.get("plan") if profile else None,
        raw=raw,
    )


def _http_error_body(error):
    raw = error.read()
    try:
        return json.loads(raw)
    except Exception:
        return raw.decode(errors="replace")


def _send(request, timeout):
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = raw.decode(errors="replace")
            return response.status, body, dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, _http_error_body(error), dict(error.headers)
    except urllib.error.URLError as error:
        return 0, str(error.reason), {}


def _send_with_retry(request, timeout):
    status, body, headers = 0, "", {}
    delay = 1.0
    for attempt in range(HTTP_RETRIES + 1):
        status, body, headers = _send(request, timeout)
        if status != 0 and status not in RETRYABLE_STATUSES:
            return status, body, headers
        if attempt == HTTP_RETRIES:
            break
        wait = delay
        retry_after = (headers or {}).get("Retry-After")
        if retry_after is not None:
            try:
                wait = max(0.0, min(float(int(retry_after)), 10.0))
            except (TypeError, ValueError):
                pass
        time.sleep(wait)
        delay *= 2
    return status, body, headers


def _get(url, headers, timeout=15):
    request = urllib.request.Request(url, method="GET")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    return _send_with_retry(request, timeout)


def _profile(token):
    """Fetch Claude subscription/account profile via the OAuth endpoint."""
    try:
        status, body, _ = _get(CLAUDE_PROFILE_URL, {
            "Authorization": f"Bearer {token['access_token']}",
            "anthropic-version": "2023-06-01",
        })
    except Exception:
        return None
    if status != 200 or not isinstance(body, dict):
        return None
    account = body.get("account") or {}
    organization = body.get("organization") or {}
    if account.get("has_claude_max"):
        plan = "Claude Max"
    elif account.get("has_claude_pro"):
        plan = "Claude Pro"
    else:
        organization_type = organization.get("organization_type") or ""
        plan = organization_type.replace("_", " ").title() or None
    return {
        "plan": plan,
        "subscription_status": organization.get("subscription_status"),
        "billing_type": organization.get("billing_type"),
        "rate_limit_tier": organization.get("rate_limit_tier"),
        "extra_usage_enabled": organization.get("has_extra_usage_enabled"),
        "subscription_created_at": organization.get("subscription_created_at"),
        "organization_type": organization.get("organization_type"),
        "display_name": account.get("display_name"),
        "full_name": account.get("full_name"),
        "org_name": organization.get("name"),
        "member_since": account.get("created_at"),
    }


def poll(conn, account, token):
    """Poll Claude via the quota-free oauth/usage endpoint (no probes)."""
    def _fetch(access_token):
        return _get(CLAUDE_USAGE_URL, {
            "Authorization": f"Bearer {access_token}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "oauth-2025-04-20",
        })

    status, body, _ = _fetch(token["access_token"])
    if status == 401 and token.get("refresh_token"):
        try:
            with work_queue.exclusive("token_refresh"):
                latest = store.get_token(conn, account["id"]) or token
                if latest["access_token"] != token["access_token"]:
                    token = latest
                else:
                    result = REFRESH(token["refresh_token"])
                    store.save_token(
                        conn,
                        account["id"],
                        result["access_token"],
                        result.get("refresh_token"),
                        result.get("id_token"),
                        result.get("expires_at"),
                        result.get("raw"),
                    )
                    store.log_event(
                        conn, account["id"], "token_refresh", True, ""
                    )
                    token = store.get_token(conn, account["id"])
            status, body, _ = _fetch(token["access_token"])
        except Exception as error:
            store.log_event(
                conn, account["id"], "token_refresh", False, str(error)
            )

    if status != 200 or not isinstance(body, dict):
        snap = {
            "status": "error",
            "status_message": f"oauth/usage HTTP {status}: {str(body)[:120]}",
        }
    else:
        snap = to_snapshot({"usage": body, "profile": _profile(token)})
    store.save_snapshot(conn, account["id"], snap)
    store.log_event(
        conn,
        account["id"],
        "limit_poll",
        snap["status"] == "active",
        snap.get("status_message", ""),
    )
