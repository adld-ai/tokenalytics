"""Tests for the provider adapter registry and its helpers.

An adapter is a module under backend/providers/ that declares PROVIDER, AUTH
and poll(conn, account, token). The registry discovers them, tells the poller
which ones can run without a stored token, and must never let one broken
adapter take the daemon down with it.
"""
from __future__ import annotations
import json, os, sys, tempfile, types, unittest

_TMP = tempfile.mkdtemp(prefix="tsb-test-")
os.environ["AGENT_POOL_DB"] = os.path.join(_TMP, "pool.db")
os.environ["AGENT_POOL_STATUS_JSON"] = os.path.join(_TMP, "status.json")
os.environ["AGENT_POOL_HISTORY_DIR"] = os.path.join(_TMP, "history")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import providers  # noqa: E402
from providers import util  # noqa: E402
import oauth  # noqa: E402
import status  # noqa: E402
import store  # noqa: E402
import window_history as wh  # noqa: E402


def fake_adapter(name, auth, poll=None):
    m = types.ModuleType(f"providers.{name}")
    m.PROVIDER = name
    m.AUTH = auth
    m.poll = poll or (lambda conn, account, token: None)
    return m


class RegistryTest(unittest.TestCase):
    def setUp(self):
        providers.reset_cache()
        self.addCleanup(providers.reset_cache)

    def test_discovery_registers_by_provider_name(self):
        providers.register(fake_adapter("kimi", util.AUTH_API_KEY))
        self.assertIn("kimi", providers.names())
        self.assertIsNotNone(providers.get("kimi"))

    def test_pollers_maps_name_to_poll_callable(self):
        calls = []
        providers.register(fake_adapter(
            "kimi", util.AUTH_API_KEY,
            poll=lambda conn, account, token: calls.append(account["id"])))
        providers.pollers()["kimi"](None, {"id": 7}, None)
        self.assertEqual(calls, [7])

    def test_auth_kind_is_reported(self):
        providers.register(fake_adapter("ollama", util.AUTH_NONE))
        self.assertEqual(providers.auth_kind("ollama"), util.AUTH_NONE)
        self.assertIsNone(providers.auth_kind("nope"))

    def test_tokenless_adapters_do_not_require_a_token(self):
        providers.register(fake_adapter("ollama", util.AUTH_NONE))
        providers.register(fake_adapter("opencode", util.AUTH_LOCAL_FILE))
        self.assertFalse(providers.requires_token("ollama"))
        self.assertFalse(providers.requires_token("opencode"))

    def test_credentialed_adapters_require_a_token(self):
        providers.register(fake_adapter("kimi", util.AUTH_API_KEY))
        self.assertTrue(providers.requires_token("kimi"))

    def test_unknown_provider_requires_a_token(self):
        """Legacy pollers are not adapters; they must keep their token gate."""
        self.assertTrue(providers.requires_token("codex"))

    def test_adapter_without_required_attributes_is_rejected(self):
        m = types.ModuleType("providers.broken")
        m.PROVIDER = "broken"
        with self.assertRaises(ValueError):
            providers.register(m)

    def test_adapter_with_unknown_auth_is_rejected(self):
        with self.assertRaises(ValueError):
            providers.register(fake_adapter("weird", "telepathy"))

    def test_real_package_discovery_does_not_raise(self):
        providers.reset_cache()
        self.assertIsInstance(providers.load(), dict)

    def test_optional_oauth_hooks_and_capabilities_are_exposed(self):
        login = lambda incognito=False: {"incognito": incognito}
        refresh = lambda token: {"access_token": token}
        plan_label = lambda snap: snap.get("plan")
        extra = lambda snap: {"source": snap.get("source")}
        browser_flow = {"host": "localhost", "port": 9876}
        adapter = fake_adapter("hooked", util.AUTH_OAUTH)
        adapter.LOGIN = login
        adapter.REFRESH = refresh
        adapter.BROWSER_FLOW = browser_flow
        adapter.CAPS = frozenset({"heartbeat", "swap"})
        adapter.PLAN_LABEL = plan_label
        adapter.EXTRA = extra

        providers.register(adapter)

        self.assertIs(providers.login_funcs()["hooked"], login)
        self.assertIs(providers.refresh_funcs()["hooked"], refresh)
        self.assertIs(providers.browser_flows()["hooked"], browser_flow)
        self.assertEqual(providers.caps("hooked"),
                         frozenset({"heartbeat", "swap"}))
        self.assertIs(providers.hook("hooked", "PLAN_LABEL"), plan_label)
        self.assertIs(providers.hook("hooked", "EXTRA"), extra)
        self.assertIs(oauth.resolve_login("hooked"), login)
        self.assertIs(oauth.resolve_refresh("hooked"), refresh)
        self.assertIn("hooked", oauth.known_providers())

    def test_codex_declares_heartbeat_and_swap_capabilities(self):
        self.assertEqual(providers.caps("codex"),
                         frozenset({"heartbeat", "swap"}))

    def test_legacy_oauth_hooks_override_adapter_hooks(self):
        legacy_login = oauth.resolve_login("claude")
        legacy_refresh = oauth.resolve_refresh("claude")
        adapter = fake_adapter("claude", util.AUTH_OAUTH)
        adapter.LOGIN = lambda incognito=False: None
        adapter.REFRESH = lambda token: None
        providers.register(adapter)

        self.assertIs(oauth.resolve_login("claude"), legacy_login)
        self.assertIs(oauth.resolve_refresh("claude"), legacy_refresh)

    def test_adapter_with_unknown_capability_is_rejected(self):
        adapter = fake_adapter("future", util.AUTH_OAUTH)
        adapter.CAPS = frozenset({"teleport"})
        with self.assertRaises(ValueError):
            providers.register(adapter)

    def test_optional_callable_hooks_are_validated(self):
        for attr in ("LOGIN", "REFRESH", "PLAN_LABEL", "EXTRA"):
            with self.subTest(attr=attr):
                adapter = fake_adapter(f"bad-{attr.lower()}", util.AUTH_OAUTH)
                setattr(adapter, attr, "not callable")
                with self.assertRaises(ValueError):
                    providers.register(adapter)

    def test_missing_optional_hooks_have_empty_defaults(self):
        providers.register(fake_adapter("plain", util.AUTH_NONE))
        self.assertEqual(providers.caps("plain"), frozenset())
        self.assertIsNone(providers.hook("plain", "LOGIN"))
        self.assertNotIn("plain", providers.login_funcs())
        self.assertNotIn("plain", providers.refresh_funcs())
        self.assertNotIn("plain", providers.browser_flows())


class WindowHelperTest(unittest.TestCase):
    def test_window_drops_unset_fields(self):
        w = util.window("5h", used_pct=12.0)
        self.assertEqual(w, {"kind": "5h", "used_pct": 12.0})

    def test_window_keeps_what_was_given(self):
        w = util.window("weekly", remaining_pct=40.0, reset_at=5000.0,
                        label="opus", severity="warning")
        self.assertEqual(w, {"kind": "weekly", "remaining_pct": 40.0,
                             "reset_at": 5000.0, "label": "opus",
                             "severity": "warning"})

    def test_snapshot_serializes_windows_into_raw_json(self):
        snap = util.snapshot([util.window("daily", used_pct=5.0)], plan="pro")
        self.assertEqual(snap["status"], "active")
        self.assertEqual(snap["plan"], "pro")
        rj = json.loads(snap["raw_json"])
        self.assertEqual(rj["windows"], [{"kind": "daily", "used_pct": 5.0}])

    def test_snapshot_merges_extra_raw_without_losing_windows(self):
        snap = util.snapshot([util.window("daily", used_pct=5.0)],
                             raw={"balance": 12})
        rj = json.loads(snap["raw_json"])
        self.assertEqual(rj["balance"], 12)
        self.assertEqual(len(rj["windows"]), 1)

    def test_snapshot_with_no_windows_still_declares_the_key(self):
        """Declaring an empty list is how an adapter says 'no quota data'."""
        rj = json.loads(util.snapshot([])["raw_json"])
        self.assertEqual(rj["windows"], [])

    def test_error_snapshot_is_truncated_and_marked(self):
        snap = util.error("x" * 500)
        self.assertEqual(snap["status"], "error")
        self.assertLessEqual(len(snap["status_message"]), 200)
        self.assertNotIn("raw_json", snap)

    def test_snapshot_round_trips_through_status_and_history(self):
        """The whole point: an adapter snapshot needs no schema column."""
        snap = util.snapshot([util.window("5h", used_pct=61.0, reset_at=5000.0)])
        conn = store.connect()
        try:
            aid = store.upsert_account(conn, "kimi", "a@b.c")
            store.save_snapshot(conn, aid, snap)
            saved = store.latest_snapshot(conn, aid)
        finally:
            conn.close()
        w = status.normalize_windows("kimi", saved)
        self.assertEqual([(x["kind"], x["used_pct"]) for x in w], [("5h", 61.0)])
        h = wh.timed_windows("kimi", saved)
        self.assertEqual([(x["kind"], x["reset_at"]) for x in h], [("5h", 5000.0)])


class ReadHelperTest(unittest.TestCase):
    def test_read_json_returns_none_for_missing_file(self):
        self.assertIsNone(util.read_json(os.path.join(_TMP, "nope.json")))

    def test_read_json_returns_none_for_malformed_file(self):
        p = os.path.join(_TMP, "bad.json")
        with open(p, "w") as f:
            f.write("{not json")
        self.assertIsNone(util.read_json(p))

    def test_read_json_expands_user_and_parses(self):
        p = os.path.join(_TMP, "ok.json")
        with open(p, "w") as f:
            json.dump({"a": {"b": 1}}, f)
        self.assertEqual(util.read_json(p), {"a": {"b": 1}})

    def test_dig_walks_nested_keys(self):
        obj = {"a": {"b": [{"c": 3}]}}
        self.assertEqual(util.dig(obj, "a", "b", 0, "c"), 3)

    def test_dig_returns_default_on_a_missing_branch(self):
        self.assertIsNone(util.dig({"a": 1}, "a", "b"))
        self.assertEqual(util.dig({}, "x", default=9), 9)

    def test_first_existing_picks_the_first_present_path(self):
        p = os.path.join(_TMP, "present.txt")
        open(p, "w").close()
        self.assertEqual(str(util.first_existing("/no/such/file", p)), p)
        self.assertIsNone(util.first_existing("/no/such/file"))

    def test_run_json_parses_stdout(self):
        self.assertEqual(util.run_json(["printf", '{"ok": true}']), {"ok": True})

    def test_run_json_returns_none_on_failure(self):
        self.assertIsNone(util.run_json(["false"]))
        self.assertIsNone(util.run_json(["definitely-not-a-real-binary-xyz"]))
        self.assertIsNone(util.run_json(["printf", "not json"]))


if __name__ == "__main__":
    unittest.main()
