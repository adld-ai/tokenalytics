"""Structural guarantees from the 2026-07-31 refactor plan."""
import os, re, unittest

BACKEND = os.path.dirname(os.path.abspath(__file__))
PIPELINE = ["poller.py", "status.py", "window_history.py", "oauth.py", "store.py"]
PROVIDER_BRANCH = re.compile(r'provider\s*(?:==|in)\s*[("\']')


class StructureTest(unittest.TestCase):
    def test_no_provider_branches_in_pipeline(self):
        # legacy_windows.py is deliberately exempt: it is the quarantine for
        # pre-adapter snapshots and disappears once the history window ages out.
        for fname in PIPELINE:
            src = open(os.path.join(BACKEND, fname)).read()
            hits = [ln for ln in src.splitlines() if PROVIDER_BRANCH.search(ln)]
            self.assertEqual(hits, [], f"{fname} still branches on provider")

    def test_module_size_ceiling(self):
        for fname in os.listdir(BACKEND):
            if fname.endswith(".py") and not fname.startswith("test_"):
                n = len(open(os.path.join(BACKEND, fname)).readlines())
                self.assertLessEqual(n, 800, f"{fname} is {n} lines")


if __name__ == "__main__":
    unittest.main()
