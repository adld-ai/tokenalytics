#!/usr/bin/env python3
"""Push the already-written status.json to the token-bar-status Cloudflare
Worker so the mobile dashboard has something to read.

Reads the same file the menu bar app and browser panel already trust
(status.STATUS_JSON, overridable via AGENT_POOL_STATUS_JSON) and forwards its
bytes verbatim — no separate DB read, so this can never disagree with what's
on screen locally. The Mac backend keeps binding 127.0.0.1 only (see
server.py's docstring); this script only ever makes outbound requests.

Usage:
  python3 backend/cloud_push.py            # one-shot push
  python3 backend/cloud_push.py --loop      # push whenever the file changes

Config (env):
  TOKEN_BAR_WORKER_URL    Worker base URL (required)
  TOKEN_BAR_PUSH_TOKEN    push bearer token (required)
  CLOUD_PUSH_INTERVAL_S   loop poll interval, default 20
  AGENT_POOL_STATUS_JSON  status.json path override (defaults like status.py)

Both required values may instead live in `secrets/cloud.env` (KEY=value lines,
0600) next to status.json, so the LaunchAgent doesn't have to carry secrets in
its plist. Real environment variables win over the file.
"""
from __future__ import annotations
import os
import sys
import time
import urllib.error
import urllib.request

import status


def _load_env_file() -> None:
    """Merge secrets/cloud.env into os.environ without clobbering real env."""
    path = status.STATUS_JSON.with_name("cloud.env")
    try:
        text = path.read_text()
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file()

WORKER_URL = os.environ.get("TOKEN_BAR_WORKER_URL", "").rstrip("/")
PUSH_TOKEN = os.environ.get("TOKEN_BAR_PUSH_TOKEN", "")
INTERVAL_S = int(os.environ.get("CLOUD_PUSH_INTERVAL_S", "20"))


def push_once() -> bool:
    if not WORKER_URL or not PUSH_TOKEN:
        print("cloud_push: TOKEN_BAR_WORKER_URL / TOKEN_BAR_PUSH_TOKEN not set; skipping",
              file=sys.stderr)
        return False
    try:
        body = status.STATUS_JSON.read_bytes()
    except OSError as e:
        print(f"cloud_push: cannot read {status.STATUS_JSON}: {e}", file=sys.stderr)
        return False
    req = urllib.request.Request(f"{WORKER_URL}/push", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {PUSH_TOKEN}")
    req.add_header("User-Agent", "token-bar-cloud-push/1.0")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
            print(f"cloud_push: pushed {len(body)} bytes (HTTP {r.status})")
            return True
    except urllib.error.HTTPError as e:
        print(f"cloud_push: HTTP {e.code}: {e.read().decode(errors='replace')[:200]}",
              file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"cloud_push: network error: {e.reason}", file=sys.stderr)
    return False


def run_loop() -> int:
    print(f"cloud_push: watching {status.STATUS_JSON} every {INTERVAL_S}s "
          f"-> {WORKER_URL or '(unset)'}")
    last_mtime = None
    # Re-push a quiet file occasionally so the phone can distinguish "nothing
    # changed" from "the Mac stopped reporting" via received_at.
    heartbeat_every = max(1, 600 // max(1, INTERVAL_S))
    ticks_since_push = 0
    while True:
        try:
            mtime = status.STATUS_JSON.stat().st_mtime
            ticks_since_push += 1
            if mtime != last_mtime or ticks_since_push >= heartbeat_every:
                if push_once():
                    last_mtime = mtime
                    ticks_since_push = 0
        except OSError as e:
            print(f"cloud_push: stat failed: {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"cloud_push: unexpected error: {e}", file=sys.stderr)
        time.sleep(INTERVAL_S)


def main() -> int:
    if "--loop" in sys.argv:
        return run_loop()
    return 0 if push_once() else 1


if __name__ == "__main__":
    raise SystemExit(main())
