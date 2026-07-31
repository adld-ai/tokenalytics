"""Tests for the poller's use of the adapter registry.

Two things matter here: adapters must be reachable from _poll_one without
being hardcoded into POLLERS, and adapters that hold no credential of their
own (local files, localhost runtimes) must not be blocked by the token gate
that exists for the OAuth providers.
"""
from __future__ import annotations
import contextlib, io, json, os, sys, tempfile, types, unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tsb-test-")
os.environ["AGENT_POOL_DB"] = os.path.join(_TMP, "pool.db")
os.environ["AGENT_POOL_STATUS_JSON"] = os.path.join(_TMP, "status.json")
os.environ["AGENT_POOL_HISTORY_DIR"] = os.path.join(_TMP, "history")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import poller  # noqa: E402
import providers  # noqa: E402
import store  # noqa: E402
from providers import claude, codex  # noqa: E402
from providers import util  # noqa: E402


def adapter(name, auth, poll):
    m = types.ModuleType(f"providers.{name}")
    m.PROVIDER, m.AUTH, m.poll = name, auth, poll
    return m


class ResolvePollerTest(unittest.TestCase):
    def setUp(self):
        providers.reset_cache()
        self.addCleanup(providers.reset_cache)

    def test_migrated_codex_resolves_from_adapter(self):
        self.assertIs(poller.resolve_poller("codex"), codex.poll)

    def test_migrated_claude_resolves_from_adapter(self):
        self.assertIs(poller.resolve_poller("claude"), claude.poll)

    def test_legacy_poller_table_is_empty(self):
        self.assertEqual(poller.POLLERS, {})

    def test_adapter_resolves(self):
        fn = lambda conn, account, token: None  # noqa: E731
        providers.register(adapter("kimi", util.AUTH_API_KEY, fn))
        self.assertIs(poller.resolve_poller("kimi"), fn)

    def test_unknown_provider_resolves_to_none(self):
        self.assertIsNone(poller.resolve_poller("nope"))

    def test_legacy_pollers_win_over_an_adapter_of_the_same_name(self):
        """test doubles patch POLLERS; that must keep working."""
        fn = lambda conn, account, token: None  # noqa: E731
        with mock.patch.dict(poller.POLLERS, {"claude": fn}):
            self.assertIs(poller.resolve_poller("claude"), fn)


class TokenGateTest(unittest.TestCase):
    def setUp(self):
        providers.reset_cache()
        self.addCleanup(providers.reset_cache)
        self.conn = store.connect()
        self.addCleanup(self.conn.close)

    def _account(self, provider):
        aid = store.upsert_account(self.conn, provider, f"{provider}@x.test")
        return store.get_account(self.conn, aid)

    def _run(self, account):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            return poller._poll_one(self.conn, account)

    def test_tokenless_adapter_polls_without_a_token(self):
        seen = {}

        def poll(conn, account, token):
            seen["token"] = token
            store.save_snapshot(conn, account["id"],
                                util.snapshot([util.window("daily", used_pct=3.0)]))

        providers.register(adapter("ollama", util.AUTH_NONE, poll))
        account = self._account("ollama")
        self.assertTrue(self._run(account))
        self.assertIsNone(seen["token"])
        snap = store.latest_snapshot(self.conn, account["id"])
        self.assertEqual(snap["status"], "active")
        self.assertEqual(json.loads(snap["raw_json"])["windows"][0]["used_pct"], 3.0)

    def test_local_file_adapter_polls_without_a_token(self):
        providers.register(adapter(
            "opencode", util.AUTH_LOCAL_FILE,
            lambda conn, account, token: store.save_snapshot(
                conn, account["id"], util.snapshot([]))))
        self.assertTrue(self._run(self._account("opencode")))

    def test_credentialed_adapter_without_a_token_fails_closed(self):
        called = []
        providers.register(adapter(
            "kimi", util.AUTH_API_KEY,
            lambda conn, account, token: called.append(1)))
        account = self._account("kimi")
        self.assertFalse(self._run(account))
        self.assertEqual(called, [])
        self.assertEqual(store.latest_snapshot(self.conn, account["id"])["status_message"],
                         "no token")

    def test_unregistered_provider_without_a_token_still_fails_closed(self):
        account = self._account("codex")
        self.assertFalse(self._run(account))
        self.assertEqual(store.latest_snapshot(self.conn, account["id"])["status_message"],
                         "no token")

    def test_tokenless_adapter_errors_are_recorded_not_raised(self):
        def poll(conn, account, token):
            raise RuntimeError("ollama is not running")

        providers.register(adapter("ollama", util.AUTH_NONE, poll))
        account = self._account("ollama")
        self.assertFalse(self._run(account))
        snap = store.latest_snapshot(self.conn, account["id"])
        self.assertEqual(snap["status"], "error")
        self.assertIn("not running", snap["status_message"])

    def test_poll_metadata_forwards_reset_credit_baseline(self):
        providers.register(adapter(
            "creditful",
            util.AUTH_OAUTH,
            lambda conn, account, token: {
                "reset_credit_baseline": {"credit-1": "available"},
            },
        ))
        account = self._account("creditful")
        store.save_token(
            self.conn, account["id"], "token", None, None, 9_999_999_999, None
        )
        with mock.patch.object(poller, "_archive_closed_windows") as archive:
            self.assertTrue(self._run(account))
        self.assertEqual(archive.call_args.args[3],
                         {"credit-1": "available"})


if __name__ == "__main__":
    unittest.main()
