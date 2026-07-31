"""Tests for the Kimi Code and Kiro adapters.

Both map a vendor payload to windows, and both have to survive the specific
shapes those vendors actually send: Kimi omits zero-valued keys and quotes
its numbers, Kiro sends epoch seconds as an exponent-notation float and
nulls fields the docs imply are always present.
"""
from __future__ import annotations
import json, os, sys, tempfile, unittest

_TMP = tempfile.mkdtemp(prefix="tsb-test-")
os.environ["AGENT_POOL_DB"] = os.path.join(_TMP, "pool.db")
os.environ["AGENT_POOL_STATUS_JSON"] = os.path.join(_TMP, "status.json")
os.environ["AGENT_POOL_HISTORY_DIR"] = os.path.join(_TMP, "history")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import status  # noqa: E402
from providers import kimi, kiro, util  # noqa: E402


def windows_of(snap):
    return json.loads(snap["raw_json"])["windows"]


# A verbatim-shaped /usages response: counts are strings, and `used` is
# absent from limits[0].detail because it was zero.
KIMI_BODY = {
    "user": {"userId": "u1", "region": "REGION_OVERSEA",
             "membership": {"level": "LEVEL_ADVANCED"}},
    "usage": {"limit": "100", "used": "2", "remaining": "98",
              "resetTime": "2026-08-01T14:15:19.873708Z"},
    "limits": [{"window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
                "detail": {"limit": "100", "remaining": "100",
                           "resetTime": "2026-07-30T21:15:19.873708Z"}}],
    "parallel": {"limit": "30"},
    "subType": "TYPE_PURCHASE",
}


class KimiSnapshotTest(unittest.TestCase):
    def test_weekly_and_five_hour_windows(self):
        snap = kimi.to_snapshot(KIMI_BODY)
        w = windows_of(snap)
        self.assertEqual([x["kind"] for x in w], ["weekly", "5h"])
        self.assertEqual(w[0]["used_pct"], 2.0)
        self.assertEqual(w[0]["window_s"], 604800)
        self.assertEqual(w[1]["window_s"], 18000)

    def test_absent_used_key_is_derived_from_remaining(self):
        """proto3 omits zero, so limits[0].detail has no `used` at all."""
        self.assertEqual(windows_of(kimi.to_snapshot(KIMI_BODY))[1]["used_pct"], 0.0)

    def test_string_counts_are_cast(self):
        body = {"usage": {"limit": "200", "used": "50"}}
        self.assertEqual(windows_of(kimi.to_snapshot(body))[0]["used_pct"], 25.0)

    def test_plan_and_raw_metadata(self):
        snap = kimi.to_snapshot(KIMI_BODY)
        self.assertEqual(snap["plan"], "LEVEL_ADVANCED")
        rj = json.loads(snap["raw_json"])
        self.assertEqual(rj["parallel_limit"], "30")
        self.assertEqual(rj["region"], "REGION_OVERSEA")

    def test_reset_times_survive_into_normalized_windows(self):
        snap = kimi.to_snapshot(KIMI_BODY)
        snap.update(ts=1000.0)
        w = status.normalize_windows("kimi", snap)
        self.assertEqual(len(w), 2)
        self.assertTrue(all(x["reset_at_epoch"] for x in w))

    def test_zero_limit_never_divides(self):
        self.assertEqual(windows_of(kimi.to_snapshot({"usage": {"limit": "0"}})), [])

    def test_empty_body_declares_no_windows(self):
        snap = kimi.to_snapshot({})
        self.assertEqual(windows_of(snap), [])
        self.assertEqual(snap["status"], "active")

    def test_malformed_limits_entries_are_skipped(self):
        body = {"limits": ["x", {"detail": {}}, {"detail": {"limit": "10", "used": "5"}}]}
        w = windows_of(kimi.to_snapshot(body))
        self.assertEqual([x["used_pct"] for x in w], [50.0])

    def test_unknown_time_unit_leaves_window_s_unset(self):
        body = {"limits": [{"window": {"duration": 5, "timeUnit": "TIME_UNIT_FORTNIGHT"},
                            "detail": {"limit": "10", "used": "1"}}]}
        w = windows_of(kimi.to_snapshot(body))
        self.assertNotIn("window_s", w[0])
        self.assertNotIn("kind", w[0])


# Verbatim-shaped getUsageLimits response, including the nulls the live API
# actually returns.
KIRO_BODY = {
    "daysUntilReset": None,
    "limits": None,
    "nextDateReset": 1785542400.0,
    "overageConfiguration": {"overageStatus": "DISABLED"},
    "subscriptionInfo": {"subscriptionTitle": "KIRO POWER",
                         "type": "Q_DEVELOPER_STANDALONE_POWER"},
    "usageBreakdownList": [{
        "displayName": "Credit", "resourceType": "CREDIT", "unit": "INVOCATIONS",
        "currentUsage": 2500, "currentUsageWithPrecision": 2500.0,
        "usageLimit": 10000, "usageLimitWithPrecision": 10000.0,
        "nextDateReset": 1785542400.0,
    }],
    "userInfo": {"email": None, "userId": "d-9067c98495"},
}


class KiroSnapshotTest(unittest.TestCase):
    def test_credit_window(self):
        w = windows_of(kiro.to_snapshot(KIRO_BODY))
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["kind"], "monthly")
        self.assertEqual(w[0]["used_pct"], 25.0)
        self.assertEqual(w[0]["label"], "credit")
        self.assertEqual(w[0]["reset_at"], 1785542400.0)

    def test_plan_title(self):
        self.assertEqual(kiro.to_snapshot(KIRO_BODY)["plan"], "KIRO POWER")

    def test_null_limits_and_days_are_ignored(self):
        """The live API sends both as null; neither may reach a window."""
        snap = kiro.to_snapshot(KIRO_BODY)
        self.assertEqual(len(windows_of(snap)), 1)

    def test_falls_back_to_top_level_reset(self):
        body = dict(KIRO_BODY)
        body["usageBreakdownList"] = [dict(KIRO_BODY["usageBreakdownList"][0])]
        del body["usageBreakdownList"][0]["nextDateReset"]
        self.assertEqual(windows_of(kiro.to_snapshot(body))[0]["reset_at"], 1785542400.0)

    def test_precision_fields_win_over_integers(self):
        body = dict(KIRO_BODY)
        body["usageBreakdownList"] = [{"currentUsage": 1, "usageLimit": 1,
                                       "currentUsageWithPrecision": 1.0,
                                       "usageLimitWithPrecision": 4.0}]
        self.assertEqual(windows_of(kiro.to_snapshot(body))[0]["used_pct"], 25.0)

    def test_integer_fields_used_when_precision_absent(self):
        body = {"usageBreakdownList": [{"currentUsage": 3, "usageLimit": 4}]}
        self.assertEqual(windows_of(kiro.to_snapshot(body))[0]["used_pct"], 75.0)

    def test_zero_limit_never_divides(self):
        body = {"usageBreakdownList": [{"currentUsage": 0, "usageLimit": 0}]}
        self.assertEqual(windows_of(kiro.to_snapshot(body)), [])

    def test_empty_body_declares_no_windows(self):
        self.assertEqual(windows_of(kiro.to_snapshot({})), [])

    def test_exponent_float_reset_normalizes(self):
        snap = kiro.to_snapshot(KIRO_BODY)
        snap.update(ts=1000.0)
        w = status.normalize_windows("kiro", snap)
        self.assertEqual(w[0]["reset_at_epoch"], 1785542400.0)


class AdapterRegistrationTest(unittest.TestCase):
    def test_both_are_discovered_as_tokenless_adapters(self):
        import providers
        providers.reset_cache()
        try:
            self.assertIn("kimi", providers.names())
            self.assertIn("kiro", providers.names())
            self.assertFalse(providers.requires_token("kimi"))
            self.assertFalse(providers.requires_token("kiro"))
            self.assertEqual(providers.errors(), {})
        finally:
            providers.reset_cache()


if __name__ == "__main__":
    unittest.main()
