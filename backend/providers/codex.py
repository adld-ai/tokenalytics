"""OpenAI Codex quota usage, reset credits, and OAuth flow."""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import oauth
import store
from . import util

PROVIDER = "codex"
AUTH = util.AUTH_OAUTH
CAPS = frozenset({"heartbeat", "swap"})

WHAM = "https://chatgpt.com/backend-api"
CODEX = {
    "auth_url": "https://auth.openai.com/oauth/authorize",
    "token_url": "https://auth.openai.com/oauth/token",
    "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
    "redirect_uri": "http://localhost:1455/auth/callback",
    "scope": "openid email profile offline_access",
    "port": 1455,
}

RETRYABLE_STATUSES = (429, 500, 502, 503, 504)
HTTP_RETRIES = 2


def LOGIN(incognito: bool = False) -> dict:
    verifier, challenge = oauth.gen_pkce()
    state = oauth.gen_state()
    params = {
        "client_id": CODEX["client_id"],
        "response_type": "code",
        "redirect_uri": CODEX["redirect_uri"],
        "scope": CODEX["scope"],
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    auth_url = f"{CODEX['auth_url']}?{urllib.parse.urlencode(params)}"
    oauth.open_browser(auth_url, incognito)
    print("Waiting for Codex callback on port 1455...")
    result = oauth.wait_for_callback(
        CODEX["port"], host="localhost", path="/auth/callback"
    )
    if result.get("error"):
        raise RuntimeError(
            f"Codex OAuth error: "
            f"{result.get('error_description', result['error'])}"
        )
    if result.get("state") != state:
        raise RuntimeError("Codex OAuth state mismatch")
    code = result["code"]
    st, tok = oauth.http_post(CODEX["token_url"], {
        "grant_type": "authorization_code",
        "client_id": CODEX["client_id"],
        "code": code,
        "redirect_uri": CODEX["redirect_uri"],
        "code_verifier": verifier,
    })
    if st != 200:
        raise RuntimeError(f"Codex token exchange failed: {st} {tok}")
    claims = oauth.decode_jwt_payload(tok.get("id_token", ""))
    auth_info = claims.get("https://api.openai.com/auth", {})
    email = (
        claims.get("email")
        or claims.get("https://api.openai.com/profile", {}).get("email", "")
    )
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "id_token": tok.get("id_token"),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "account_id": auth_info.get("chatgpt_account_id", ""),
        "email": email,
        "plan": auth_info.get("chatgpt_plan_type", ""),
        "raw": tok,
    }


def REFRESH(refresh_token: str) -> dict:
    st, tok = oauth.http_post(CODEX["token_url"], {
        "grant_type": "refresh_token",
        "client_id": CODEX["client_id"],
        "refresh_token": refresh_token,
    })
    if st != 200:
        raise RuntimeError(f"Codex refresh failed: {st} {tok}")
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", refresh_token),
        "id_token": tok.get("id_token"),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "raw": tok,
    }


def _authorize(state: str, challenge: str) -> str:
    params = {
        "client_id": CODEX["client_id"],
        "response_type": "code",
        "redirect_uri": CODEX["redirect_uri"],
        "scope": CODEX["scope"],
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    return f"{CODEX['auth_url']}?{urllib.parse.urlencode(params)}"


def _exchange(code: str, state: str, verifier: str) -> dict:
    st, tok = oauth.http_post(CODEX["token_url"], {
        "grant_type": "authorization_code",
        "client_id": CODEX["client_id"],
        "code": code,
        "redirect_uri": CODEX["redirect_uri"],
        "code_verifier": verifier,
    })
    if st != 200:
        raise RuntimeError(f"Codex token exchange failed: {st} {tok}")
    claims = oauth.decode_jwt_payload(tok.get("id_token", ""))
    auth_info = claims.get("https://api.openai.com/auth", {})
    email = (
        claims.get("email")
        or claims.get("https://api.openai.com/profile", {}).get("email", "")
    )
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "id_token": tok.get("id_token"),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "account_id": auth_info.get("chatgpt_account_id", ""),
        "email": email,
        "plan": auth_info.get("chatgpt_plan_type", ""),
        "raw": tok,
    }


BROWSER_FLOW = {
    "host": "localhost",
    "port": CODEX["port"],
    "path": "/auth/callback",
    "pkce": True,
    "authorize": _authorize,
    "exchange": _exchange,
}


def PLAN_LABEL(plan, item) -> tuple:
    p = (plan or "").strip()
    labels = {
        "plus": ("Plus", "$20/mo"),
        "pro": ("Pro", "$200/mo"),
        "free": ("Free", "$0"),
        "team": ("Team", "$30/user/mo"),
        "business": ("Business", None),
        "enterprise": ("Enterprise", None),
    }
    return labels.get(p.lower(), (p.title() or None, None))


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

    out = {
        "credits_balance": extra.get(
            "credits_balance", snap.get("credits_balance")
        ),
        "banked_resets": extra.get(
            "banked_resets", snap.get("banked_resets")
        ),
    }
    if "reset_credits" in extra:
        from status import iso_fmt_exact

        out["reset_credits"] = [
            {
                "title": credit.get("title"),
                "status": credit.get("status"),
                "expires_at": (
                    iso_fmt_exact(credit.get("expires_at"))
                    or credit.get("expires_at")
                ),
                "granted_at": credit.get("granted_at"),
                "description": credit.get("description"),
            }
            for credit in extra.get("reset_credits") or []
            if isinstance(credit, dict)
        ]
    return {key: value for key, value in out.items() if value is not None}


def _kind_from_window_s(window_s, default):
    if not window_s:
        return default
    if 17000 <= window_s <= 19000:
        return "5h"
    if window_s == 86400:
        return "daily"
    if 500000 <= window_s < 1000000:
        return "weekly"
    if window_s >= 1000000:
        return "monthly"
    return default


def _usage_window(payload, default_kind, captured_at):
    used = payload.get("used_percent")
    if used is None:
        return None
    reset_after = payload.get("reset_after_seconds")
    reset_at = (
        captured_at + reset_after
        if captured_at is not None and reset_after is not None
        else None
    )
    window_s = payload.get("limit_window_seconds")
    window = util.window(
        _kind_from_window_s(window_s, default_kind),
        used_pct=used,
        reset_at=reset_at,
        window_s=window_s,
    )
    if reset_at is None:
        # Legacy Codex history ignored windows without a reset timestamp.
        window["history"] = False
    return window


def to_snapshot(body: dict) -> dict:
    """Map captured Codex usage and reset-credit responses to a snapshot."""
    usage = body.get("usage") or {}
    captured_at = body.get("captured_at")
    rate_limit = usage.get("rate_limit") or {}
    windows = []
    primary = _usage_window(
        rate_limit.get("primary_window") or {}, "5h", captured_at
    )
    if primary:
        windows.append(primary)
    secondary = _usage_window(
        rate_limit.get("secondary_window") or {}, "weekly", captured_at
    )
    if secondary:
        windows.append(secondary)

    extra = {
        "credits_balance": (usage.get("credits") or {}).get("balance"),
        "banked_resets": (
            usage.get("rate_limit_reset_credits") or {}
        ).get("available_count"),
    }
    if "reset_credits" in body:
        extra["reset_credits"] = body.get("reset_credits") or []
    return util.snapshot(
        windows,
        plan=usage.get("plan_type"),
        raw={"usage": usage, "extra": extra},
    )


def _http_error_body(error):
    raw = error.read()
    try:
        return json.loads(raw)
    except Exception:
        return raw.decode(errors="replace")


def _send(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
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


def _send_with_retry(req, timeout):
    st, body, headers = 0, "", {}
    delay = 1.0
    for attempt in range(HTTP_RETRIES + 1):
        st, body, headers = _send(req, timeout)
        if st != 0 and st not in RETRYABLE_STATUSES:
            return st, body, headers
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
    return st, body, headers


def _get(url, headers, timeout=15):
    req = urllib.request.Request(url, method="GET")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    return _send_with_retry(req, timeout)


def _shape_error(source, response):
    return {
        "status": "error",
        "status_message": (
            f"{source}: unexpected response shape: {str(response)[:120]}"
        ),
    }


def _stored_credit_body(credits):
    return [
        {
            "id": credit.get("credit_id"),
            "title": credit.get("title"),
            "status": credit.get("status"),
            "expires_at": credit.get("expires_at"),
            "granted_at": credit.get("granted_at"),
            "description": credit.get("description"),
        }
        for credit in credits
    ]


def poll(conn, account, token):
    try:
        stored_credits = store.list_reset_credits(conn, account["id"])
        credit_baseline = {
            credit["credit_id"]: credit["status"] for credit in stored_credits
        }
    except Exception as error:
        print(f"  pre-poll credit capture failed codex #{account['id']}: {error}")
        stored_credits, credit_baseline = [], {}
    poll_meta = {"reset_credit_baseline": credit_baseline}

    aid = account["account_id"] or ""
    headers = {
        "Authorization": f"Bearer {token['access_token']}",
        "ChatGPT-Account-Id": aid,
        "User-Agent": "agent-pool/1.0",
        "OAI-Product-Sku": "codex",
    }
    st, usage, _ = _get(f"{WHAM}/wham/usage", headers)
    if st != 200:
        snap = {
            "status": "error",
            "status_message": f"wham/usage HTTP {st}: {str(usage)[:120]}",
            "raw_json": (
                json.dumps({"usage": usage})
                if isinstance(usage, dict)
                else str(usage)
            ),
        }
        store.save_snapshot(conn, account["id"], snap)
        store.log_event(
            conn, account["id"], "limit_poll", False, snap["status_message"]
        )
        return poll_meta
    if not isinstance(usage, dict):
        snap = _shape_error("wham/usage", usage)
        store.save_snapshot(conn, account["id"], snap)
        store.log_event(
            conn, account["id"], "limit_poll", False, snap["status_message"]
        )
        return poll_meta

    captured_at = time.time()
    credit_list = _stored_credit_body(stored_credits)
    st2, credits, _ = _get(
        f"{WHAM}/wham/rate-limit-reset-credits", headers
    )
    if st2 == 200 and isinstance(credits, dict):
        credit_list = credits.get("credits") or []
        store.replace_reset_credits(conn, account["id"], credit_list)
        store.upsert_credit_history(conn, account["id"], credit_list)

    snap = to_snapshot({
        "captured_at": captured_at,
        "usage": usage,
        "reset_credits": credit_list,
    })
    store.save_snapshot(conn, account["id"], snap)
    _sync_subscription_meta(conn, account, headers)
    store.log_event(conn, account["id"], "limit_poll", True, "")
    return poll_meta


def _sync_subscription_meta(conn, account, headers):
    """Best-effort ChatGPT account metadata sync for Codex subscriptions."""
    aid = account.get("account_id") or ""
    if not aid:
        return
    existing = store.get_subscription_meta(conn, account["id"]) or {}
    account_created_at = existing.get("account_created_at")

    st, accounts_body, _ = _get(f"{WHAM}/accounts", headers)
    if st == 200 and isinstance(accounts_body, dict):
        for item in accounts_body.get("items") or []:
            if isinstance(item, dict) and item.get("id") == aid:
                account_created_at = item.get("created_time") or account_created_at
                break

    st, check_body, _ = _get(
        f"{WHAM}/accounts/check/v4-2023-04-27", headers
    )
    if st != 200 or not isinstance(check_body, dict):
        return
    entry = (check_body.get("accounts") or {}).get(aid) or {}
    acct = entry.get("account") or {}
    ent = entry.get("entitlement") or {}
    if not acct and not ent:
        return

    renews_at = ent.get("renews_at")
    expires_at = ent.get("expires_at")
    gratis = ent.get("is_active_subscription_gratis")
    plan = ent.get("subscription_plan")
    if gratis:
        note = (
            f"active free promotion; expires_at={expires_at}"
            if expires_at
            else "active free promotion"
        )
    elif ent.get("has_active_subscription"):
        note = (
            f"active paid subscription; renews_at={renews_at}"
            if renews_at
            else "active paid subscription"
        )
    else:
        note = "subscription metadata synced from accounts/check"

    store.upsert_subscription_meta(
        conn,
        account["id"],
        paid_since=existing.get("paid_since"),
        renews_at=renews_at,
        expires_at=expires_at,
        account_created_at=account_created_at,
        subscription_plan=plan,
        has_active_subscription=ent.get("has_active_subscription"),
        is_active_subscription_gratis=gratis,
        has_previously_paid_subscription=acct.get(
            "has_previously_paid_subscription"
        ),
        previous_paid_months=existing.get("previous_paid_months"),
        billing_note=note,
    )
