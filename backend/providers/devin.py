"""Devin daily and weekly quota usage.

Devin exposes quota through the Connect-RPC protobuf endpoint used by its
client. API keys are validated separately against the public user endpoint.
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request

import oauth
import store
from . import util

PROVIDER = "devin"
AUTH = util.AUTH_API_KEY
CAPS = frozenset()

USAGE_URL = (
    "https://server.codeium.com/"
    "exa.seat_management_pb.SeatManagementService/GetUserStatus"
)


def LOGIN(api_key: str) -> dict:
    """Devin uses API keys, not OAuth. Get key from app.devin.ai dashboard."""
    # Validate the key by fetching org info
    st, resp = oauth.http_get(
        "https://api.devin.ai/v1/user",
        {"Authorization": f"Bearer {api_key}", "User-Agent": oauth.UA},
    )[:2]
    if st != 200:
        raise RuntimeError(
            f"Devin API key validation failed: HTTP {st}: {str(resp)[:120]}"
        )
    email = ""
    org_id = ""
    if isinstance(resp, dict):
        email = resp.get("email", "")
        org_id = str(resp.get("organization_id", resp.get("org_id", "")))
    return {
        "access_token": api_key,
        "refresh_token": None,
        "id_token": "",
        "expires_at": 0,  # API keys don't expire
        "account_id": org_id,
        "email": email or "devin-user",
        "plan": "",
        "raw": {
            "api_key": api_key,
            "user_info": resp if isinstance(resp, dict) else {},
        },
    }


def PLAN_LABEL(plan, item) -> tuple:
    p = (plan or "").strip()
    labels = {"core": ("Core", "$20/mo"), "team": ("Team", "$500/mo")}
    return labels.get(p.lower(), (p or None, None))


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
        "credit_balance": extra.get("credit_balance"),
        "plan_start": (
            ts_fmt(extra.get("plan_start_unix"))
            if extra.get("plan_start_unix")
            else None
        ),
        "plan_reset": (
            ts_fmt(extra.get("plan_reset_unix"))
            if extra.get("plan_reset_unix")
            else None
        ),
    }
    return {key: value for key, value in out.items() if value is not None}


def to_snapshot(body: bytes) -> dict:
    """Map a GetUserStatus protobuf response to a snapshot (pure)."""
    parsed = _devin_parse_response(body)
    daily_pct = parsed.get("daily_quota_remaining_percent")
    weekly_pct = parsed.get("weekly_quota_remaining_percent")
    daily_reset = parsed.get("daily_quota_reset_at_unix")
    weekly_reset = parsed.get("weekly_quota_reset_at_unix")
    plan_reset = parsed.get("plan_reset_unix")

    windows = []
    if daily_pct is not None:
        windows.append(
            util.window(
                "daily",
                remaining_pct=daily_pct,
                reset_at=float(daily_reset) if daily_reset else None,
                window_s=86400,
                boundary="midnight",
            )
        )
    if weekly_pct is not None:
        windows.append(
            util.window(
                "weekly",
                remaining_pct=weekly_pct,
                reset_at=float(weekly_reset) if weekly_reset else None,
                window_s=604800,
                boundary=plan_reset,
            )
        )

    extra = {}
    if parsed.get("credit_balance_micros") is not None:
        extra["credit_balance"] = parsed["credit_balance_micros"] / 1_000_000
    if parsed.get("plan_start_unix"):
        extra["plan_start_unix"] = parsed["plan_start_unix"]
    if plan_reset:
        extra["plan_reset_unix"] = plan_reset
    return util.snapshot(windows, plan=parsed.get("plan"), raw={"extra": extra})


def poll(conn, account, token):
    # Devin exposes quota via a Connect-RPC protobuf endpoint:
    #   POST /exa.seat_management_pb.SeatManagementService/GetUserStatus
    #   Content-Type: application/proto
    #   Authorization: Basic <session_token>
    # The response protobuf contains (in field 1.13):
    #   .14 = daily_quota_remaining_percent (0-100)
    #   .15 = weekly_quota_remaining_percent (0-100)
    #   .16 = credit balance (micros)
    #   .17 = daily_quota_reset_at_unix
    #   .18 = weekly_quota_reset_at_unix
    #   .2.1 = plan_start_unix
    #   .3.1 = plan_reset_unix (billing cycle end)
    # Field 2 = plan_info with .2 = plan name (e.g. "Pro")
    at = token["access_token"]

    # Build the protobuf request body
    body = _devin_build_request(at)

    req = urllib.request.Request(USAGE_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/proto")
    req.add_header("Connect-Protocol-Version", "1")
    req.add_header("Authorization", f"Basic {at}")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
            snap = to_snapshot(raw)
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:120]
        snap = {
            "status": "error",
            "status_message": f"GetUserStatus HTTP {e.code}: {msg}",
        }
    except urllib.error.URLError as e:
        snap = {"status": "error", "status_message": str(e.reason)}
    store.save_snapshot(conn, account["id"], snap)
    store.log_event(
        conn,
        account["id"],
        "limit_poll",
        snap["status"] == "active",
        snap.get("status_message", ""),
    )


def _devin_encode_varint(val):
    result = b""
    while val > 0x7f:
        result += bytes([0x80 | (val & 0x7f)])
        val >>= 7
    result += bytes([val & 0x7f])
    return result


def _devin_encode_str(field_num, s):
    data = s.encode("utf-8") if isinstance(s, str) else s
    return (
        _devin_encode_varint((field_num << 3) | 2)
        + _devin_encode_varint(len(data))
        + data
    )


# Client identity constants sent in the GetUserStatus protobuf request.
DEVIN_CLIENT_NAME = "chisel"
DEVIN_CLIENT_VERSION = "2026.8.18"
DEVIN_CLIENT_PLATFORM = "mac"
DEVIN_CLIENT_LOCALE = "en"
DEVIN_CLIENT_FINGERPRINT = "080d03eeaa0cd7a10d0e0c84c26cb9a1c533e2675c14a85c3a971248f6521a710e4c02372539fc56c8b6a0454553533dc7f9e54fa3c16a2b141c87d0fb43a8b6a7e32b15a2267290298a6c6382e7b0096e06b41012d46d998f947b53a35b84c55ab589c683c6a3727aa5bf90c18e349fba8ac069b4121f5298fbacca590c903f169850ec072da539ed40d46f212aea973c725221098fcea6fb6fde32a7ef324003cb070e8a603c8c7a1d6743cfadd9e86f53797b32bb88b11abe8bcc98ec38473496bd9aaf482c6ab2c5def224bb7f554687cd78202159112e1cdee29b1c44b38cd407629d59c9dc0e2eab891ccacca859f358d7641acedc7fed0ba64a4d3e3a4827ac433bae69f7e48917ff2a6df24e2adf4fb9ed88ed8266228b99604a7cba3356fc28cb304de708958d188143f12eff3d52178a680c86073b21bc1efbf45a44b09887b60e9fe13ae9e5256e640b7159a595dcd5ecb2b470a290cf30357403e4a820dfb0ce990517e2cd64"


def _devin_build_request(at):
    """Build the GetUserStatusRequest protobuf."""
    inner = (
        _devin_encode_str(1, DEVIN_CLIENT_NAME)
        + _devin_encode_str(2, DEVIN_CLIENT_VERSION)
        + _devin_encode_str(3, at)
        + _devin_encode_str(4, DEVIN_CLIENT_LOCALE)
        + _devin_encode_str(5, DEVIN_CLIENT_PLATFORM)
        + _devin_encode_str(7, DEVIN_CLIENT_VERSION)
        + _devin_encode_str(12, DEVIN_CLIENT_NAME)
        + _devin_encode_str(31, DEVIN_CLIENT_FINGERPRINT)
    )
    return (
        _devin_encode_varint((1 << 3) | 2)
        + _devin_encode_varint(len(inner))
        + inner
    )


def _devin_parse_field(data, pos):
    """Parse one protobuf field. Returns (field_num, wire_type, value, new_pos)."""
    key = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        key |= (b & 0x7f) << shift
        shift += 7
        if not (b & 0x80):
            break
    field_num = key >> 3
    wire_type = key & 0x7
    if wire_type == 0:
        val = 0
        shift = 0
        while pos < len(data):
            b = data[pos]
            pos += 1
            val |= (b & 0x7f) << shift
            shift += 7
            if not (b & 0x80):
                break
        return field_num, "varint", val, pos
    elif wire_type == 2:
        length = 0
        shift = 0
        while pos < len(data):
            b = data[pos]
            pos += 1
            length |= (b & 0x7f) << shift
            shift += 7
            if not (b & 0x80):
                break
        val = data[pos : pos + length]
        pos += length
        return field_num, "bytes", val, pos
    elif wire_type == 5:
        val = data[pos : pos + 4]
        pos += 4
        return field_num, "32bit", val, pos
    elif wire_type == 1:
        val = data[pos : pos + 8]
        pos += 8
        return field_num, "64bit", val, pos
    return None, None, None, pos


def _devin_parse_response(raw):
    """Parse the GetUserStatusResponse protobuf."""
    parsed = {}
    # Top level: field 1 = user_status, field 2 = plan_info
    pos = 0
    user_status = None
    plan_info = None
    while pos < len(raw):
        fn, wt, val, pos = _devin_parse_field(raw, pos)
        if fn is None:
            break
        if fn == 1:
            user_status = val
        elif fn == 2:
            plan_info = val

    # Parse plan_info (field 2) for plan name
    if plan_info:
        sub_pos = 0
        while sub_pos < len(plan_info):
            sfn, swt, sval, sub_pos = _devin_parse_field(plan_info, sub_pos)
            if sfn is None:
                break
            if sfn == 2 and swt == "bytes":
                try:
                    parsed["plan"] = sval.decode("utf-8")
                except Exception as e:
                    print(f"  devin: plan name decode failed: {e}")

    # Parse user_status (field 1) for quota info in field 13
    if user_status:
        sub_pos = 0
        while sub_pos < len(user_status):
            sfn, swt, sval, sub_pos = _devin_parse_field(user_status, sub_pos)
            if sfn is None:
                break
            if sfn == 13 and swt == "bytes":
                # Field 1.13 = quota section
                quota = _devin_parse_quota(sval)
                parsed.update(quota)
            if sfn == 7 and swt == "bytes":
                try:
                    parsed["email"] = sval.decode("utf-8")
                except Exception as e:
                    print(f"  devin: email decode failed: {e}")
            if sfn == 3 and swt == "bytes":
                try:
                    parsed["name"] = sval.decode("utf-8")
                except Exception as e:
                    print(f"  devin: name decode failed: {e}")
    return parsed


def _devin_parse_quota(data):
    """Parse field 1.13 (quota section) of GetUserStatusResponse."""
    result = {}
    pos = 0
    while pos < len(data):
        fn, wt, val, pos = _devin_parse_field(data, pos)
        if fn is None:
            break
        if wt == "varint":
            if fn == 14:
                result["daily_quota_remaining_percent"] = val
            elif fn == 15:
                result["weekly_quota_remaining_percent"] = val
            elif fn == 16:
                result["credit_balance_micros"] = val
            elif fn == 17:
                result["daily_quota_reset_at_unix"] = val
            elif fn == 18:
                result["weekly_quota_reset_at_unix"] = val
        elif wt == "bytes" and fn in [2, 3]:
            # Nested message with field 1 = timestamp
            inner_pos = 0
            while inner_pos < len(val):
                ifn, iwt, ival, inner_pos = _devin_parse_field(val, inner_pos)
                if ifn is None:
                    break
                if ifn == 1 and iwt == "varint":
                    if fn == 2:
                        result["plan_start_unix"] = ival
                    elif fn == 3:
                        result["plan_reset_unix"] = ival
    return result
