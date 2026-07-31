"""Tests for adapter-declared windows feeding window-history detection.

status.declared_windows() covers display; these cover the other consumer of a
snapshot's windows — closed-window archiving and the hot-poll scheduler, which
read window_history.timed_windows()/drop_windows().
"""
from __future__ import annotations
import json, os, sys, tempfile, unittest

_TMP = tempfile.mkdtemp(prefix="tsb-test-")
os.environ["AGENT_POOL_DB"] = os.path.join(_TMP, "pool.db")
os.environ["AGENT_POOL_STATUS_JSON"] = os.path.join(_TMP, "status.json")
os.environ["AGENT_POOL_HISTORY_DIR"] = os.path.join(_TMP, "history")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import poller  # noqa: E402
import window_history as wh  # noqa: E402


def snap(windows=None, **kw):
    base = {"ts": 1000.0, "status": "active"}
    if windows is not None:
        base["raw_json"] = json.dumps({"windows": windows})
    base.update(kw)
    return base


class DeclaredTimedWindowsTest(unittest.TestCase):
    def test_declared_window_with_reset_is_timed(self):
        s = snap([{"kind": "5h", "used_pct": 40.0, "reset_at_epoch": 5000.0}])
        w = wh.timed_windows("kimi", s)
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["kind"], "5h")
        self.assertEqual(w[0]["used_pct"], 40.0)
        self.assertEqual(w[0]["reset_at"], 5000.0)
        self.assertEqual(w[0]["window_s"], 18000)

    def test_iso_reset_is_parsed(self):
        s = snap([{"kind": "daily", "used_pct": 5.0,
                   "reset_at": "2026-01-01T00:00:00Z"}])
        self.assertEqual(wh.timed_windows("kimi", s)[0]["reset_at"], 1767225600.0)

    def test_remaining_pct_is_inverted(self):
        s = snap([{"kind": "weekly", "remaining_pct": 25.0, "reset_at": 5000.0}])
        self.assertEqual(wh.timed_windows("zai", s)[0]["used_pct"], 75.0)

    def test_label_disambiguates_same_kind_windows(self):
        s = snap([{"kind": "weekly", "used_pct": 1.0, "reset_at": 5000.0,
                   "label": "GLM-4.7"},
                  {"kind": "weekly", "used_pct": 2.0, "reset_at": 5000.0}])
        kinds = [w["kind"] for w in wh.timed_windows("zai", s)]
        self.assertEqual(kinds, ["weekly_glm_4_7", "weekly"])

    def test_explicit_window_s_wins_over_kind_default(self):
        s = snap([{"kind": "weekly", "window_s": 1209600, "used_pct": 1.0,
                   "reset_at": 5000.0}])
        self.assertEqual(wh.timed_windows("kimi", s)[0]["window_s"], 1209600)

    def test_declared_window_without_reset_is_a_drop_window(self):
        s = snap([{"kind": "daily", "used_pct": 30.0}])
        self.assertEqual(wh.timed_windows("kimi", s), [])
        d = wh.drop_windows("kimi", s)
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["kind"], "daily")
        self.assertEqual(d[0]["used_pct"], 30.0)
        self.assertIsNone(d[0]["boundary"])

    def test_drop_window_boundary_hint_passes_through(self):
        s = snap([{"kind": "monthly", "used_pct": 30.0, "boundary": 9000.0}])
        self.assertEqual(wh.drop_windows("kimi", s)[0]["boundary"], 9000.0)

    def test_declared_windows_beat_legacy_columns(self):
        s = snap([{"kind": "daily", "used_pct": 1.0, "reset_at": 5000.0}],
                 primary_used_pct=99.0, primary_reset_at=7000.0,
                 primary_window_s=18000)
        w = wh.timed_windows("codex", s)
        self.assertEqual([(x["kind"], x["used_pct"]) for x in w], [("daily", 1.0)])

    def test_absent_key_leaves_legacy_path_untouched(self):
        s = snap(primary_used_pct=6.0, primary_reset_at=2000.0,
                 primary_window_s=604800)
        w = wh.timed_windows("codex", s)
        self.assertEqual([(x["kind"], x["used_pct"]) for x in w], [("weekly", 6.0)])

    def test_declared_but_empty_returns_empty_not_legacy(self):
        s = snap([], primary_used_pct=99.0, primary_reset_at=2000.0,
                 primary_window_s=604800)
        self.assertEqual(wh.timed_windows("codex", s), [])

    def test_malformed_entries_are_skipped(self):
        s = snap(["nope", {"kind": "daily"}, {"used_pct": "abc", "reset_at": 1},
                  {"kind": "weekly", "used_pct": 3.0, "reset_at": 5000.0}])
        w = wh.timed_windows("kimi", s)
        self.assertEqual([x["kind"] for x in w], ["weekly"])


class DeclaredHotnessTest(unittest.TestCase):
    """Declared windows must drive hot polling and pre-reset wakeups too."""

    def test_max_used_pct_sees_declared_windows(self):
        s = snap([{"kind": "5h", "used_pct": 88.0, "reset_at": 5000.0},
                  {"kind": "daily", "used_pct": 12.0}])
        self.assertEqual(poller.max_used_pct("kimi", s), 88.0)

    def test_next_reset_at_sees_declared_windows(self):
        s = snap([{"kind": "5h", "used_pct": 10.0, "reset_at": 5000.0},
                  {"kind": "weekly", "used_pct": 10.0, "reset_at": 9000.0}])
        self.assertEqual(poller.next_reset_at("kimi", s, now=1000.0), 5000.0)


if __name__ == "__main__":
    unittest.main()
