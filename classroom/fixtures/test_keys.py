import json, os, unittest
HERE = os.path.dirname(__file__)
# Frozen from backend/status.py build_payload()/_win()/refresh_windows()/attach_projections()/account_state(), read 2026-10-09.
ACCOUNT_KEYS = {"id","provider","email","label","account_id","plan","status","status_message","token_expires","token_expired",
 "primary_used_pct","primary_reset","secondary_used_pct","secondary_reset","rate_limit_remaining","rate_limit_reset","rate_limit_limit",
 "sku","limited_user_quotas","limited_user_reset_date","daily_quota_remaining_percent","weekly_quota_remaining_percent","plan_reset",
 "monthly_used","monthly_limit","monthly_used_pct","monthly_period_start","monthly_period_end","reset_credits","last_poll","last_poll_epoch",
 "tier_override","capabilities","windows","state","plan_price"}
ACCOUNT_OPT = {"live","heartbeat_status","heartbeat_next","heartbeat_count"}  # conditional / provider-merged extras — the frozen set is a floor, not the full contract
WINDOW_KEYS = {"kind","label","used_pct","reset_at_epoch","severity","is_active","source","as_of_epoch","phase","used_pct_effective","stale"}
WINDOW_OPT = {"projected_exhaust_epoch"}
STATE_KEYS = {"auth","subscription","sub_renews_at","sub_expires_at","quota","usable"}
TOP = {"generated_at","account_count","heartbeat","headline","accounts"}
class T(unittest.TestCase):
    def setUp(self):
        self.d = json.load(open(os.path.join(HERE, "status.sample.json")))
    def test_top(self): self.assertTrue(TOP <= set(self.d))
    def test_accounts(self):
        self.assertEqual(len(self.d["accounts"]), 30)
        for a in self.d["accounts"]:
            self.assertTrue(ACCOUNT_KEYS <= set(a), ("missing", ACCOUNT_KEYS - set(a), a.get("id")))
            self.assertEqual(set(a["state"]), STATE_KEYS)
            for w in a["windows"]:
                self.assertTrue(WINDOW_KEYS <= set(w) <= WINDOW_KEYS | WINDOW_OPT, w)
    def test_mix(self):
        acc = self.d["accounts"]
        self.assertEqual(len({a["provider"] for a in acc}), 6)
        self.assertEqual(sum(1 for a in acc if a["windows"][0]["stale"]), 3)
        self.assertEqual(sum(1 for a in acc if "projected_exhaust_epoch" in a["windows"][0]), 2)
        self.assertEqual(sum(1 for a in acc if a["windows"][0]["severity"] == "exhausted"), 1)
if __name__ == "__main__": unittest.main()
