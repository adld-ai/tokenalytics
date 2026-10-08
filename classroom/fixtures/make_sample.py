#!/usr/bin/env python3
"""Emit a 30-account status.json sample using the key names backend/status.py writes.
Imports nothing from backend/. Deterministic (seeded)."""
import json, random, sys, time
random.seed(7)
NOW = int(time.time())
PROV = ["codex", "claude", "copilot", "xai", "antigravity", "devin"]
PLANS = {"codex": ["Plus", "Pro"], "claude": ["Pro", "Max 5x", "Max 20x"], "copilot": ["Pro"],
         "xai": ["SuperGrok"], "antigravity": ["Standard"], "devin": ["Core"]}
KINDS = {"codex": [("session", "5h"), ("weekly", "Weekly")], "claude": [("session", "5h"), ("weekly", "Weekly")],
         "copilot": [("monthly", "Premium requests")], "xai": [("daily", "Daily")],
         "antigravity": [("daily", "Model quota")], "devin": [("weekly", "ACUs")]}
def win(kind, label, used, reset_in, sev="normal", stale=False, proj=None):
    w = {"kind": kind, "label": label, "used_pct": round(used, 2), "reset_at_epoch": NOW + reset_in,
         "severity": sev, "is_active": True, "source": "api", "as_of_epoch": NOW - (900 if stale else 20),
         "phase": "live", "used_pct_effective": round(used, 2), "stale": stale}
    if proj: w["projected_exhaust_epoch"] = NOW + proj
    return w
accts = []
for i in range(30):
    p = PROV[i % 6]
    used = random.uniform(5, 97)
    sev = "exhausted" if i == 4 else ("warning" if used > 80 else "normal")
    if i == 4: used = 100.0
    stale = i in (9, 17, 25)
    proj = 540 if i == 11 else (1800 if i == 22 else None)
    ws = []
    for k, (kind, label) in enumerate(KINDS[p]):
        u = used if k == 0 else max(0, used - random.uniform(10, 40))
        ws.append(win(kind, label, u, random.randint(600, 4 * 3600) if kind == "session" else random.randint(3600, 5 * 86400),
                      sev if k == 0 else "normal", stale, proj if k == 0 else None))
    quota = "exhausted" if sev == "exhausted" else ("warning" if sev == "warning" else "ok")
    accts.append({
        "id": i + 1, "provider": p, "email": f"trainee{i+1:02d}@example.co.kr", "label": f"seat-{i+1:02d}",
        "account_id": f"acc_{i+1:04d}", "plan": random.choice(PLANS[p]), "status": "active", "status_message": "",
        "token_expires": None, "token_expired": False, "primary_used_pct": round(used, 2), "primary_reset": None,
        "secondary_used_pct": None, "secondary_reset": None, "rate_limit_remaining": None, "rate_limit_reset": None,
        "rate_limit_limit": None, "sku": None, "limited_user_quotas": None, "limited_user_reset_date": None,
        "daily_quota_remaining_percent": None, "weekly_quota_remaining_percent": None, "plan_reset": None,
        "monthly_used": None, "monthly_limit": None, "monthly_used_pct": None, "monthly_period_start": None,
        "monthly_period_end": None, "reset_credits": [], "last_poll": "now", "last_poll_epoch": float(NOW - 20),
        "tier_override": None, "capabilities": [], "plan_price": None, "windows": ws,
        "state": {"auth": "ok", "subscription": "paid", "sub_renews_at": None, "sub_expires_at": None,
                  "quota": quota, "usable": quota != "exhausted"},
    })
worst = accts[4]["windows"][0]
payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW)), "account_count": len(accts),
           "heartbeat": {"status": "ok", "next": None, "accounts": 0},
           "headline": {"account_id": 5, "provider": accts[4]["provider"], "email": accts[4]["email"], "kind": worst["kind"],
                        "label": worst["label"], "used_pct": worst["used_pct"], "reset_at_epoch": worst["reset_at_epoch"], "severity": "exhausted"},
           "accounts": accts,
           "last_swap": {"provider": "codex", "from": "seat-05", "to": "seat-06", "at_epoch": NOW - 300}}
out = sys.argv[1] if len(sys.argv) > 1 else "status.sample.json"
json.dump(payload, open(out, "w"), indent=1)
print("wrote", out, len(accts), "accounts")
