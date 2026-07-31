"""Legacy window readers for snapshots written before provider adapters.

Delete this file once every account's snapshots within the history scan
window are declared-shaped (their raw JSON contains ``windows``).
"""
from __future__ import annotations
import datetime, json, re


def _pct(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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


def _parse_iso_ts(s) -> float | None:
    if not s:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def _win(kind, label, used, reset_epoch, *, severity=None, is_active=None,
         source="api", as_of=None):
    if used is None:
        return None
    try:
        used = float(used)
    except (TypeError, ValueError):
        return None
    try:
        reset_epoch = float(reset_epoch) if reset_epoch is not None else None
    except (TypeError, ValueError):
        reset_epoch = None
    return {"kind": kind, "label": label, "used_pct": round(used, 2),
            "reset_at_epoch": reset_epoch, "severity": severity or "normal",
            "is_active": is_active, "source": source, "as_of_epoch": as_of}


def _raw(snap) -> dict:
    try:
        raw = json.loads(snap.get("raw_json") or "{}")
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def normalize(provider, snap) -> list[dict]:
    """Normalize old provider-column snapshots for the live status view."""
    out = []
    rj = _raw(snap)
    src = snap.get("source") or "api"
    as_of = float(snap["ts"]) if snap.get("ts") else None

    def add(w):
        if w:
            out.append(w)

    if provider in ("codex", "claude"):
        sev_active = {}
        if provider == "claude":
            for lim in (rj.get("usage_api") or {}).get("limits") or []:
                if isinstance(lim, dict):
                    sev_active[lim.get("kind")] = (lim.get("severity"),
                                                   lim.get("is_active"))
        s5, a5 = sev_active.get("session", (None, None))
        sw, aw = sev_active.get("weekly_all", (None, None))
        add(_win(_kind_from_window_s(snap.get("primary_window_s"), "5h"), None,
                 snap.get("primary_used_pct"), snap.get("primary_reset_at"),
                 severity=s5, is_active=a5, source=src, as_of=as_of))
        add(_win(_kind_from_window_s(snap.get("secondary_window_s"), "weekly"), None,
                 snap.get("secondary_used_pct"), snap.get("secondary_reset_at"),
                 severity=sw, is_active=aw, source=src, as_of=as_of))
        fable = rj.get("fable") or {}
        if fable.get("used_pct") is not None:
            add(_win("model_weekly", fable.get("label"), fable["used_pct"],
                     fable.get("reset_at"), severity=fable.get("status"),
                     source=src, as_of=as_of))
    elif provider == "xai":
        reset = _parse_iso_ts(snap.get("monthly_period_end"))
        add(_win("monthly", "credits", snap.get("monthly_used_pct"), reset,
                 source=src, as_of=as_of))
        if snap.get("secondary_window_s") == 86400:
            add(_win("daily", None, snap.get("secondary_used_pct"),
                     snap.get("secondary_reset_at"), source=src, as_of=as_of))
    elif provider == "copilot":
        add(_win("monthly", "premium", snap.get("primary_used_pct"),
                 snap.get("primary_reset_at"), source=src, as_of=as_of))
        add(_win("monthly", "chat", snap.get("secondary_used_pct"),
                 snap.get("primary_reset_at"), source=src, as_of=as_of))
    elif provider == "devin":
        daily_rem = _pct(snap.get("daily_quota_remaining_percent"))
        if daily_rem is not None:
            add(_win("daily", None, 100.0 - daily_rem,
                     snap.get("primary_reset_at"), source=src, as_of=as_of))
        weekly_rem = _pct(snap.get("weekly_quota_remaining_percent"))
        if weekly_rem is not None:
            add(_win("weekly", None, 100.0 - weekly_rem,
                     snap.get("secondary_reset_at"), source=src, as_of=as_of))
    elif provider == "antigravity":
        label = None
        rem = snap.get("rate_limit_remaining") or ""
        m = re.search(r"\(([^)]+)\)", rem)
        if m:
            label = m.group(1)
        add(_win("model_weekly", label, snap.get("primary_used_pct"),
                 snap.get("primary_reset_at"), source=src, as_of=as_of))
        for w in (rj.get("extra") or {}).get("usage_windows") or []:
            if not isinstance(w, dict):
                continue
            rem_pct = _pct(w.get("remaining_pct"))
            if rem_pct is None:
                continue
            kind = "weekly" if w.get("window") == "weekly" else "5h"
            add(_win(kind, w.get("group"),
                     max(0.0, min(100.0, 100.0 - rem_pct)),
                     w.get("reset_at"), source=src, as_of=as_of))
    return out


def _fable(snap) -> dict | None:
    """Claude's model-scoped weekly window from raw_json (best-effort)."""
    rj = _raw(snap)
    f = rj.get("fable")
    if isinstance(f, dict) and f.get("used_pct") is not None and f.get("reset_at"):
        return f
    return None


def _agy_usage_windows(snap) -> list[dict]:
    """Antigravity per-group 5h/weekly windows from raw_json extra."""
    rj = _raw(snap)
    extra = rj.get("extra")
    ws = extra.get("usage_windows") if isinstance(extra, dict) else None
    out = []
    for w in ws or []:
        if not isinstance(w, dict):
            continue
        rem = _pct(w.get("remaining_pct"))
        if rem is None or not w.get("reset_at"):
            continue
        window = "weekly" if w.get("window") == "weekly" else "5h"
        group = w.get("group") or "other"
        out.append({"kind": f"{window}_{group}",
                    "used_pct": max(0.0, min(100.0, 100.0 - rem)),
                    "reset_at": w["reset_at"],
                    "window_s": 604800 if window == "weekly" else 18000})
    return out


def timed(provider, snap) -> list[dict]:
    """Old snapshot windows that carry a reset timestamp."""
    out: list[dict] = []

    def add(kind, used, reset_at, window_s, start=None):
        if used is None or not reset_at:
            return
        try:
            used_pct, reset_ts = float(used), float(reset_at)
        except (TypeError, ValueError):
            return
        out.append({"kind": kind, "used_pct": used_pct, "reset_at": reset_ts,
                    "window_s": window_s, "start": start})

    if provider in ("codex", "claude", "antigravity"):
        add(_kind_from_window_s(snap.get("primary_window_s"), "5h"),
            snap.get("primary_used_pct"), snap.get("primary_reset_at"),
            snap.get("primary_window_s"))
        add(_kind_from_window_s(snap.get("secondary_window_s"), "weekly"),
            snap.get("secondary_used_pct"), snap.get("secondary_reset_at"),
            snap.get("secondary_window_s"))
        if provider == "claude":
            f = _fable(snap)
            if f:
                add("weekly_fable", f.get("used_pct"), f.get("reset_at"), 604800)
        if provider == "antigravity":
            for w in _agy_usage_windows(snap):
                add(w["kind"], w["used_pct"], w["reset_at"], w["window_s"])
    elif provider == "copilot":
        add("monthly_premium", snap.get("primary_used_pct"), snap.get("primary_reset_at"), None)
    elif provider == "xai":
        add("monthly", snap.get("monthly_used_pct"),
            _parse_iso_ts(snap.get("monthly_period_end")), None,
            start=_parse_iso_ts(snap.get("monthly_period_start")))
    return out


def drop(provider, snap) -> list[dict]:
    """Old snapshot windows without a reset timestamp."""
    out: list[dict] = []
    if provider == "copilot":
        used = _pct(snap.get("secondary_used_pct"))
        if used is not None:
            out.append({"kind": "monthly_chat", "used_pct": used,
                        "boundary": snap.get("primary_reset_at")})
    elif provider == "devin":
        daily_rem = _pct(snap.get("daily_quota_remaining_percent"))
        if daily_rem is not None:
            out.append({"kind": "daily",
                        "used_pct": 100.0 - daily_rem,
                        "boundary": "midnight"})
        weekly_rem = _pct(snap.get("weekly_quota_remaining_percent"))
        if weekly_rem is not None:
            out.append({"kind": "weekly",
                        "used_pct": 100.0 - weekly_rem,
                        "boundary": snap.get("plan_reset_unix")})
    return out
