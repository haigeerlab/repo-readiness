import subprocess
import sys
import unittest
from pathlib import Path

import repo_readiness

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "bin" / "repo-readiness"


def invoke(*args):
    return subprocess.run([str(LAUNCHER), *args], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=30)


class CliTest(unittest.TestCase):
    def test_version(self):
        p = invoke("--version")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(repo_readiness.__version__, p.stdout)

    def test_no_arguments_is_usage_error(self):
        p = invoke()
        self.assertEqual(p.returncode, 2)

    def test_unknown_subcommand_is_usage_error(self):
        p = invoke("no-such-command")
        self.assertEqual(p.returncode, 2)

    def test_launcher_honours_python_override(self):
        env = {"PATH": "/usr/bin:/bin", "REPO_READINESS_PYTHON": sys.executable}
        p = subprocess.run([str(LAUNCHER), "--version"], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
