"""T19: composing a base ruler with stack rulers (kind: stack).

- the repository's declared stacks win; detection only fills in when nothing is declared and is
  otherwise reported as "to confirm" without affecting the score;
- stack clauses apply only to targets of that stack (otherwise n/a);
- a stack may only tighten base clauses (keep every level, never weaken); redefining an id,
  loosening, or using unknown tiers fails to load (exit 2).
Adding a stack is data only: the toy stack rulers here needed no code.
"""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from repo_readiness.clauses import ClauseFileError, compose, load, load_stack

ROOT = Path(__file__).resolve().parent.parent
RS = ROOT / "tests" / "fixtures" / "rulesets"
BASE, FE, SH = RS / "toy-base.json", RS / "toy-stack-fe.json", RS / "toy-stack-sh.json"
FE_DATA = json.loads(FE.read_text(encoding="utf-8"))


def stack_file(tmp: Path, edit) -> Path:
    d = copy.deepcopy(FE_DATA)
    edit(d)
    p = tmp / ("stack-%d.json" % len(list(tmp.glob("stack-*.json"))))
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


class ComposeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_compose_adds_stack_clauses_and_applies_tighten(self):
        rs = compose(load(BASE), [load_stack(FE), load_stack(SH)])
        ids = [c.id for c in rs.clauses]
        self.assertIn("ST-FE-1", ids)
        self.assertIn("ST-SH-1", ids)
        self.assertEqual(rs.clause("ST-FE-1").stack, "FE")
        self.assertIsNone(rs.clause("T1").stack)
        t2 = rs.clause("T2")
        self.assertEqual([(lv.tier, lv.strength) for lv in t2.levels], [("basic", "must"), ("standard", "must")])
        self.assertEqual(t2.tightened_by, ("FE",))
        self.assertEqual([r["id"] for r in rs.parts], ["toy", "toy-fe", "toy-sh"])

    def assertComposeFails(self, edit, fragment):
        with self.assertRaises(ClauseFileError) as cm:
            compose(load(BASE), [load_stack(stack_file(self.tmp, edit))])
        self.assertTrue(any(fragment in p for p in cm.exception.problems), cm.exception.problems)

    def test_redefining_a_base_id_fails(self):
        self.assertComposeFails(lambda d: d["clauses"][0].update(id="T1"), "already defined")

    def test_loosening_fails(self):
        self.assertComposeFails(lambda d: d["tighten"][0].update(levels=[{"tier": "standard", "strength": "should"}]),
                                "loosens")

    def test_dropping_a_level_fails(self):
        self.assertComposeFails(lambda d: d["tighten"][0].update(levels=[{"tier": "basic", "strength": "must"}]),
                                "loosens")

    def test_tighten_unknown_clause_fails(self):
        self.assertComposeFails(lambda d: d["tighten"][0].update(id="T99"), "unknown clause")

    def test_unknown_tier_fails(self):
        self.assertComposeFails(lambda d: d["clauses"][0]["levels"][0].update(tier="gold"), "unknown tier")

    def test_two_stacks_defining_the_same_id_fail(self):
        other = stack_file(self.tmp, lambda d: (d.update(id="toy-fe2", stack="FX"), d.pop("tighten")))
        with self.assertRaises(ClauseFileError):
            compose(load(BASE), [load_stack(FE), load_stack(other)])

    def test_tighten_cannot_touch_applicability(self):
        self.assertComposeFails(lambda d: d["tighten"][0].update(applies={"categories": "*"}), "tighten")

    def test_stack_with_more_than_two_musts_warns(self):
        def three(d):
            for i in (3, 4):
                c = copy.deepcopy(d["clauses"][0])
                c["id"] = "ST-FE-%d" % i
                d["clauses"].append(c)
        rs = compose(load(BASE), [load_stack(stack_file(self.tmp, three))])
        self.assertTrue(any("3 must" in w for w in rs.warnings), rs.warnings)

    def test_lint_with_base(self):
        p = subprocess.run([str(ROOT / "bin" / "repo-readiness"), "clauses", "lint", str(FE), "--base", str(BASE)],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("toy-fe", p.stdout)
        p = subprocess.run([str(ROOT / "bin" / "repo-readiness"), "clauses", "lint", str(FE)],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 2)
        self.assertIn("--base", p.stderr)


class CheckWithStacksTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        for rel in ("README.md", "LICENSE", "tests/t.txt", "package.json", "tsconfig.json", "scripts/a.sh"):
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}" if rel.endswith(".json") else "x", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def check(self, readiness=None, *extra):
        if readiness is not None:
            (self.repo / ".github" / "autopr").mkdir(parents=True, exist_ok=True)
            (self.repo / ".github" / "autopr" / "readiness.yml").write_text(readiness, encoding="utf-8")
        out = self.tmp / "out"
        p = subprocess.run([str(ROOT / "bin" / "repo-readiness"), "check", str(self.repo), "--clauses", str(BASE),
                            "--stack-clauses", str(FE), "--stack-clauses", str(SH), "--out", str(out),
                            "--category", "plugin", "--as-of", "2026-11-20", *extra],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertIn(p.returncode, (0, 1), p.stderr)
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        return {(r["clause"], r["target"]): r for r in report["results"]}, report

    def test_declared_stacks_win_and_mismatches_are_listed(self):
        res, report = self.check("stacks: [SH]\n")
        self.assertEqual(res[("ST-SH-1", "repo")]["status"], "gap")  # declared: judged
        self.assertEqual(res[("ST-FE-1", "repo")]["status"], "na")   # not declared: n/a, even though detected
        st = report["stacks"]
        self.assertEqual((st["source"], st["used"]), ("declared", ["SH"]))
        self.assertIn("FE", st["detected"])
        self.assertEqual(st["to_confirm"], [{"stack": "FE", "issue": "detected but not declared"}])
        self.assertEqual([r["id"] for r in report["rulesets"]], ["toy", "toy-fe", "toy-sh"])

    def test_detection_is_used_when_nothing_is_declared(self):
        res, report = self.check()
        self.assertEqual(report["stacks"]["source"], "detected")
        self.assertEqual(sorted(report["stacks"]["used"]), ["FE", "SH"])
        self.assertEqual(res[("ST-FE-1", "repo")]["status"], "met")

    def test_declared_but_not_detected_is_listed(self):
        (self.repo / "package.json").unlink()
        _, report = self.check("stacks: [FE, SH]\n")
        self.assertEqual(report["stacks"]["to_confirm"], [{"stack": "FE", "issue": "declared but not detected"}])

    def test_unknown_declared_stack_is_a_usage_error(self):
        (self.repo / ".github" / "autopr").mkdir(parents=True)
        (self.repo / ".github" / "autopr" / "readiness.yml").write_text("stacks: [GO]\n", encoding="utf-8")
        p = subprocess.run([str(ROOT / "bin" / "repo-readiness"), "check", str(self.repo), "--clauses", str(BASE),
                            "--stack-clauses", str(FE), "--out", str(self.tmp / "o")],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2)
        self.assertIn("GO", p.stderr)

    def test_per_app_stacks(self):
        for rel in ("apps/web/tsconfig.json", "apps/api/x.txt"):
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}", encoding="utf-8")
        readiness = ("stacks: [SH]\napps:\n  web: { path: \"apps/web\", stacks: [FE] }\n"
                     "  api: { path: \"apps/api\" }\n")
        res, report = self.check(readiness)
        self.assertEqual(res[("ST-FE-1", "web")]["status"], "met")
        self.assertEqual(res[("ST-FE-1", "api")]["status"], "na")
        self.assertEqual(report["stacks"]["apps"], {"web": ["FE"], "api": ["SH"]})

    def test_tighten_takes_effect(self):
        (self.repo / "LICENSE").unlink()
        # After T2's enforce_from: tightening changes the requirement, it does not cancel the grace period.
        _, report = self.check("stacks: [FE]\n", "--as-of", "2026-12-02")
        basic = report["units"][0]["checks"][0]
        self.assertIn("T2", basic["must_failed"])  # FE tightened T2 to must at basic

    def test_without_stack_rulers_nothing_changes(self):
        out = self.tmp / "plain"
        p = subprocess.run([str(ROOT / "bin" / "repo-readiness"), "check", str(self.repo), "--clauses", str(BASE),
                            "--out", str(out), "--category", "plugin", "--as-of", "2026-11-20"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        self.assertNotIn("stacks", report)


if __name__ == "__main__":
    unittest.main()
