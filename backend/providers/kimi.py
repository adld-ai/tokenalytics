"""Kimi Code subscription usage.

One GET returns everything the menu bar needs: a 7-day window, a rolling
5-hour window, plan tier and reset timestamps. The credential is the Kimi
Code CLI's own file, so there is no Token Bar login for this provider — the
adapter only runs once an account row with provider="kimi" exists, and it
touches nothing before that.

Endpoint and OAuth client are undocumented; they were read out of the
shipped `kimi` binary and confirmed against a live 200. Treat every field as
optional.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path

import store
import work_queue
from . import util

PROVIDER = "kimi"
AUTH = util.AUTH_LOCAL_FILE

KIMI_HOME = Path(os.environ.get("KIMI_CODE_HOME", str(Path.home() / ".kimi-code")))
CRED_PATH = KIMI_HOME / "credentials" / "kimi-code.json"
USAGE_URL = os.environ.get("KIMI_CODE_BASE_URL",
                           "https://api.kimi.com/coding/v1") + "/usages"
TOKEN_URL = os.environ.get("KIMI_CODE_OAUTH_HOST",
                           "https://auth.kimi.com") + "/api/oauth/token"
CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"

# access_token lives 900s. Refresh with room to spare rather than racing it.
REFRESH_LEAD_S = 120
# Set to "0" to never write the credential file back (poll fails once the
# CLI's own token expires, but Token Bar never touches the user's login).
ALLOW_REFRESH = os.environ.get("TOKENBAR_KIMI_REFRESH", "1") != "0"


def _num(v, default=None):
    """Kimi sends counts as JSON strings, and omits them entirely when zero
    (proto3 zero-omission), so every read goes through this."""
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _window_s(win) -> int | None:
    """Seconds from a {duration, timeUnit} pair."""
    dur = _num(util.dig(win, "duration"))
    if dur is None:
        return None
    unit = util.dig(win, "timeUnit") or ""
    per = {"TIME_UNIT_SECOND": 1, "TIME_UNIT_MINUTE": 60,
           "TIME_UNIT_HOUR": 3600, "TIME_UNIT_DAY": 86400}.get(unit)
    return int(dur * per) if per else None


def _used_pct(detail):
    """used/limit as a percentage. `used` is absent when zero, so it is
    derived from remaining when missing."""
    limit = _num(util.dig(detail, "limit"))
    if not limit or limit <= 0:
        return None
    used = _num(util.dig(detail, "used"))
    if used is None:
        remaining = _num(util.dig(detail, "remaining"))
        used = limit - remaining if remaining is not None else 0.0
    return max(0.0, min(100.0, 100.0 * used / limit))


def to_snapshot(body: dict) -> dict:
    """Map a /usages response to a snapshot (pure — the tested part)."""
    windows = []
    weekly = body.get("usage") or {}
    pct = _used_pct(weekly)
    if pct is not None:
        # The weekly block carries no window descriptor; the official CLI
        # assumes 1 week and so do we.
        windows.append(util.window("weekly", used_pct=pct, window_s=604800,
                                   reset_at=weekly.get("resetTime")))
    for lim in body.get("limits") or []:
        if not isinstance(lim, dict):
            continue
        detail = lim.get("detail") or {}
        pct = _used_pct(detail)
        if pct is None:
            continue
        secs = _window_s(lim.get("window"))
        kind = "5h" if secs and 17000 <= secs <= 19000 else None
        windows.append(util.window(kind, used_pct=pct, window_s=secs,
                                   reset_at=detail.get("resetTime")))
    raw = {"membership": util.dig(body, "user", "membership", "level"),
           "region": util.dig(body, "user", "region"),
           "parallel_limit": util.dig(body, "parallel", "limit"),
           "sub_type": body.get("subType")}
    return util.snapshot(windows,
                         plan=util.dig(body, "user", "membership", "level"),
                         raw={k: v for k, v in raw.items() if v is not None})


def _read_creds():
    return util.read_json(CRED_PATH)


def _write_creds(creds: dict) -> None:
    """Replace the credential file atomically, keeping 0600.

    The Kimi CLI rotates refresh tokens, so the new one must land or the
    user's CLI login breaks. Written to a temp file in the same directory
    and renamed, so a reader never sees a half-written file.
    """
    CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CRED_PATH.with_name(CRED_PATH.name + ".tokenbar.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(creds, f)
        os.replace(tmp, CRED_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _refresh(creds: dict) -> dict:
    """Exchange the rotating refresh token and persist the result."""
    st, body = util.post_form(TOKEN_URL, {
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": creds.get("refresh_token") or "",
    })
    if st != 200 or not isinstance(body, dict) or not body.get("access_token"):
        raise RuntimeError(f"kimi token refresh HTTP {st}: {str(body)[:120]}")
    merged = dict(creds)
    merged.update(body)
    if body.get("expires_in") and not body.get("expires_at"):
        merged["expires_at"] = int(time.time()) + int(body["expires_in"])
    _write_creds(merged)
    return merged


def _fresh_token(conn, account) -> str:
    creds = _read_creds()
    if not creds or not creds.get("access_token"):
        raise RuntimeError(f"no Kimi Code credential at {CRED_PATH}")
    expires_at = creds.get("expires_at") or 0
    if expires_at and expires_at - time.time() > REFRESH_LEAD_S:
        return creds["access_token"]
    if not ALLOW_REFRESH:
        raise RuntimeError("Kimi access token expired; run the kimi CLI to renew")
    # The CLI shares this file, so serialize our own refreshes and re-read
    # inside the lock — the CLI may have renewed it while we waited.
    with work_queue.exclusive("kimi_token_refresh"):
        creds = _read_creds() or creds
        expires_at = creds.get("expires_at") or 0
        if expires_at and expires_at - time.time() > REFRESH_LEAD_S:
            return creds["access_token"]
        creds = _refresh(creds)
        store.log_event(conn, account["id"], "token_refresh", True, "kimi")
    return creds["access_token"]


def poll(conn, account, token):
    try:
        access = _fresh_token(conn, account)
    except Exception as e:
        store.save_snapshot(conn, account["id"], util.error(e))
        store.log_event(conn, account["id"], "limit_poll", False, str(e))
        raise

    st, body, _ = util.get_json(USAGE_URL, {
        "Authorization": f"Bearer {access}",
        "Accept": "application/json",
    })
    if st != 200 or not isinstance(body, dict):
        snap = util.error(f"usages HTTP {st}: {str(body)[:120]}")
    else:
        snap = to_snapshot(body)
    store.save_snapshot(conn, account["id"], snap)
    store.log_event(conn, account["id"], "limit_poll",
                    snap["status"] == "active", snap.get("status_message", ""))
