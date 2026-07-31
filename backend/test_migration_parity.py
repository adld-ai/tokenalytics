"""Golden parity for the legacy-to-adapter provider migration.

For each legacy provider, freeze both the normalized status windows and the
history keys produced from a representative column snapshot. Provider
adapters replace ``adapter_snapshot()`` as they migrate in Phase 5.

Regenerate goldens only before a provider migration starts::

    GOLDEN_UPDATE=1 python3 -m pytest backend/test_migration_parity.py -q
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="tsb-test-")
os.environ["AGENT_POOL_DB"] = os.path.join(_TMP, "pool.db")
os.environ["AGENT_POOL_STATUS_JSON"] = os.path.join(_TMP, "status.json")
os.environ["AGENT_POOL_HISTORY_DIR"] = os.path.join(_TMP, "history")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import status  # noqa: E402
import window_history  # noqa: E402
from providers import copilot, devin  # noqa: E402


GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "golden")


def _strip_volatile(windows):
    """Remove fields whose value is tied to when a snapshot was captured."""
    return [
        {key: value for key, value in sorted(window.items())
         if key != "as_of_epoch"}
        for window in windows
    ]


def _history_keys(provider, snap):
    windows = (window_history.timed_windows(provider, snap)
               + window_history.drop_windows(provider, snap))
    return [window["kind"] for window in windows]


def _parity_value(provider, snap):
    return {
        "history_keys": _history_keys(provider, snap),
        "windows": _strip_volatile(status.normalize_windows(provider, snap)),
    }


def _golden_path(provider):
    return os.path.join(GOLDEN_DIR, f"{provider}.json")


def capture_golden(provider, snap):
    """Create a provider golden in update mode, otherwise verify legacy drift."""
    value = _parity_value(provider, snap)
    path = _golden_path(provider)
    if os.environ.get("GOLDEN_UPDATE"):
        os.makedirs(GOLDEN_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, sort_keys=True)
            f.write("\n")
        return value
    with open(path, encoding="utf-8") as f:
        golden = json.load(f)
    if golden != value:
        raise AssertionError(f"legacy parity fixture drifted for {provider}")
    return golden


def assert_parity(provider, adapter_snapshot):
    """Assert an adapter snapshot has the provider's frozen public shape."""
    with open(_golden_path(provider), encoding="utf-8") as f:
        golden = json.load(f)
    actual = _parity_value(provider, adapter_snapshot)
    if golden != actual:
        raise AssertionError(
            f"adapter parity failed for {provider}:\n"
            f"expected {golden!r}\nactual   {actual!r}"
        )


def _snap(**fields):
    snap = {"ts": 1000.0, "status": "active"}
    snap.update(fields)
    return snap


class ParityCase(unittest.TestCase):
    provider = None
    legacy_snap = None

    def adapter_snapshot(self):
        # Phase 5 overrides this with the provider's declared-window mapper.
        return self.legacy_snap

    def _golden(self):
        if self.provider is None:
            self.skipTest("base parity case")
        return capture_golden(self.provider, self.legacy_snap)

    def test_windows_parity(self):
        golden = self._golden()
        actual = _parity_value(self.provider, self.adapter_snapshot())
        self.assertEqual(golden["windows"], actual["windows"])

    def test_history_keys_parity(self):
        golden = self._golden()
        actual = _parity_value(self.provider, self.adapter_snapshot())
        self.assertEqual(golden["history_keys"], actual["history_keys"])


class CodexParityTest(ParityCase):
    provider = "codex"
    legacy_snap = _snap(
        primary_used_pct=6.0,
        primary_reset_at=2000.0,
        primary_window_s=604800,
    )


class ClaudeParityTest(ParityCase):
    provider = "claude"
    legacy_snap = _snap(
        primary_used_pct=41.0,
        primary_reset_at=2000.0,
        primary_window_s=18000,
        secondary_used_pct=5.0,
        secondary_reset_at=3000.0,
        secondary_window_s=604800,
        raw_json=json.dumps({
            "usage_api": {"limits": [
                {"kind": "session", "percent": 41, "severity": "normal",
                 "is_active": True},
                {"kind": "weekly_all", "percent": 5, "severity": "normal",
                 "is_active": False},
            ]},
            "fable": {"label": "Fable", "used_pct": 9.0,
                      "reset_at": 3000.0, "status": "normal"},
        }),
    )


class XaiParityTest(ParityCase):
    provider = "xai"
    legacy_snap = _snap(
        monthly_used_pct=3.17,
        monthly_period_end="2026-08-01T00:00:00+00:00",
        secondary_used_pct=0.0,
        secondary_window_s=86400,
    )


class CopilotParityTest(ParityCase):
    provider = "copilot"
    legacy_snap = _snap(primary_used_pct=12.1, primary_reset_at=2000.0)

    def adapter_snapshot(self):
        return copilot.to_snapshot({
            "copilot_plan": "individual_pro",
            "quota_reset_date": "1970-01-01T00:33:20+00:00",
            "quota_snapshots": {
                "premium_interactions": {
                    "percent_remaining": 87.9,
                    "unlimited": False,
                },
            },
        })


class DevinParityTest(ParityCase):
    provider = "devin"
    legacy_snap = _snap(
        daily_quota_remaining_percent=90.0,
        weekly_quota_remaining_percent=80.0,
        primary_reset_at=2000.0,
        secondary_reset_at=3000.0,
    )

    def adapter_snapshot(self):
        def field(field_num, value):
            return (devin._devin_encode_varint(field_num << 3)
                    + devin._devin_encode_varint(value))

        def message(field_num, value):
            return (devin._devin_encode_varint((field_num << 3) | 2)
                    + devin._devin_encode_varint(len(value)) + value)

        quota = (field(14, 90) + field(15, 80)
                 + field(17, 2000) + field(18, 3000))
        user_status = message(13, quota)
        return devin.to_snapshot(message(1, user_status))


class AntigravityParityTest(ParityCase):
    provider = "antigravity"
    legacy_snap = _snap(
        primary_used_pct=0.0,
        rate_limit_remaining="100% left (Gemini 3 Pro)",
        raw_json=json.dumps({"extra": {"usage_windows": [
            {"group": "gemini", "window": "5h", "remaining_pct": 100.0,
             "reset_at": None},
            {"group": "gemini", "window": "weekly", "remaining_pct": 92.0,
             "reset_at": 4000.0},
        ]}}),
    )


if __name__ == "__main__":
    unittest.main()
