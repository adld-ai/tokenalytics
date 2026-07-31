"""Helpers shared by provider adapters.

The point of these is that an adapter should be a thin mapping from one
vendor's payload to a list of windows — no SQL, no schema knowledge, no
snapshot-column trivia. snapshot() serializes the windows into raw_json, which
status.declared_windows() and window_history.declared() both read, so a new
provider ships without touching the limit_snapshots schema.
"""
from __future__ import annotations
import json, subprocess
from pathlib import Path
from typing import Any

import oauth

# How an adapter obtains its credential. The first two keep a row in the
# tokens table; the last two do not, which is what lets Token Bar sync tools
# that never had a Token Bar login (a CLI already logged in on this machine,
# or a purely local runtime).
AUTH_OAUTH = "oauth"            # Token Bar runs the OAuth dance itself
AUTH_API_KEY = "api_key"        # user pastes a key; stored as access_token
AUTH_LOCAL_FILE = "local_file"  # read the vendor CLI's own credential file
AUTH_NONE = "none"              # no credential at all (localhost / disk only)

AUTH_KINDS = (AUTH_OAUTH, AUTH_API_KEY, AUTH_LOCAL_FILE, AUTH_NONE)
TOKENLESS = (AUTH_LOCAL_FILE, AUTH_NONE)

MAX_MESSAGE = 200


def window(kind, *, used_pct=None, remaining_pct=None, reset_at=None,
           label=None, window_s=None, severity=None, is_active=None,
           source=None, boundary=None) -> dict:
    """One quota window in the shape the consumers agree on.

    Pass used_pct or remaining_pct, whichever the vendor reports — inverting
    is the reader's job so the adapter stays a straight transcription. Unset
    fields are dropped rather than stored as null.
    """
    w = {"kind": kind, "used_pct": used_pct, "remaining_pct": remaining_pct,
         "reset_at": reset_at, "label": label, "window_s": window_s,
         "severity": severity, "is_active": is_active, "source": source,
         "boundary": boundary}
    return {k: v for k, v in w.items() if v is not None}


def snapshot(windows=(), *, plan=None, raw=None, status="active",
             status_message="", source=None) -> dict:
    """A snapshot dict for store.save_snapshot().

    windows always lands in raw_json, even when empty: an empty list is an
    adapter saying "I looked and there is no quota data", which must not fall
    through to the legacy per-provider column branches.
    """
    rj = dict(raw or {})
    rj["windows"] = list(windows)
    snap = {"status": status, "status_message": status_message,
            "raw_json": json.dumps(rj)}
    if plan:
        snap["plan"] = plan
    if source:
        snap["source"] = source
    return snap


def error(message) -> dict:
    """A failed-poll snapshot. Carries no windows, so the previous good
    reading stays the newest successful one."""
    return {"status": "error", "status_message": str(message)[:MAX_MESSAGE]}


def read_json(path) -> Any | None:
    """Parsed JSON at path, or None when it is missing or malformed.

    Vendor credential files come and go as their CLIs log in and out; an
    adapter must treat both as "no data", never as an exception.
    """
    try:
        return json.loads(Path(path).expanduser().read_text())
    except (OSError, ValueError):
        return None


def first_existing(*paths) -> Path | None:
    """The first path that exists, or None. For vendors that moved their
    config dir between versions and still support both."""
    for p in paths:
        if not p:
            continue
        q = Path(p).expanduser()
        if q.exists():
            return q
    return None


def run_json(cmd, timeout=10, env=None) -> Any | None:
    """JSON on a command's stdout, or None if it fails, times out, is missing,
    or prints something that is not JSON."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def dig(obj, *path, default=None):
    """Walk nested dict keys / list indices, returning default on any miss."""
    cur = obj
    for step in path:
        try:
            cur = cur[step]
        except (KeyError, IndexError, TypeError):
            return default
    return cur


def get_json(url, headers=None) -> tuple[int, Any, dict]:
    """GET returning (status, parsed_body, response_headers).

    Response headers are handed back deliberately: for several vendors the
    only quota signal is an x-ratelimit-* header on an ordinary call.
    """
    return oauth.http_get(url, headers or {})


def post_form(url, data, headers=None) -> tuple[int, Any]:
    """POST application/x-www-form-urlencoded — the OAuth token-endpoint shape."""
    return oauth.http_post(url, data, headers or {})
