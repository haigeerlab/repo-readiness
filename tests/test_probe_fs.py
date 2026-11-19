import os
import tempfile
import unittest
from pathlib import Path

from repo_readiness.probes.runtime import ProbeContext, evaluate


class FsProbeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "README.md").write_text("# hi\n", encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "a.txt").write_text("x", encoding="utf-8")
        (self.root / "package-lock.json").write_text('{\n  "lockfileVersion": 3\n}\n', encoding="utf-8")
        (self.root / "apps" / "web").mkdir(parents=True)
        (self.root / "apps" / "web" / "README.md").write_text("web", encoding="utf-8")
        self.ctx = ProbeContext(repo_root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def ev(self, expr, ctx=None):
        return evaluate(expr, ctx or self.ctx)

    def test_exists(self):
        r = self.ev({"use": "fs.exists", "with": {"path": "README.md"}})
        self.assertEqual(r.status, "met")
        self.assertIn("README.md", r.evidence[0])
        r = self.ev({"use": "fs.exists", "with": {"path": "LICENSE"}})
        self.assertEqual(r.status, "gap")
        self.assertIn("LICENSE", r.missing)

    def test_escaping_the_repo_is_refused(self):
        # The last one stays inside the repo once resolved; '..' is still refused outright.
        for p in ("../etc/passwd", "/etc/passwd", "tests/../../x", "tests/../README.md"):
            with self.subTest(path=p):
                r = self.ev({"use": "fs.exists", "with": {"path": p}})
                self.assertEqual(r.status, "unknown")
                self.assertTrue(r.error)

    def test_symlink_out_of_the_repo_is_refused(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        os.symlink(outside.name, str(self.root / "link"))
        r = self.ev({"use": "fs.exists", "with": {"path": "link"}})
        self.assertEqual(r.status, "unknown")

    def test_glob(self):
        self.assertEqual(self.ev({"use": "fs.glob", "with": {"pattern": "tests/**/*"}}).status, "met")
        self.assertEqual(self.ev({"use": "fs.glob", "with": {"pattern": "tests/**/*", "min": 2}}).status, "gap")
        self.assertEqual(self.ev({"use": "fs.glob", "with": {"pattern": "docs/*.md"}}).status, "gap")

    def test_glob_ignores_git_directory(self):
        (self.root / ".git").mkdir()
        (self.root / ".git" / "HEAD").write_text("ref", encoding="utf-8")
        self.assertEqual(self.ev({"use": "fs.glob", "with": {"pattern": "**/HEAD"}}).status, "gap")

    def test_contains(self):
        r = self.ev({"use": "fs.contains", "with": {"path": "package-lock.json", "pattern": "lockfileVersion"}})
        self.assertEqual(r.status, "met")
        self.assertIn("package-lock.json:2", r.evidence[0])
        self.assertEqual(self.ev({"use": "fs.contains", "with": {"path": "README.md", "pattern": "nope"}}).status, "gap")
        self.assertEqual(self.ev({"use": "fs.contains", "with": {"path": "missing", "pattern": "x"}}).status, "gap")

    def test_contains_bad_regex_is_unknown(self):
        r = self.ev({"use": "fs.contains", "with": {"path": "README.md", "pattern": "("}})
        self.assertEqual(r.status, "unknown")

    def test_app_context_resolves_relative_to_app(self):
        ctx = ProbeContext(repo_root=self.root, base="apps/web")
        self.assertEqual(self.ev({"use": "fs.exists", "with": {"path": "README.md"}}, ctx).status, "met")
        self.assertEqual(self.ev({"use": "fs.exists", "with": {"path": "tests"}}, ctx).status, "gap")


class CombinatorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "A").write_text("", encoding="utf-8")
        self.ctx = ProbeContext(repo_root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    E = staticmethod(lambda p: {"use": "fs.exists", "with": {"path": p}})
    BAD = {"use": "fs.exists", "with": {"path": "../x"}}  # unknown

    def st(self, expr):
        return evaluate(expr, self.ctx).status

    def test_all(self):
        self.assertEqual(self.st({"all": [self.E("A"), self.E("A")]}), "met")
        self.assertEqual(self.st({"all": [self.E("A"), self.E("B")]}), "gap")
        self.assertEqual(self.st({"all": [self.E("A"), self.BAD]}), "unknown")
        self.assertEqual(self.st({"all": [self.BAD, self.E("B")]}), "gap")  # a definite gap wins

    def test_any(self):
        self.assertEqual(self.st({"any": [self.E("B"), self.E("A")]}), "met")
        self.assertEqual(self.st({"any": [self.E("B"), self.E("C")]}), "gap")
        self.assertEqual(self.st({"any": [self.E("B"), self.BAD]}), "unknown")

    def test_then_runs_only_after_met(self):
        self.assertEqual(self.st(dict(self.E("B"), then=self.E("A"))), "gap")
        self.assertEqual(self.st(dict(self.E("A"), then=self.E("B"))), "gap")
        self.assertEqual(self.st(dict(self.E("A"), then=self.E("A"))), "met")

    def test_declared_but_unimplemented_probe_is_unknown(self):
        # Every catalog probe is implemented today; simulate a ruler that is ahead of the tool.
        from repo_readiness.probes import runtime
        saved = runtime._IMPLEMENTATIONS.pop("fs.glob")
        try:
            r = evaluate({"use": "fs.glob", "with": {"pattern": "*"}}, self.ctx)
        finally:
            runtime._IMPLEMENTATIONS["fs.glob"] = saved
        self.assertEqual(r.status, "unknown")
        self.assertIn("not implemented", r.error)
        self.assertEqual(r.not_implemented, ["fs.glob"])


if __name__ == "__main__":
    unittest.main()
