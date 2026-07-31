"""Antigravity / Google quota usage and OAuth flow."""
from __future__ import annotations
import datetime
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import oauth
import store
from agy_usage import fetch_usage, parse_usage_panel
from . import util

PROVIDER = "antigravity"
AUTH = util.AUTH_OAUTH
CAPS = frozenset({"heartbeat"})


# Google OAuth credentials are loaded from a gitignored file
# (secrets/antigravity.env) so they are never committed. Env vars override
# the file if set.
def _load_antigravity_creds():
    env_id = os.environ.get("ANTIGRAVITY_CLIENT_ID", "")
    env_secret = os.environ.get("ANTIGRAVITY_CLIENT_SECRET", "")
    if env_id and env_secret:
        return env_id, env_secret
    # Look for antigravity.env in the user data dir (~/solo/token-status-bar/secrets/)
    # so it is never bundled inside the read-only .app.
    data_dir = os.environ.get(
        "AGENT_POOL_DATA_DIR",
        str(os.path.expanduser("~/solo/token-status-bar/secrets")),
    )
    env_path = os.path.join(data_dir, "antigravity.env")
    file_id, file_secret = "", ""
    try:
        # Best-effort tighten: this file holds OAuth client credentials.
        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTIGRAVITY_CLIENT_ID="):
                    file_id = line.split("=", 1)[1]
                elif line.startswith("ANTIGRAVITY_CLIENT_SECRET="):
                    file_secret = line.split("=", 1)[1]
    except FileNotFoundError:
        pass
    return env_id or file_id, env_secret or file_secret


_AG_CLIENT_ID, _AG_CLIENT_SECRET = _load_antigravity_creds()
ANTIGRAVITY = {
    "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_url": "https://oauth2.googleapis.com/token",
    "client_id": _AG_CLIENT_ID,
    "client_secret": _AG_CLIENT_SECRET,
    "scope": "https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/cclog https://www.googleapis.com/auth/experimentsandconfigs",
    "port": 51121,
}


def _ensure_antigravity_creds():
    if ANTIGRAVITY["client_id"] and ANTIGRAVITY["client_secret"]:
        return
    client_id, client_secret = _load_antigravity_creds()
    ANTIGRAVITY["client_id"] = client_id
    ANTIGRAVITY["client_secret"] = client_secret


def LOGIN(incognito: bool = False) -> dict:
    _ensure_antigravity_creds()
    if not ANTIGRAVITY["client_id"] or not ANTIGRAVITY["client_secret"]:
        raise RuntimeError(
            "Antigravity Google OAuth credentials missing. Put them in "
            "secrets/antigravity.env (ANTIGRAVITY_CLIENT_ID, "
            "ANTIGRAVITY_CLIENT_SECRET) or export them as env vars."
        )
    state = oauth.gen_state()
    redirect = f"http://localhost:{ANTIGRAVITY['port']}/oauth-callback"
    params = {
        "client_id": ANTIGRAVITY["client_id"],
        "response_type": "code",
        "redirect_uri": redirect,
        "scope": ANTIGRAVITY["scope"],
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"{ANTIGRAVITY['auth_url']}?{urllib.parse.urlencode(params)}"
    oauth.open_browser(auth_url, incognito)
    print(f"Waiting for Antigravity callback on port {ANTIGRAVITY['port']}...")
    result = oauth.wait_for_callback(
        ANTIGRAVITY["port"], host="localhost", path="/oauth-callback"
    )
    if result.get("error"):
        raise RuntimeError(
            f"Antigravity OAuth error: "
            f"{result.get('error_description', result['error'])}"
        )
    if result.get("state") != state:
        raise RuntimeError("Antigravity OAuth state mismatch")
    st, tok = oauth.http_post(ANTIGRAVITY["token_url"], {
        "grant_type": "authorization_code",
        "client_id": ANTIGRAVITY["client_id"],
        "code": result["code"],
        "redirect_uri": redirect,
        "client_secret": ANTIGRAVITY["client_secret"],
    })
    if st != 200:
        raise RuntimeError(f"Antigravity token exchange failed: {st} {tok}")
    # Fetch user info
    email = ""
    st2, userinfo = oauth.http_get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        {"Authorization": f"Bearer {tok['access_token']}"},
    )[:2]
    if isinstance(userinfo, dict):
        email = userinfo.get("email", "")
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "id_token": tok.get("id_token", ""),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "account_id": "",
        "email": email,
        "plan": "",
        "raw": tok,
    }


def REFRESH(refresh_token: str) -> dict:
    # Credentials can be rotated in antigravity.env while the daemon is alive.
    client_id, client_secret = _load_antigravity_creds()
    ANTIGRAVITY["client_id"] = client_id
    ANTIGRAVITY["client_secret"] = client_secret
    _ensure_antigravity_creds()
    st, tok = oauth.http_post(ANTIGRAVITY["token_url"], {
        "grant_type": "refresh_token",
        "client_id": ANTIGRAVITY["client_id"],
        "client_secret": ANTIGRAVITY["client_secret"],
        "refresh_token": refresh_token,
    })
    if st != 200:
        raise RuntimeError(f"Antigravity refresh failed: {st} {tok}")
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", refresh_token),
        "id_token": tok.get("id_token", ""),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "raw": tok,
    }


def _authorize(state: str, challenge: str) -> str:
    _ensure_antigravity_creds()
    if not ANTIGRAVITY["client_id"] or not ANTIGRAVITY["client_secret"]:
        raise RuntimeError(
            "Antigravity Google OAuth credentials missing. Put them in "
            "secrets/antigravity.env (ANTIGRAVITY_CLIENT_ID, "
            "ANTIGRAVITY_CLIENT_SECRET) or export them as env vars."
        )
    redirect = f"http://localhost:{ANTIGRAVITY['port']}/oauth-callback"
    params = {
        "client_id": ANTIGRAVITY["client_id"],
        "response_type": "code",
        "redirect_uri": redirect,
        "scope": ANTIGRAVITY["scope"],
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{ANTIGRAVITY['auth_url']}?{urllib.parse.urlencode(params)}"


def _exchange(code: str, state: str, verifier: str) -> dict:
    _ensure_antigravity_creds()
    redirect = f"http://localhost:{ANTIGRAVITY['port']}/oauth-callback"
    st, tok = oauth.http_post(ANTIGRAVITY["token_url"], {
        "grant_type": "authorization_code",
        "client_id": ANTIGRAVITY["client_id"],
        "code": code,
        "redirect_uri": redirect,
        "client_secret": ANTIGRAVITY["client_secret"],
    })
    if st != 200:
        raise RuntimeError(f"Antigravity token exchange failed: {st} {tok}")
    email = ""
    userinfo = oauth.http_get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        {"Authorization": f"Bearer {tok['access_token']}"},
    )[1]
    if isinstance(userinfo, dict):
        email = userinfo.get("email", "")
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "id_token": tok.get("id_token", ""),
        "expires_at": time.time() + tok.get("expires_in", 3600),
        "account_id": "",
        "email": email,
        "plan": "",
        "raw": tok,
    }


BROWSER_FLOW = {
    "host": "localhost",
    "port": ANTIGRAVITY["port"],
    "path": "/oauth-callback",
    "pkce": False,
    "authorize": _authorize,
    "exchange": _exchange,
}


def PLAN_LABEL(plan, item) -> tuple:
    p = (plan or "").strip()
    tid = item.get("tier_id")
    override = (item.get("tier_override") or "").lower()
    if override:
        if "ultra" in override and "20" in override:
            return ("Google AI Ultra 20x", None)
        if "ultra" in override or "5x" in override:
            return ("Google AI Ultra 5x", None)
        if "pro" in override:
            return ("Google AI Pro", None)
        if "plus" in override:
            return ("Google AI Plus", None)
    labels = {
        "g1-plus-tier": ("Google AI Plus", None),
        "g1-pro-tier": ("Google AI Pro", "$19.99/mo"),
        "g1-ultra-tier": ("Google AI Ultra", None),
        "g1-ultra-5x-tier": ("Google AI Ultra 5x", None),
        "g1-ultra-20x-tier": ("Google AI Ultra 20x", None),
        "free-tier": ("Free", "$0"),
        "standard-tier": ("Antigravity", None),
    }
    return labels.get(tid, (p or None, None))


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
    from status import ts_fmt

    out = {
        "tier_id": extra.get("tier_id"),
        "tier_description": extra.get("tier_description"),
        "active_tier": extra.get("active_tier"),
        "rate_limit_remaining": extra.get("rate_limit_remaining"),
        "rate_limit_limit": extra.get("rate_limit_limit"),
        "rate_limit_reset": extra.get("rate_limit_reset"),
    }
    exported = []
    for window in extra.get("usage_windows") or []:
        if not isinstance(window, dict) or window.get("remaining_pct") is None:
            continue
        used = 100.0 - float(window["remaining_pct"])
        exported.append({
            "group": window.get("group"),
            "window": window.get("window"),
            "used_pct": round(max(0.0, min(100.0, used)), 2),
            "reset": ts_fmt(window["reset_at"]) if window.get("reset_at") else None,
        })
    if exported:
        out["usage_windows"] = exported
    return {key: value for key, value in out.items() if value is not None}


def _quota(models, plan):
    """Reduce per-model quotaInfo to the most-constrained display window."""
    worst = None  # (remainingFraction, resetTime, label)
    for key, info in models.items():
        qi = info.get("quotaInfo")
        if not qi:
            continue
        label = info.get("displayName") or key
        low = label.lower()
        if (
            low.startswith("chat_")
            or low.startswith("rev19")
            or low.startswith("tab_")
            or "gemini 2.5" in low
            or "image" in low
        ):
            continue
        frac = qi.get("remainingFraction")
        if frac is None:
            continue
        if worst is None or frac < worst[0]:
            worst = (frac, qi.get("resetTime"), label)

    if worst is None:
        window = util.window("model_weekly", used_pct=0.0)
        window["history"] = False
        return window, {
            "rate_limit_remaining": "available",
            "rate_limit_limit": plan,
            "rate_limit_reset": "unknown",
        }, "active", ""

    frac, reset_iso, label = worst
    used = max(0.0, min(100.0, (1.0 - frac) * 100.0))
    reset_at = None
    if reset_iso:
        try:
            reset_at = datetime.datetime.fromisoformat(
                reset_iso.replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            pass
    window = util.window(
        "model_weekly", used_pct=used, reset_at=reset_at, label=label
    )
    if reset_at is None:
        window["history"] = False
    else:
        window["history_kind"] = "5h"
    extra = {
        "rate_limit_limit": plan,
        "rate_limit_remaining": f"{frac * 100:.0f}% left ({label})",
    }
    if not reset_iso:
        extra["rate_limit_reset"] = "rolling"
    status = "rate_limited" if frac <= 0 else "active"
    message = "quota exhausted" if frac <= 0 else ""
    return window, extra, status, message


def to_snapshot(body: dict) -> dict:
    """Map Code Assist, model-quota, and optional CLI usage to a snapshot."""
    code_assist = body.get("code_assist") or {}
    current = code_assist.get("currentTier", {})
    paid = code_assist.get("paidTier") or {}
    allowed = code_assist.get("allowedTiers") or []
    # The session's active Code Assist tier is currentTier (often free-tier),
    # but the user's actual entitlement lives in paidTier. Prefer paidTier.
    tier = paid if paid.get("id") else current
    if not tier.get("id") and allowed:
        tier = allowed[0]
    plan = tier.get("name", "Gemini Code Assist")
    tier_id = tier.get("id")
    active_tier_id = current.get("id")

    windows = []
    quota_extra = {}
    status = body.get("status", "active")
    status_message = body.get("status_message", "")
    models = body.get("models")
    if isinstance(models, dict):
        model_window, quota_extra, quota_status, quota_message = _quota(models, plan)
        windows.append(model_window)
        if status == "active":
            status = quota_status
            status_message = quota_message

    usage_windows = body.get("usage_windows")
    for usage in usage_windows or []:
        if not isinstance(usage, dict) or usage.get("remaining_pct") is None:
            continue
        kind = "weekly" if usage.get("window") == "weekly" else "5h"
        window = util.window(
            kind,
            remaining_pct=usage["remaining_pct"],
            reset_at=usage.get("reset_at"),
            label=usage.get("group"),
        )
        if usage.get("reset_at") is None:
            window["history"] = False
        else:
            window["history_kind"] = f"{kind}_{usage.get('group') or 'other'}"
        windows.append(window)

    extra = {
        "tier_id": tier_id,
        "tier_description": tier.get("description"),
        "active_tier": (
            active_tier_id
            if active_tier_id and active_tier_id != tier_id
            else None
        ),
        "usage_windows": usage_windows,
        **quota_extra,
    }
    return util.snapshot(
        windows,
        plan=plan,
        raw={"extra": extra},
        status=status,
        status_message=status_message,
    )


def _shape_error(source, resp):
    return {
        "status": "error",
        "status_message": f"{source}: unexpected response shape: {str(resp)[:120]}",
    }


def poll(conn, account, token):
    # Step 1: loadCodeAssist to get tier info + project ID
    url = "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist"
    body = json.dumps({"metadata": {}}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token['access_token']}")
    req.add_header("Accept", "*/*")
    req.add_header(
        "User-Agent",
        "antigravity/cli/1.0.13 (aidev_client; os_type=darwin; arch=arm64)",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            code_assist = json.loads(response.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:120]
        snap = {
            "status": "error",
            "status_message": f"loadCodeAssist HTTP {e.code}: {msg}",
        }
        store.save_snapshot(conn, account["id"], snap)
        store.log_event(
            conn, account["id"], "limit_poll", False, snap["status_message"]
        )
        return
    except urllib.error.URLError as e:
        snap = {"status": "error", "status_message": str(e.reason)}
        store.save_snapshot(conn, account["id"], snap)
        store.log_event(
            conn, account["id"], "limit_poll", False, snap["status_message"]
        )
        return
    except json.JSONDecodeError as e:
        snap = _shape_error("loadCodeAssist", f"invalid JSON: {e}")
        store.save_snapshot(conn, account["id"], snap)
        store.log_event(
            conn, account["id"], "limit_poll", False, snap["status_message"]
        )
        return
    if not isinstance(code_assist, dict):
        snap = _shape_error("loadCodeAssist", code_assist)
        store.save_snapshot(conn, account["id"], snap)
        store.log_event(
            conn, account["id"], "limit_poll", False, snap["status_message"]
        )
        return

    project = code_assist.get("cloudaicompanionProject", "")

    # Step 2: fetch real-time per-model quota via fetchAvailableModels.
    # Response: models[<key>].quotaInfo.remainingFraction (0..1) + .resetTime (ISO8601).
    # This is a metadata call -- it reports quota without consuming a request.
    models_url = "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"
    payload = json.dumps({"project": project}).encode()
    req = urllib.request.Request(models_url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token['access_token']}")
    req.add_header("Accept", "*/*")
    req.add_header("User-Agent", "antigravity")

    mapped = {"code_assist": code_assist}
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            resp = json.loads(response.read())
        if isinstance(resp, dict):
            mapped["models"] = resp.get("models") or {}
        else:
            mapped["status"] = "error"
            mapped["status_message"] = (
                "fetchAvailableModels: unexpected response shape: "
                f"{str(resp)[:120]}"
            )
    except urllib.error.HTTPError as e:
        body_resp = e.read().decode(errors="replace")[:120]
        mapped["status"] = "error"
        mapped["status_message"] = (
            f"fetchAvailableModels HTTP {e.code}: {body_resp}"
        )
    except urllib.error.URLError as e:
        mapped["status"] = "error"
        mapped["status_message"] = str(e.reason)
    except json.JSONDecodeError as e:
        mapped["status"] = "error"
        mapped["status_message"] = f"fetchAvailableModels: invalid JSON: {e}"

    try:
        mapped["usage_windows"] = fetch_usage()
    except Exception:
        mapped["usage_windows"] = None

    snap = to_snapshot(mapped)
    store.save_snapshot(conn, account["id"], snap)
    store.log_event(
        conn,
        account["id"],
        "limit_poll",
        snap["status"] == "active",
        snap.get("status_message", ""),
    )
