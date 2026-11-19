import sys
import unittest
from pathlib import Path

from repo_readiness.proc import EXIT_ENV_NOT_READY, run

HERE = Path(__file__).resolve().parent


class RunTest(unittest.TestCase):
    def test_success_captures_output(self):
        r = run([sys.executable, "-c", "print('hi')"], cwd=HERE, timeout_s=10)
        self.assertEqual(r.code, 0)
        self.assertEqual(r.stdout.strip(), "hi")
        self.assertFalse(r.timed_out)

    def test_nonzero_exit_is_passed_through(self):
        r = run([sys.executable, "-c", "import sys; sys.exit(7)"], cwd=HERE, timeout_s=10)
        self.assertEqual(r.code, 7)

    def test_stdin_is_closed(self):
        # A child that reads stdin must see EOF immediately instead of hanging.
        r = run([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], cwd=HERE, timeout_s=10)
        self.assertEqual(r.code, 0)
        self.assertEqual(r.stdout.strip(), "''")

    def test_timeout_maps_to_env_not_ready(self):
        r = run([sys.executable, "-c", "import time; time.sleep(5)"], cwd=HERE, timeout_s=1)
        self.assertTrue(r.timed_out)
        self.assertEqual(r.code, EXIT_ENV_NOT_READY)

    def test_missing_executable_maps_to_env_not_ready(self):
        r = run(["definitely-not-a-real-binary-xyz"], cwd=HERE, timeout_s=5)
        self.assertEqual(r.code, EXIT_ENV_NOT_READY)
        self.assertIn("not found", r.stderr)

    def test_env_is_replaced_when_given(self):
        r = run([sys.executable, "-c", "import os; print(os.environ.get('RR_PROBE', 'absent'))"],
                cwd=HERE, timeout_s=10, env={"RR_PROBE": "x", "PATH": "/usr/bin:/bin"})
        self.assertEqual(r.stdout.strip(), "x")


if __name__ == "__main__":
    unittest.main()
