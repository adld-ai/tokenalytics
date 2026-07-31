"""Tests for adapter-declared windows in raw_json["windows"].

Declarative providers write their already-normalized windows into the
snapshot's raw_json instead of into dedicated limit_snapshots columns, so
adding a provider needs no schema migration and no branch in
normalize_windows().
"""
from __future__ import annotations
import json, os, sys, tempfile, unittest

_TMP = tempfile.mkdtemp(prefix="tsb-test-")
os.environ["AGENT_POOL_DB"] = os.path.join(_TMP, "pool.db")
os.environ["AGENT_POOL_STATUS_JSON"] = os.path.join(_TMP, "status.json")
os.environ["AGENT_POOL_HISTORY_DIR"] = os.path.join(_TMP, "history")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import status  # noqa: E402


def snap(windows=None, **kw):
    base = {"ts": 1000.0, "status": "active"}
    if windows is not None:
        rj = kw.pop("raw", {})
        rj["windows"] = windows
        base["raw_json"] = json.dumps(rj)
    base.update(kw)
    return base


class DeclaredWindowsTest(unittest.TestCase):
    def test_declared_windows_are_used(self):
        s = snap([{"kind": "5h", "used_pct": 42.0, "reset_at_epoch": 2000.0}])
        w = status.normalize_windows("kimi", s)
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["kind"], "5h")
        self.assertEqual(w[0]["used_pct"], 42.0)
        self.assertEqual(w[0]["reset_at_epoch"], 2000.0)
        self.assertEqual(w[0]["as_of_epoch"], 1000.0)
        self.assertEqual(w[0]["source"], "api")

    def test_declared_windows_beat_legacy_columns(self):
        """An adapter that declares windows owns the whole result."""
        s = snap([{"kind": "daily", "used_pct": 10.0}],
                 primary_used_pct=99.0, primary_window_s=18000)
        w = status.normalize_windows("codex", s)
        self.assertEqual([(x["kind"], x["used_pct"]) for x in w], [("daily", 10.0)])

    def test_remaining_pct_is_inverted(self):
        s = snap([{"kind": "weekly", "remaining_pct": 30.0}])
        w = status.normalize_windows("zai", s)
        self.assertEqual(w[0]["used_pct"], 70.0)

    def test_remaining_pct_is_clamped(self):
        s = snap([{"kind": "weekly", "remaining_pct": 140.0},
                  {"kind": "daily", "remaining_pct": -20.0}])
        w = status.normalize_windows("zai", s)
        self.assertEqual([x["used_pct"] for x in w], [0.0, 100.0])

    def test_used_pct_wins_over_remaining_pct(self):
        s = snap([{"kind": "daily", "used_pct": 25.0, "remaining_pct": 30.0}])
        w = status.normalize_windows("zai", s)
        self.assertEqual(w[0]["used_pct"], 25.0)

    def test_iso_reset_is_parsed_to_epoch(self):
        s = snap([{"kind": "daily", "used_pct": 1.0,
                   "reset_at": "2026-01-01T00:00:00Z"}])
        w = status.normalize_windows("cursor", s)
        self.assertEqual(w[0]["reset_at_epoch"], 1767225600.0)

    def test_epoch_reset_at_alias_is_accepted(self):
        s = snap([{"kind": "daily", "used_pct": 1.0, "reset_at": 2500.0}])
        w = status.normalize_windows("cursor", s)
        self.assertEqual(w[0]["reset_at_epoch"], 2500.0)

    def test_unparseable_reset_becomes_none(self):
        s = snap([{"kind": "daily", "used_pct": 1.0, "reset_at": "soon"}])
        w = status.normalize_windows("cursor", s)
        self.assertIsNone(w[0]["reset_at_epoch"])

    def test_kind_is_derived_from_window_s(self):
        s = snap([{"window_s": 18000, "used_pct": 1.0},
                  {"window_s": 604800, "used_pct": 2.0}])
        w = status.normalize_windows("kimi", s)
        self.assertEqual([x["kind"] for x in w], ["5h", "weekly"])

    def test_kind_defaults_when_unknown(self):
        s = snap([{"used_pct": 1.0}])
        w = status.normalize_windows("kimi", s)
        self.assertEqual(w[0]["kind"], "session")

    def test_label_severity_and_is_active_pass_through(self):
        s = snap([{"kind": "weekly", "used_pct": 1.0, "label": "opus",
                   "severity": "warning", "is_active": True}])
        w = status.normalize_windows("kimi", s)
        self.assertEqual(w[0]["label"], "opus")
        self.assertEqual(w[0]["severity"], "warning")
        self.assertTrue(w[0]["is_active"])

    def test_per_window_source_override(self):
        s = snap([{"kind": "daily", "used_pct": 1.0, "source": "gateway"},
                  {"kind": "weekly", "used_pct": 2.0}], source="local")
        w = status.normalize_windows("kimi", s)
        self.assertEqual([x["source"] for x in w], ["gateway", "local"])

    def test_entries_without_a_percentage_are_dropped(self):
        s = snap([{"kind": "daily"}, {"kind": "weekly", "used_pct": 5.0},
                  "not-a-dict", {"kind": "5h", "used_pct": "abc"}])
        w = status.normalize_windows("kimi", s)
        self.assertEqual([x["kind"] for x in w], ["weekly"])

    def test_declared_but_empty_returns_empty_not_legacy(self):
        s = snap([], primary_used_pct=99.0, primary_window_s=18000)
        self.assertEqual(status.normalize_windows("codex", s), [])

    def test_non_list_windows_falls_back_to_legacy(self):
        s = snap(primary_used_pct=6.0, primary_reset_at=2000.0,
                 primary_window_s=604800,
                 raw_json=json.dumps({"windows": {"kind": "daily"}}))
        w = status.normalize_windows("codex", s)
        self.assertEqual([x["kind"] for x in w], ["weekly"])

    def test_absent_key_leaves_legacy_path_untouched(self):
        s = snap(primary_used_pct=6.0, primary_reset_at=2000.0,
                 primary_window_s=604800)
        w = status.normalize_windows("codex", s)
        self.assertEqual([(x["kind"], x["used_pct"]) for x in w], [("weekly", 6.0)])

    def test_error_snapshot_yields_nothing(self):
        s = snap([{"kind": "daily", "used_pct": 1.0}], status="error")
        self.assertEqual(status.normalize_windows("kimi", s), [])


if __name__ == "__main__":
    unittest.main()
