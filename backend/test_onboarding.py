#!/usr/bin/env python3
"""Verify that every newly-onboarded user gets every subscription data on
initial onboarding — not deferred to the next 5-minute poll cycle.

For each provider this asserts two things:
  1. `pool.cmd_add` / `pool.cmd_add_devin` invokes `poller.poll_account`
     immediately after saving the token (the onboarding→poll wiring).
  2. The provider's poller, fed canned HTTP responses, saves a snapshot
     containing the full set of subscription fields that provider surfaces.

Run:  python test_onboarding.py
"""
from __future__ import annotations
import datetime, json, os, sys, tempfile, time, types, unittest
import urllib.request
from pathlib import Path
from unittest import mock

# Point the store + status export at a temp DB / file BEFORE importing the
# modules that read these at import time.
_TMP = tempfile.mkdtemp(prefix="tsb-test-")
os.environ["AGENT_POOL_DB"] = str(Path(_TMP) / "pool.db")
os.environ["AGENT_POOL_STATUS_JSON"] = str(Path(_TMP) / "status.json")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import providers, store, oauth, poller, pool, status  # noqa: E402
from providers import antigravity, claude, codex, copilot, devin, util, xai  # noqa: E402


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()


# ─── fake HTTP ──────────────────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, status, body, headers):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = headers

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(req, timeout=None):
    url = req.full_url
    method = req.get_method()
    # Dispatch keyed on URL substring; each branch returns canned bytes.
    # ── codex ──
    if "wham/usage" in url:
        return _FakeResp(200, {
            "plan_type": "pro",
            "rate_limit": {
                "primary_window": {"used_percent": 42.0, "reset_after_seconds": 3600,
                                   "limit_window_seconds": 7200},
                "secondary_window": {"used_percent": 10.0, "reset_after_seconds": 86400,
                                     "limit_window_seconds": 172800},
            },
            "credits": {"balance": 12.5},
            "rate_limit_reset_credits": {"available_count": 2},
        }, {})
    if "wham/rate-limit-reset-credits" in url and "consume" not in url:
        return _FakeResp(200, {"credits": [
            {"id": "rc1", "title": "Reset", "status": "available",
             "expires_at": "2026-12-31T00:00:00Z", "granted_at": "2026-01-01T00:00:00Z",
             "description": "banked"},
        ]}, {})
    if "backend-api/accounts/check/v4-2023-04-27" in url:
        return _FakeResp(200, {"accounts": {"codex-acct-1": {
            "account": {"account_id": "codex-acct-1", "plan_type": "pro",
                        "has_previously_paid_subscription": True},
            "entitlement": {"subscription_id": "sub-1", "has_active_subscription": True,
                            "is_active_subscription_gratis": False,
                            "subscription_plan": "chatgptpro_partner_managed",
                            "renews_at": "2026-08-09T14:59:59+00:00",
                            "expires_at": "2026-08-16T14:59:59+00:00"},
        }}}, {})
    if "backend-api/accounts" in url:
        return _FakeResp(200, {"items": [
            {"id": "codex-acct-1", "created_time": "2023-06-06T14:41:24.785528Z"},
        ]}, {})
    # ── claude ──
    if "api.anthropic.com/api/oauth/usage" in url:
        five_hour_reset = _iso(time.time() + 18000)
        seven_day_reset = _iso(time.time() + 604800)
        return _FakeResp(200, {
            "five_hour": {"utilization": 7.0, "resets_at": five_hour_reset,
                          "limit_dollars": None, "used_dollars": None,
                          "remaining_dollars": None},
            "seven_day": {"utilization": 20.0, "resets_at": seven_day_reset,
                         "limit_dollars": None, "used_dollars": None,
                         "remaining_dollars": None},
            "limits": [
                {"kind": "session", "group": "session", "percent": 7,
                 "severity": "normal", "resets_at": five_hour_reset,
                 "scope": None, "is_active": True},
                {"kind": "weekly_all", "group": "weekly", "percent": 20,
                 "severity": "normal", "resets_at": seven_day_reset,
                 "scope": None, "is_active": False},
            ],
            "extra_usage": {"is_enabled": False, "monthly_limit": None,
                            "used_credits": None, "utilization": None},
        }, {})
    if "api.anthropic.com/api/oauth/profile" in url:
        return _FakeResp(200, {
            "account": {"has_claude_max": True, "display_name": "Test",
                        "full_name": "Test User", "created_at": "2024-01-01T00:00:00Z"},
            "organization": {"subscription_status": "active", "billing_type": "stripe",
                             "rate_limit_tier": "tier_2",
                             "has_extra_usage_enabled": True,
                             "subscription_created_at": "2024-01-01T00:00:00Z",
                             "organization_type": "individual",
                             "name": "Personal"},
        }, {})
    # ── xai ──
    if "cli-chat-proxy.grok.com/v1/billing" in url:
        return _FakeResp(200, {"config": {
            "used": {"val": 30}, "monthlyLimit": {"val": 100},
            "billingPeriodStart": "2026-01-01T00:00:00Z",
            "billingPeriodEnd": "2026-02-01T00:00:00Z",
            "onDemandCap": {"val": 50},
        }}, {})
    if "api.x.ai/v1/chat/completions" in url:
        return _FakeResp(200, {}, {
            "x-ratelimit-limit-requests": "100",
            "x-ratelimit-remaining-requests": "80",
            "x-ratelimit-limit-tokens": "10000",
            "x-ratelimit-remaining-tokens": "9000",
            "x-ratelimit-reset-requests": "23h59m",
        })
    # ── antigravity ──
    if "loadCodeAssist" in url:
        return _FakeResp(200, {
            "allowedTiers": [{"id": "standard-tier", "name": "Antigravity",
                              "description": "Unlimited coding assistant"}],
            "cloudaicompanionProject": "proj-123",
        }, {})
    if "fetchAvailableModels" in url:
        return _FakeResp(200, {"models": {
            "gemini-3-pro": {"displayName": "Gemini 3 Pro",
                             "quotaInfo": {"remainingFraction": 0.75,
                                           "resetTime": "2026-01-02T00:00:00Z"}},
        }}, {})
    # ── copilot ──
    if "copilot_internal/v2/token" in url:
        return _FakeResp(200, {"token": "cp-tok", "expires_at": time.time() + 7200,
                               "sku": "individual_pro",
                               "limited_user_quotas": "1000 premium requests",
                               "limited_user_reset_date": "2026-02-01"}, {})
    if "copilot_internal/user" in url:
        return _FakeResp(200, {
            "copilot_plan": "individual_pro",
            "quota_reset_date": "2026-02-01",
            "quota_snapshots": {
                "premium_interactions": {"percent_remaining": 60.0, "unlimited": False,
                                         "entitlement": "pro", "overage_count": 0},
                "chat": {"percent_remaining": 90.0, "unlimited": False},
                "completions": {"unlimited": True},
            },
            "access_type_sku": "individual_pro",
            "can_upgrade_plan": False,
            "organization_login_list": ["my-org"],
        }, {})
    if "api.github.com/user" in url:
        return _FakeResp(200, {"login": "testuser", "id": 1234,
                               "email": "test@example.com", "name": "Test User"}, {})
    # ── devin ──
    if "GetUserStatus" in url:
        # Minimal protobuf: field 2 (plan_info) with field 2 = "Pro",
        # field 1 (user_status) with field 13 (quota) containing varints 14..18.
        def _varint(v):
            out = b""
            while v > 0x7f:
                out += bytes([0x80 | (v & 0x7f)]); v >>= 7
            return out + bytes([v & 0x7f])
        def _bytes_field(fn, data):
            return _varint((fn << 3) | 2) + _varint(len(data)) + data
        def _varint_field(fn, v):
            return _varint((fn << 3) | 0) + _varint(v)
        plan_start = int(time.time()) - 30 * 86400
        plan_reset = int(time.time()) + 86400
        quota = (_bytes_field(2, _varint_field(1, plan_start))
                 + _bytes_field(3, _varint_field(1, plan_reset))
                 + _varint_field(14, 70) + _varint_field(15, 40)
                 + _varint_field(16, 5_000_000) + _varint_field(17, int(time.time()) + 86400)
                 + _varint_field(18, int(time.time()) + 604800))
        user_status = _bytes_field(7, b"test@example.com") + _bytes_field(13, quota)
        plan_info = _bytes_field(2, b"Pro")
        body = _bytes_field(1, user_status) + _bytes_field(2, plan_info)
        return _FakeResp(200, body, {})
    raise AssertionError(f"unexpected urlopen: {method} {url}")


def _fake_login(provider):
    """Return a fake OAuth result for the given provider (no browser/network)."""
    return {
        "access_token": f"fake-{provider}-access",
        "refresh_token": f"fake-{provider}-refresh",
        "id_token": "",
        "expires_at": time.time() + 3600,
        "account_id": f"{provider}-acct-1",
        "email": f"{provider}@example.com",
        "plan": "",
        "raw": {"github_token": f"fake-{provider}-gh"} if provider == "copilot" else {},
    }


# ─── tests ──────────────────────────────────────────────────────────────────
class OnboardingPollTests(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect()
        # wipe between tests
        for t in ("subscription_meta", "reset_credits", "refresh_log", "limit_snapshots", "tokens", "accounts"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()
        self._urlopen_patch = mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen)
        self._urlopen_patch.start()

    def tearDown(self):
        self._urlopen_patch.stop()
        self.conn.close()

    # Helper: run onboarding for a provider and return the saved snapshot.
    def _onboard(self, provider):
        if provider in ("antigravity", "claude", "codex", "copilot", "xai"):
            adapter = {
                "antigravity": antigravity,
                "claude": claude,
                "codex": codex,
                "copilot": copilot,
                "xai": xai,
            }[provider]
            login_patch = mock.patch.object(
                adapter, "LOGIN", side_effect=lambda incognito=False: _fake_login(provider))
        else:
            login_patch = mock.patch.dict(
                oauth.LOGIN_FUNCS,
                {provider: lambda incognito=False: _fake_login(provider)},
            )
        with login_patch:
            rc = pool.cmd_add(provider, f"{provider}-test")
        self.assertEqual(rc, 0, f"cmd_add({provider}) returned {rc}")
        acct = next(a for a in store.list_accounts(self.conn) if a["provider"] == provider)
        snap = store.latest_snapshot(self.conn, acct["id"])
        self.assertIsNotNone(snap, f"no snapshot saved for {provider}")
        return acct, snap

    def test_registered_tokenless_provider_uses_plain_add_route(self):
        adapter = types.ModuleType("providers.fake_local")
        adapter.PROVIDER = "fake_local"
        adapter.AUTH = util.AUTH_NONE
        adapter.poll = lambda conn, account, token: store.save_snapshot(
            conn, account["id"], util.snapshot([]))
        providers.register(adapter)
        self.addCleanup(providers.reset_cache)

        with mock.patch.object(pool, "DB", self.conn):
            rc = pool.cmd_add("fake_local", "Local test")

        self.assertEqual(rc, 0)
        account = next(a for a in store.list_accounts(self.conn)
                       if a["provider"] == "fake_local")
        self.assertIsNone(store.get_token(self.conn, account["id"]))
        self.assertEqual(store.latest_snapshot(self.conn, account["id"])["status"],
                         "active")

    def test_every_oauth_provider_onboarding_polls(self):
        """cmd_add must call poller.poll_account for every OAuth provider."""
        providers_with_login = [provider for provider in oauth.known_providers()
                                if providers.auth_kind(provider) in (None, util.AUTH_OAUTH)
                                if oauth.resolve_login(provider) is not None]
        for provider in providers_with_login:
            with self.subTest(provider=provider):
                _, snap = self._onboard(provider)
                self.assertEqual(snap["status"], "active",
                                 f"{provider} onboarding did not produce an active snapshot: "
                                 f"{snap.get('status_message')}")

    def test_devin_onboarding_polls(self):
        """cmd_add_devin must call poller.poll_account for devin."""
        with mock.patch.object(devin, "LOGIN", return_value={
            "access_token": "fake-devin-key", "refresh_token": None, "id_token": "",
            "expires_at": 0, "account_id": "devin-org-1",
            "email": "devin@example.com", "plan": "", "raw": {"api_key": "fake-devin-key"},
        }):
            rc = pool.cmd_add_devin("fake-devin-key", "devin-test")
        self.assertEqual(rc, 0)
        acct = next(a for a in store.list_accounts(self.conn) if a["provider"] == "devin")
        snap = store.latest_snapshot(self.conn, acct["id"])
        self.assertIsNotNone(snap, "no snapshot saved for devin")
        self.assertEqual(snap["status"], "active",
                         f"devin onboarding did not produce an active snapshot: "
                         f"{snap.get('status_message')}")

    def test_reconnect_oauth_account_updates_existing_account(self):
        """cmd_reconnect must refresh credentials in place and poll immediately."""
        acct, _ = self._onboard("codex")
        reconnected = _fake_login("codex")
        reconnected["access_token"] = "fake-codex-reconnected-access"
        reconnected["refresh_token"] = "fake-codex-reconnected-refresh"
        with mock.patch.object(codex, "LOGIN", return_value=reconnected):
            rc = pool.cmd_reconnect(str(acct["id"]))
        self.assertEqual(rc, 0)
        accounts = [a for a in store.list_accounts(self.conn) if a["provider"] == "codex"]
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["id"], acct["id"])
        token = store.get_token(self.conn, acct["id"])
        self.assertEqual(token["access_token"], "fake-codex-reconnected-access")
        snap = store.latest_snapshot(self.conn, acct["id"])
        self.assertIsNotNone(snap, "reconnect did not poll the account")
        self.assertEqual(snap["status"], "active")

    # ── per-provider subscription field coverage ──
    def test_codex_subscription_data(self):
        _, snap = self._onboard("codex")
        self.assertEqual(snap["plan"], "pro")
        raw = json.loads(snap["raw_json"])
        windows = {window["kind"]: window for window in raw["windows"]}
        self.assertEqual(windows["5h"]["used_pct"], 42.0)
        self.assertEqual(windows["5h"]["window_s"], 7200)
        self.assertIsNotNone(windows["5h"].get("reset_at"))
        self.assertEqual(windows["weekly"]["used_pct"], 10.0)
        self.assertEqual(windows["weekly"]["window_s"], 172800)
        self.assertIsNotNone(windows["weekly"].get("reset_at"))
        exported = codex.EXTRA(snap)
        self.assertEqual(exported["credits_balance"], 12.5)
        self.assertEqual(exported["banked_resets"], 2)
        self.assertEqual(len(exported["reset_credits"]), 1)
        # reset credits table must be populated
        acct = next(a for a in store.list_accounts(self.conn) if a["provider"] == "codex")
        credits = store.list_reset_credits(self.conn, acct["id"])
        self.assertEqual(len(credits), 1, "codex reset credits not populated")

    def test_codex_poll_returns_reset_credit_baseline(self):
        acct, _ = self._onboard("codex")
        token = store.get_token(self.conn, acct["id"])
        poll_meta = codex.poll(self.conn, acct, token)
        self.assertEqual(poll_meta["reset_credit_baseline"],
                         {"rc1": "available"})

    def test_claude_subscription_data(self):
        _, snap = self._onboard("claude")
        self.assertEqual(snap["plan"], "Claude Max")
        rj = json.loads(snap["raw_json"])
        windows = {window["kind"]: window for window in rj["windows"]}
        self.assertEqual(windows["5h"]["used_pct"], 7.0)
        self.assertEqual(windows["5h"]["window_s"], 18000)
        self.assertIsNotNone(windows["5h"].get("reset_at"))
        self.assertEqual(windows["weekly"]["used_pct"], 20.0)
        self.assertEqual(windows["weekly"]["window_s"], 604800)
        self.assertIsNotNone(windows["weekly"].get("reset_at"))
        exported = claude.EXTRA(snap)
        self.assertEqual(exported["rate_limit_remaining"], "normal")
        self.assertEqual(exported["rate_limit_limit"], "unified")
        # Profile must still be merged into raw_json.
        self.assertEqual(rj["profile"]["plan"], "Claude Max")

    def test_xai_subscription_data(self):
        _, snap = self._onboard("xai")
        rj = json.loads(snap["raw_json"])
        windows = {window["kind"]: window for window in rj["windows"]}
        self.assertEqual(windows["monthly"]["label"], "credits")
        self.assertEqual(windows["monthly"]["used_pct"], 30.0)
        self.assertEqual(windows["monthly"]["reset_at"],
                         "2026-02-01T00:00:00Z")
        self.assertEqual(windows["daily"]["used_pct"], 20.0)
        self.assertIsNotNone(windows["daily"].get("reset_at"))
        self.assertEqual(rj["extra"]["credits_used"], 30)
        self.assertEqual(rj["extra"]["credits_limit"], 100)
        exported = xai.EXTRA(snap)
        self.assertEqual(exported["credits_used"], 30)
        self.assertEqual(exported["credits_limit"], 100)
        self.assertEqual(exported["on_demand_cap"], 50)
        self.assertEqual(exported["billing_period_start"], "2026-01-01 09:00")
        self.assertEqual(exported["plan_start"], "2026-01-01 09:00")
        self.assertEqual(exported["plan_reset"], "2026-02-01 09:00")

    def test_antigravity_subscription_data(self):
        _, snap = self._onboard("antigravity")
        self.assertEqual(snap["plan"], "Antigravity")
        rj = json.loads(snap["raw_json"])
        windows = rj["windows"]
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["kind"], "model_weekly")
        self.assertEqual(windows[0]["label"], "Gemini 3 Pro")
        self.assertEqual(windows[0]["used_pct"], 25.0)
        self.assertIsNotNone(windows[0]["reset_at"])
        self.assertEqual(rj["extra"]["tier_id"], "standard-tier")
        exported = antigravity.EXTRA(snap)
        self.assertEqual(exported["rate_limit_remaining"],
                         "75% left (Gemini 3 Pro)")
        self.assertEqual(exported["rate_limit_limit"], "Antigravity")

    def test_antigravity_plan_labels(self):
        cases = [
            ({"tier_id": "standard-tier"}, "Antigravity"),
            ({"tier_id": "g1-plus-tier"}, "Google AI Plus"),
            ({"tier_id": "g1-pro-tier"}, "Google AI Pro"),
            ({"tier_id": "g1-ultra-tier"}, "Google AI Ultra"),
            ({"tier_override": "plus"}, "Google AI Plus"),
            ({"tier_override": "pro"}, "Google AI Pro"),
            ({"tier_override": "ultra-20x"}, "Google AI Ultra 20x"),
        ]
        for item, expected in cases:
            with self.subTest(item=item):
                name, _ = antigravity.PLAN_LABEL("Antigravity", item)
                self.assertEqual(name, expected)

    def test_copilot_subscription_data(self):
        _, snap = self._onboard("copilot")
        self.assertIsNotNone(snap["plan"], "copilot snapshot missing plan")
        rj = json.loads(snap["raw_json"])
        windows = {(window["kind"], window["label"]): window
                   for window in rj["windows"]}
        self.assertEqual(windows[("monthly", "premium")]["used_pct"], 40.0)
        self.assertIsNotNone(windows[("monthly", "premium")].get("reset_at"))
        self.assertEqual(windows[("monthly", "chat")]["used_pct"], 10.0)
        self.assertEqual(rj["extra"]["access_sku"], "individual_pro")
        self.assertEqual(rj["extra"]["limited_user_quotas"],
                         "1000 premium requests")
        self.assertEqual(rj["extra"]["limited_user_reset_date"], "2026-02-01")
        self.assertEqual(rj["extra"]["github_email"], "test@example.com")
        exported = copilot.EXTRA(snap)
        self.assertEqual(exported["access_sku"], "individual_pro")
        self.assertEqual(exported["rate_limit_limit"], "1000 premium requests")
        self.assertEqual(exported["rate_limit_reset"], "2026-02-01 09:00")
        self.assertEqual(exported["plan_start"], "2026-01-01")
        self.assertEqual(exported["plan_reset"], "2026-02-01 09:00")

    def test_devin_subscription_data(self):
        with mock.patch.object(devin, "LOGIN", return_value={
            "access_token": "fake-devin-key", "refresh_token": None, "id_token": "",
            "expires_at": 0, "account_id": "devin-org-1",
            "email": "devin@example.com", "plan": "", "raw": {"api_key": "fake-devin-key"},
        }):
            rc = pool.cmd_add_devin("fake-devin-key", "devin-test")
        self.assertEqual(rc, 0)
        acct = next(a for a in store.list_accounts(self.conn) if a["provider"] == "devin")
        snap = store.latest_snapshot(self.conn, acct["id"])
        self.assertIsNotNone(snap["plan"], "devin snapshot missing plan")
        rj = json.loads(snap["raw_json"])
        windows = {window["kind"]: window for window in rj["windows"]}
        self.assertEqual(windows["daily"]["remaining_pct"], 70)
        self.assertEqual(windows["daily"]["window_s"], 86400)
        self.assertIsNotNone(windows["daily"].get("reset_at"))
        self.assertEqual(windows["daily"]["boundary"], "midnight")
        self.assertEqual(windows["weekly"]["remaining_pct"], 40)
        self.assertEqual(windows["weekly"]["window_s"], 604800)
        self.assertIsNotNone(windows["weekly"].get("reset_at"))
        self.assertEqual(windows["weekly"]["boundary"],
                         rj["extra"]["plan_reset_unix"])
        self.assertEqual(rj["extra"]["credit_balance"], 5.0)
        self.assertIsNotNone(rj["extra"].get("plan_start_unix"))
        self.assertIsNotNone(rj["extra"].get("plan_reset_unix"))

    def test_export_includes_billing_period_fields(self):
        self._onboard("xai")
        with mock.patch.object(devin, "LOGIN", return_value={
            "access_token": "fake-devin-key", "refresh_token": None, "id_token": "",
            "expires_at": 0, "account_id": "devin-org-1",
            "email": "devin@example.com", "plan": "", "raw": {"api_key": "fake-devin-key"},
        }):
            self.assertEqual(pool.cmd_add_devin("fake-devin-key", "devin-test"), 0)

        payload = json.loads(Path(status.STATUS_JSON).read_text())
        by_provider = {a["provider"]: a for a in payload["accounts"]}
        xai = by_provider["xai"]
        self.assertEqual(xai["billing_period_start"], "2026-01-01 09:00")
        self.assertEqual(xai["plan_start"], "2026-01-01 09:00")
        self.assertEqual(xai["plan_reset"], "2026-02-01 09:00")
        devin_item = by_provider["devin"]
        self.assertIsNotNone(devin_item["plan_start"])
        self.assertIsNotNone(devin_item["plan_reset"])

    def test_export_includes_codex_subscription_meta(self):
        acct, _ = self._onboard("codex")
        store.upsert_subscription_meta(
            self.conn,
            acct["id"],
            paid_since="2026-06-09T00:05:39Z",
            renews_at="2026-07-09T14:59:59Z",
            account_created_at="2023-06-06T14:41:24Z",
            previous_paid_months=3,
            billing_note="confirmed prior Pro billing history",
        )

        status.cmd_export(self.conn)
        payload = json.loads(Path(status.STATUS_JSON).read_text())
        codex = next(a for a in payload["accounts"] if a["provider"] == "codex")
        self.assertEqual(codex["plan_start"], "2026-06-09 09:05")
        self.assertEqual(codex["plan_reset"], "2026-07-09 23:59")
        self.assertEqual(codex["account_created"], "2023-06-06 23:41")
        self.assertEqual(codex["payment_history"], "previous 3 months")

    def test_codex_subscription_meta_syncs_from_account_endpoints(self):
        acct, _ = self._onboard("codex")
        meta = store.get_subscription_meta(self.conn, acct["id"])
        self.assertEqual(meta["account_created_at"], "2023-06-06T14:41:24.785528Z")
        self.assertEqual(meta["renews_at"], "2026-08-09T14:59:59+00:00")
        self.assertEqual(meta["expires_at"], "2026-08-16T14:59:59+00:00")
        self.assertEqual(meta["subscription_plan"], "chatgptpro_partner_managed")
        self.assertEqual(meta["has_active_subscription"], 1)
        self.assertEqual(meta["is_active_subscription_gratis"], 0)
        self.assertEqual(meta["has_previously_paid_subscription"], 1)

        status.cmd_export(self.conn)
        payload = json.loads(Path(status.STATUS_JSON).read_text())
        codex = next(a for a in payload["accounts"] if a["provider"] == "codex")
        self.assertEqual(codex["plan_reset"], "2026-08-09 23:59")
        self.assertEqual(codex["expires_at"], "2026-08-16 23:59")
        self.assertEqual(codex["subscription_plan"], "chatgptpro_partner_managed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
