"""GitHub Copilot premium-request quota usage."""
from __future__ import annotations
import datetime
import json
import time
import urllib.error
import urllib.request

import oauth
import store
from . import util

PROVIDER = "copilot"
AUTH = util.AUTH_OAUTH
CAPS = frozenset()

COPILOT = {
    "device_code_url": "https://github.com/login/device/code",
    "token_url": "https://github.com/login/oauth/access_token",
    "copilot_token_url": "https://api.github.com/copilot_internal/v2/token",
    "client_id": "Iv1.b507a08c87ecfe98",
    "scope": "read:user",
}

# Copilot uses a device flow inside LOGIN, not the callback-based browser flow.
BROWSER_FLOW = None

# IDE headers required for copilot_internal/user to return quota_snapshots.
COPILOT_IDE_HEADERS = {
    "Accept-Encoding": "identity",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "X-Github-Api-Version": "2025-04-01",
}

RETRYABLE_STATUSES = (429, 500, 502, 503, 504)
HTTP_RETRIES = 2


def LOGIN(incognito: bool = False) -> dict:
    # Step 1: request device code
    st, resp = oauth.http_post_json(COPILOT["device_code_url"], {
        "client_id": COPILOT["client_id"],
        "scope": COPILOT["scope"],
    }, {"User-Agent": "agent-pool/1.0", "Accept": "application/json"})
    if st != 200:
        raise RuntimeError(f"Copilot device code request failed: {st} {resp}")
    device_code = resp["device_code"]
    user_code = resp["user_code"]
    verification_uri = resp.get("verification_uri", "https://github.com/login/device")
    interval = resp.get("interval", 5)
    expires_in = resp.get("expires_in", 899)

    print("\n=== GitHub Copilot Device Flow ===")
    print(f"Open: {verification_uri}")
    print(f"Enter code: {user_code}")
    oauth.open_browser(verification_uri)
    print(f"Waiting for authorization (expires in {expires_in}s)...")

    # Step 2: poll for token
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        st, tok = oauth.http_post_json(COPILOT["token_url"], {
            "client_id": COPILOT["client_id"],
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }, {"User-Agent": "agent-pool/1.0", "Accept": "application/json"})
        if st == 200 and isinstance(tok, dict) and tok.get("access_token"):
            break
        if isinstance(tok, dict):
            err = tok.get("error", "")
            if err == "authorization_pending":
                continue
            elif err == "slow_down":
                interval += 5
                continue
            elif err == "expired_token":
                raise RuntimeError("Copilot device code expired")
            else:
                raise RuntimeError(f"Copilot token poll error: {tok}")
    else:
        raise RuntimeError("Copilot device flow timed out")

    github_token = tok["access_token"]

    # Step 3: fetch GitHub user info
    st2, user = oauth.http_get(
        "https://api.github.com/user",
        {"Authorization": f"token {github_token}", "User-Agent": "agent-pool/1.0"},
    )[:2]
    username = ""
    github_user_id = ""
    if isinstance(user, dict):
        username = user.get("login", "")
        github_user_id = str(user.get("id", ""))

    # Step 4: exchange for Copilot token
    st3, ctoken_resp = oauth.http_get(
        COPILOT["copilot_token_url"],
        {
            "Authorization": f"token {github_token}",
            "User-Agent": "agent-pool/1.0",
            "X-GitHub-Api-Version": "2025-04-01",
        },
    )[:2]

    copilot_token = ""
    copilot_expires = 0
    if isinstance(ctoken_resp, dict):
        copilot_token = ctoken_resp.get("token", "")
        copilot_expires = ctoken_resp.get("expires_at", 0)

    return {
        "access_token": github_token,  # the github oauth token (long-lived)
        "refresh_token": None,  # GitHub device flow has no refresh token
        "id_token": "",
        "expires_at": copilot_expires or (time.time() + 7200),
        "account_id": github_user_id,
        "email": username,  # GitHub username as identifier
        "plan": "copilot",
        "raw": {
            "github_token": github_token,
            "copilot_token": copilot_token,
            "copilot_expires_at": copilot_expires,
            "user": user if isinstance(user, dict) else {},
        },
    }


def REFRESH(github_token: str) -> dict:
    """Re-exchange the GitHub token for a new Copilot token."""
    st, resp = oauth.http_get(
        COPILOT["copilot_token_url"],
        {
            "Authorization": f"token {github_token}",
            "User-Agent": "agent-pool/1.0",
            "X-GitHub-Api-Version": "2025-04-01",
        },
    )[:2]
    if st != 200:
        raise RuntimeError(f"Copilot token refresh failed: {st} {resp}")
    return {
        "access_token": github_token,
        "copilot_token": resp.get("token", ""),
        "expires_at": resp.get("expires_at", 0),
        "raw": resp,
    }


def PLAN_LABEL(plan, item) -> tuple:
    p = (plan or "").strip()
    labels = {
        "free": ("Copilot Free", "$0"),
        "individual": ("Copilot Pro", "$10/mo"),
        "individual_pro": ("Copilot Pro", "$10/mo"),
        "individual_proplus": ("Copilot Pro+", "$39/mo"),
        "individual_max": ("Copilot Max", "$100/mo"),
        "business": ("Copilot Business", "$19/user/mo"),
        "enterprise": ("Copilot Enterprise", "$39/user/mo"),
    }
    return labels.get(p.lower(), (p or None, None))


def ACCOUNT_STATE(item) -> dict:
    sku = (item.get("sku") or item.get("access_sku") or "").lower()
    subscription = "unknown"
    if sku:
        subscription = "free" if "free" in sku else "paid"
    return {"subscription": subscription,
            "renews_at": item.get("plan_reset")}


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
    from status import iso_fmt, previous_month, reset_fmt

    out = {
        "access_sku": extra.get("access_sku"),
        "premium_entitlement": extra.get("premium_entitlement"),
        "premium_overage": extra.get("premium_overage"),
        "chat_unlimited": extra.get("chat_unlimited"),
        "completions_unlimited": extra.get("completions_unlimited"),
        "can_upgrade": extra.get("can_upgrade"),
        "organizations": extra.get("organizations"),
        "github_email": extra.get("github_email"),
        "github_name": extra.get("github_name"),
        "rate_limit_remaining": extra.get("rate_limit_remaining"),
        "rate_limit_reset": reset_fmt(extra.get("rate_limit_reset")),
        "rate_limit_limit": extra.get("rate_limit_limit"),
    }
    reset_date = raw.get("reset")
    if reset_date:
        out["plan_reset"] = iso_fmt(reset_date) or reset_date
        start_dt = previous_month(reset_date)
        if start_dt:
            out["plan_start"] = start_dt.strftime("%Y-%m-%d")
    return {key: value for key, value in out.items() if value is not None}


def _reset_epoch(reset_date):
    if not reset_date:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(reset_date))
        # Naive timestamps are UTC; explicit offsets must be preserved.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def to_snapshot(body: dict) -> dict:
    """Map Copilot token and user responses to a snapshot (pure)."""
    if "user" in body or "token" in body:
        user = body.get("user") or {}
        token_body = body.get("token") or {}
    else:
        user = body
        token_body = {}

    qs = user.get("quota_snapshots") or {}
    pi = qs.get("premium_interactions") or {}
    ch = qs.get("chat") or {}
    reset_date = (user.get("quota_reset_date")
                  or token_body.get("limited_user_reset_date"))
    reset_at = _reset_epoch(reset_date)
    windows = []

    prem_rem = pi.get("percent_remaining")
    status = "active"
    status_message = ""
    if pi.get("unlimited"):
        premium_used = 0.0
        rate_remaining = "unlimited premium"
        rate_limit = "premium (unlimited)"
    elif prem_rem is not None:
        premium_used = max(0.0, min(100.0, 100.0 - prem_rem))
        rate_remaining = f"{prem_rem:.1f}% premium left"
        rate_limit = "premium requests"
        if prem_rem <= 0:
            status = "rate_limited"
            status_message = "premium quota exhausted"
    else:
        premium_used = 0.0
        rate_remaining = "ok"
        rate_limit = "copilot quota"
    windows.append(util.window("monthly", label="premium",
                               used_pct=premium_used, reset_at=reset_at))

    chat_rem = ch.get("percent_remaining")
    if chat_rem is not None and not ch.get("unlimited"):
        chat_used = max(0.0, min(100.0, 100.0 - chat_rem))
        windows.append(util.window("monthly", label="chat",
                                   used_pct=chat_used, reset_at=reset_at))

    sku = token_body.get("sku") or user.get("access_type_sku")
    limited_quota = token_body.get("limited_user_quotas")
    raw = {
        "extra": {
            "access_sku": sku,
            "premium_entitlement": pi.get("entitlement"),
            "premium_overage": pi.get("overage_count"),
            "chat_unlimited": ch.get("unlimited"),
            "completions_unlimited": (qs.get("completions") or {}).get("unlimited"),
            "can_upgrade": user.get("can_upgrade_plan"),
            "organizations": ", ".join(user.get("organization_login_list") or []) or None,
            "limited_user_quotas": limited_quota,
            "limited_user_reset_date": token_body.get("limited_user_reset_date"),
            "rate_limit_remaining": rate_remaining,
            "rate_limit_reset": reset_date or "monthly",
            "rate_limit_limit": limited_quota if limited_quota is not None else rate_limit,
        },
        "plan": user.get("copilot_plan"),
        "reset": reset_date,
    }
    return util.snapshot(windows, plan=user.get("copilot_plan"), raw=raw,
                         status=status, status_message=status_message)


def _http_error_body(e):
    """Read an HTTPError body once; JSON when possible, text otherwise."""
    raw = e.read()
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
    except urllib.error.HTTPError as e:
        return e.code, _http_error_body(e), dict(e.headers)
    except urllib.error.URLError as e:
        return 0, str(e.reason), {}


def _send_with_retry(req, timeout):
    """Bounded retry on 429/5xx and network errors."""
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
                wait = max(0.0, min(float(int(retry_after)), 10.0))
            except (TypeError, ValueError):
                pass
        time.sleep(wait)
        delay *= 2
    return st, body, hdrs


def _get(url, headers, timeout=15):
    req = urllib.request.Request(url, method="GET")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    return _send_with_retry(req, timeout)


def _shape_error(source, resp):
    """Error snapshot for a response that isn't the expected JSON object."""
    return {
        "status": "error",
        "status_message": f"{source}: unexpected response shape: {str(resp)[:120]}",
    }


def poll(conn, account, token):
    # Step 1: refresh the copilot token. The copilot_internal/v2/token endpoint
    # intermittently returns HTTP 403 "Resource not accessible by integration" -
    # a transient GitHub-side entitlement re-check that resolves on the next
    # poll. Retry once after a short backoff; if it still fails, hold the last
    # good snapshot (so the menu bar doesn't flip red for one bad poll) and only
    # write an error when there is no prior active snapshot to hold.
    raw = json.loads(token["raw_json"]) if token["raw_json"] else {}
    github_token = raw.get("github_token") or token["access_token"]
    token_url = "https://api.github.com/copilot_internal/v2/token"
    token_hdrs = {
        "Authorization": f"token {github_token}",
        "User-Agent": "agent-pool/1.0",
        "X-GitHub-Api-Version": "2025-04-01",
    }
    st, resp, hdrs = _get(token_url, token_hdrs)
    if st in (403, 500, 502, 503, 504):
        time.sleep(2)
        st, resp, hdrs = _get(token_url, token_hdrs)
    if st != 200 or not isinstance(resp, dict):
        msg = f"token refresh HTTP {st}: {str(resp)[:120]}"
        # A "subscription has ended" 403 is permanent (plan lapsed/cancelled),
        # not a transient entitlement re-check: never hold the stale snapshot.
        if "subscription has ended" in str(resp).lower():
            snap = {
                "status": "error",
                "status_message": "Copilot subscription has ended",
            }
            store.save_snapshot(conn, account["id"], snap)
            store.log_event(conn, account["id"], "limit_poll", False,
                            snap["status_message"])
            return
        prior = store.latest_snapshot(conn, account["id"])
        if prior and prior.get("status") == "active":
            # Hold the last good snapshot; log the transient failure for audit.
            store.log_event(conn, account["id"], "limit_poll", False, msg)
            return
        snap = {"status": "error", "status_message": msg}
        store.save_snapshot(conn, account["id"], snap)
        store.log_event(conn, account["id"], "limit_poll", False,
                        snap["status_message"])
        return

    copilot_token = resp.get("token", "")
    expires = resp.get("expires_at", 0)
    sku = resp.get("sku", "")
    raw["copilot_token"] = copilot_token
    raw["copilot_expires_at"] = expires
    store.save_token(conn, account["id"], token["access_token"], None, "",
                     expires or (time.time() + 7200), raw)

    # Step 2: fetch real-time premium-request quota via copilot_internal/user.
    # quota_snapshots.premium_interactions.percent_remaining is the headline number;
    # the plain v2/token endpoint reports limited_user_quotas=null for most SKUs.
    req = urllib.request.Request(
        "https://api.github.com/copilot_internal/user",
        headers={"Authorization": f"token {github_token}", **COPILOT_IDE_HEADERS},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            user = json.loads(response.read())
        if isinstance(user, dict):
            snap = to_snapshot({"user": user, "token": resp})
        else:
            snap = _shape_error("copilot_internal/user", user)
            snap["sku"] = sku
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:120]
        snap = {
            "status": "error" if e.code != 429 else "rate_limited",
            "status_message": f"user HTTP {e.code}: {msg}",
            "sku": sku,
        }
    except urllib.error.URLError as e:
        snap = {"status": "error", "status_message": str(e.reason), "sku": sku}
    except json.JSONDecodeError as e:
        snap = _shape_error("copilot_internal/user", f"invalid JSON: {e}")
        snap["sku"] = sku

    # Best-effort: real email/name via the public user endpoint. Email is often
    # null (private profile / token lacks user:email scope); captured when present.
    if snap.get("raw_json"):
        _copilot_attach_identity(snap, github_token)

    store.save_snapshot(conn, account["id"], snap)
    store.log_event(conn, account["id"], "limit_poll",
                    snap["status"] == "active", snap.get("status_message", ""))


def _copilot_attach_identity(snap, github_token):
    """Merge github_email / github_name into snap raw extra when available."""
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {github_token}",
                "User-Agent": "agent-pool/1.0",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            user = json.loads(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return
    payload = json.loads(snap["raw_json"]) if snap.get("raw_json") else {}
    extra = payload.setdefault("extra", {})
    extra["github_email"] = user.get("email")
    extra["github_name"] = user.get("name")
    snap["raw_json"] = json.dumps(payload)
