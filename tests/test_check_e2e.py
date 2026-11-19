"""End-to-end: ruler + repo on disk -> report.json + summary.md + exit code."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from repo_readiness.resources import schema_validator

ROOT = Path(__file__).resolve().parent.parent
TOY = ROOT / "tests" / "fixtures" / "rulesets" / "toy-base.json"
AS_OF = "2026-11-19"


def make_repo(root: Path, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


FULL = {"README.md": "# toy\n", "LICENSE": "MIT\n", "tests/test_a.txt": "x\n"}


class CheckE2ETest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.out = self.tmp / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def check(self, *extra, ruleset=TOY):
        p = subprocess.run(
            [str(ROOT / "bin" / "repo-readiness"), "check", str(self.repo), "--clauses", str(ruleset),
             "--out", str(self.out), "--as-of", AS_OF, *extra],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        report = None
        if (self.out / "report.json").exists():
            report = json.loads((self.out / "report.json").read_text(encoding="utf-8"))
        return p, report

    def result(self, report, clause, target="repo"):
        for r in report["results"]:
            if r["clause"] == clause and r["target"] == target:
                return r
        self.fail("no result for %s/%s" % (clause, target))

    def test_full_repo_reaches_top_and_report_is_valid(self):
        make_repo(self.repo, FULL)
        p, report = self.check("--category", "plugin", "--min-tier", "standard")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(schema_validator("report.v1").errors(report), [])
        # High only holds a future clause: an empty tier is not reached (gate.empty_tier default).
        self.assertEqual(report["tier"]["id"], "standard")
        self.assertEqual(report["tier"]["trust_cap"], "L3")
        high = next(c for c in report["units"][0]["checks"] if c["tier"] == "high")
        self.assertTrue(high["empty"])
        self.assertFalse(high["reached"])
        self.assertEqual(report["rulesets"][0]["id"], "toy")
        self.assertEqual(len(report["rulesets"][0]["sha256"]), 64)
        # T4 is declare-then-judge; without readiness.yml there is no self-assessment: gap, not met.
        self.assertEqual(self.result(report, "T4")["status"], "gap")
        self.assertIn("readiness.yml", self.result(report, "T4")["missing"])
        self.assertTrue(any(n["clause"] == "T6" and "future" in n["reason"] for n in report["not_evaluated"]))
        summary = (self.out / "summary.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(summary.splitlines()), 30)
        self.assertIn("标准档", summary)
        self.assertIn("没有生效的必须项", summary)

    def test_missing_readme_is_below_lowest_and_fails_min_tier(self):
        make_repo(self.repo, {k: v for k, v in FULL.items() if k != "README.md"})
        p, report = self.check("--category", "plugin", "--min-tier", "basic")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIsNone(report["tier"]["id"])
        self.assertEqual(report["tier"]["name"], "未达标")
        self.assertEqual(report["tier"]["trust_cap"], "L0")
        self.assertEqual(report["next_tier"]["tier"], "basic")
        self.assertEqual(report["next_tier"]["must_failed"], ["T1"])
        self.assertIn("T1", (self.out / "summary.md").read_text(encoding="utf-8"))

    def test_without_min_tier_a_completed_run_exits_zero(self):
        make_repo(self.repo, {"LICENSE": "x"})
        p, report = self.check("--category", "plugin")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIsNone(report["tier"]["id"])

    def test_category_filter_and_when_condition(self):
        # frontend + package.json -> T5 applies and fails without a lockfile.
        make_repo(self.repo, dict(FULL, **{"package.json": "{}"}))
        _, report = self.check("--category", "frontend")
        self.assertEqual(self.result(report, "T5")["status"], "gap")
        self.assertIsNone(report["tier"]["id"])
        # plugin -> T5 does not apply.
        _, report = self.check("--category", "plugin")
        self.assertEqual(self.result(report, "T5")["status"], "na")
        # frontend without package.json -> the when-probe says n/a.
        (self.repo / "package.json").unlink()
        _, report = self.check("--category", "frontend")
        self.assertEqual(self.result(report, "T5")["status"], "na")

    def test_undeclared_category_makes_category_clauses_unknown(self):
        make_repo(self.repo, FULL)
        _, report = self.check()
        self.assertEqual(self.result(report, "T5")["status"], "unknown")

    def test_apps_are_judged_separately(self):
        make_repo(self.repo, dict(FULL, **{"apps/web/tests/t.txt": "x", "apps/api/src/x.txt": "x"}))
        _, report = self.check("--category", "plugin", "--app", "web=apps/web", "--app", "api=apps/api")
        self.assertEqual(self.result(report, "T3", "web")["status"], "met")
        self.assertEqual(self.result(report, "T3", "api")["status"], "gap")
        apps = {a["id"]: (a["root"], a["paths"]) for a in report["apps"]}
        self.assertEqual(apps, {"web": ("apps/web", ["apps/web/**"]), "api": ("apps/api", ["apps/api/**"])})
        tiers = {a["id"]: a["tier"] for a in report["apps"]}
        self.assertEqual(tiers, {"web": "standard", "api": "basic"})
        self.assertEqual(report["tier"]["id"], "basic")

    def test_app_with_extra_globs(self):
        make_repo(self.repo, dict(FULL, **{"apps/web/tests/t.txt": "x"}))
        _, report = self.check("--category", "plugin", "--app", "web=apps/web,packages/web/**,libs/*/web/**")
        self.assertEqual(report["apps"][0]["root"], "apps/web")
        self.assertEqual(report["apps"][0]["paths"], ["apps/web/**", "packages/web/**", "libs/*/web/**"])

    def test_bad_app_specs_exit_two(self):
        make_repo(self.repo, FULL)
        for spec in ("web", "=apps/web", "web=", "web=../x", "web=/abs", "web=apps/web,../y/**", "web=apps/web,,"):
            with self.subTest(spec=spec):
                p, _ = self.check("--app", spec)
                self.assertEqual(p.returncode, 2, p.stderr)

    def test_as_of_controls_enforce_from(self):
        make_repo(self.repo, {k: v for k, v in FULL.items() if k != "LICENSE"})

        def standard_check(report):
            return next(c for c in report["units"][0]["checks"] if c["tier"] == "standard")

        _, before = self.check("--category", "plugin")
        self.assertEqual(standard_check(before)["grace"], ["T2"])  # enforce_from 2026-12-01 not reached yet
        self.assertNotIn("T2", standard_check(before)["must_failed"])
        p = subprocess.run([str(ROOT / "bin" / "repo-readiness"), "check", str(self.repo), "--clauses", str(TOY),
                            "--out", str(self.out), "--as-of", "2026-12-01", "--category", "plugin"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        after = json.loads((self.out / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(p.returncode, 0)
        self.assertEqual(standard_check(after)["grace"], [])
        self.assertIn("T2", standard_check(after)["must_failed"])

    def test_usage_errors_exit_two(self):
        make_repo(self.repo, FULL)
        p, _ = self.check("--min-tier", "platinum")
        self.assertEqual(p.returncode, 2)
        self.assertIn("platinum", p.stderr)
        bad = self.tmp / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        p, _ = self.check(ruleset=bad)
        self.assertEqual(p.returncode, 2)
        p = subprocess.run([str(ROOT / "bin" / "repo-readiness"), "check", str(self.tmp / "nope"), "--clauses",
                            str(TOY), "--out", str(self.out)], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2)

    def test_fingerprint_is_stable_and_changes_with_evidence(self):
        make_repo(self.repo, FULL)
        _, a = self.check("--category", "plugin")
        _, b = self.check("--category", "plugin")
        self.assertEqual(self.result(a, "T1")["fingerprint"], self.result(b, "T1")["fingerprint"])
        (self.repo / "README.md").unlink()
        _, c = self.check("--category", "plugin")
        self.assertNotEqual(self.result(a, "T1")["fingerprint"], self.result(c, "T1")["fingerprint"])

    def test_git_head_is_recorded_when_repo_is_a_git_checkout(self):
        make_repo(self.repo, FULL)
        env_git = ["git", "-C", str(self.repo)]
        subprocess.run(env_git + ["init", "-q"], check=True, stdin=subprocess.DEVNULL)
        subprocess.run(env_git + ["-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", "-A"], check=True)
        subprocess.run(env_git + ["-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "x"],
                       check=True, stdin=subprocess.DEVNULL)
        _, report = self.check("--category", "plugin")
        self.assertRegex(report["repo"]["head"], "^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
