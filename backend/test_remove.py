#!/usr/bin/env python3
"""Regression: pool.cmd_remove must not race the poll daemon.

Before this fix, cmd_remove deleted the account and exported status.json
without holding the "poll" worker lock. A poller daemon mid-cycle (holding a
stale account list) could then rewrite status.json with the removed account,
resurrecting it in the menu bar.

Run:  python3 test_remove.py
"""
from __future__ import annotations
import fcntl, json, os, sys, tempfile, unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="tsb-test-remove-")
os.environ["AGENT_POOL_DB"] = os.path.join(_TMP, "pool.db")
_STATUS_JSON = Path(_TMP) / "status.json"
os.environ["AGENT_POOL_STATUS_JSON"] = str(_STATUS_JSON)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pool  # noqa: E402
import store  # noqa: E402


class RemoveRaceTest(unittest.TestCase):
    def test_remove_serializes_with_poll_lock(self):
        conn = pool.DB
        acct_id = store.upsert_account(conn, "codex", "race@example.com", "codex-race")

        # Simulate the poll daemon mid-cycle: it owns the exclusive lock, so
        # a concurrent remover must contend instead of deleting underneath it.
        lock_path = store.DB_PATH.parent / "poll.lock"
        with open(lock_path, "w") as held, open(lock_path, "w") as contender:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                fcntl.flock(held, fcntl.LOCK_UN)

        rc = pool.cmd_remove(acct_id)
        self.assertEqual(rc, 0)
        self.assertIsNone(store.get_account(conn, acct_id))

        # status.json was exported after the delete: the account is gone.
        # Whichever module imported status.py first decides STATUS_JSON for the
        # whole pytest session, so assert against the path status.py resolves
        # right now rather than this module's original env value.
        import status as status_mod
        payload = json.loads(status_mod.STATUS_JSON.read_text())
        ids = [a["id"] for a in payload["accounts"]]
        self.assertNotIn(acct_id, ids)

    def test_remove_unknown_account_is_a_noop(self):
        self.assertEqual(pool.cmd_remove(424242), 1)


if __name__ == "__main__":
    unittest.main()
