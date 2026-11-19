import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from repo_readiness.clauses import ClauseFileError, lint_data, load

ROOT = Path(__file__).resolve().parent.parent
TOY = ROOT / "tests" / "fixtures" / "rulesets" / "toy-base.json"
TOY_DATA = json.loads(TOY.read_text(encoding="utf-8"))


def mutated(fn):
    d = copy.deepcopy(TOY_DATA)
    fn(d)
    return d


class LoadTest(unittest.TestCase):
    def test_toy_ruleset_loads(self):
        rs = load(TOY)
        self.assertEqual((rs.id, rs.version, rs.kind), ("toy", "1.0.0", "base"))
        self.assertEqual([t.id for t in rs.tiers], ["basic", "standard", "high"])
        self.assertEqual(len(rs.clauses), 6)
        self.assertEqual(len(rs.sha256), 64)

    def test_levels_and_defaults(self):
        rs = load(TOY)
        t2 = rs.clause("T2")
        self.assertEqual([(lv.tier, lv.strength) for lv in t2.levels], [("basic", "should"), ("standard", "must")])
        self.assertEqual(t2.lifecycle, "active")
        self.assertTrue(t2.na_allowed and t2.na_justification_required)
        self.assertFalse(rs.clause("T5").na_justification_required)
        self.assertEqual(rs.clause("T6").lifecycle, "future")

    def test_should_rule_per_tier_override(self):
        rs = load(TOY)
        self.assertEqual(rs.should_rule("basic"), {"rule": "ratio", "ratio": 0.8, "rounding": "floor"})
        self.assertEqual(rs.should_rule("standard"), {"rule": "max_missing", "max_missing": 1})

    def test_not_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text("{ nope", encoding="utf-8")
            with self.assertRaises(ClauseFileError):
                load(p)


class LintTest(unittest.TestCase):
    def assertProblem(self, data, fragment):
        problems = lint_data(data)
        self.assertTrue(any(fragment in p for p in problems), problems)

    def test_toy_is_clean(self):
        self.assertEqual(lint_data(TOY_DATA), [])

    def test_schema_violation(self):
        self.assertProblem(mutated(lambda d: d.pop("owner")), "owner")

    def test_should_rule_must_be_one_known_shape(self):
        self.assertProblem(mutated(lambda d: d["gate"].update(should={"rule": "ratio"})), "gate.should")

    def test_duplicate_clause_id(self):
        self.assertProblem(mutated(lambda d: d["clauses"].append(copy.deepcopy(d["clauses"][0]))), "duplicate clause id 'T1'")

    def test_unknown_tier_in_levels(self):
        self.assertProblem(mutated(lambda d: d["clauses"][0]["levels"].append({"tier": "gold", "strength": "must"})),
                           "unknown tier 'gold'")

    def test_tier_listed_twice_in_levels(self):
        self.assertProblem(mutated(lambda d: d["clauses"][0]["levels"].append({"tier": "basic", "strength": "should"})),
                           "lists tier 'basic' twice")

    def test_strength_cannot_weaken_at_higher_tier(self):
        self.assertProblem(mutated(lambda d: d["clauses"][1].update(levels=[
            {"tier": "basic", "strength": "must"}, {"tier": "standard", "strength": "should"}])), "weakens")

    def test_duplicate_tier_id_and_rank(self):
        self.assertProblem(mutated(lambda d: d["tiers"].append({"id": "basic", "name": "x", "rank": 9})), "duplicate tier id")
        self.assertProblem(mutated(lambda d: d["tiers"].append({"id": "extra", "name": "x", "rank": 1})), "duplicate tier rank")

    def test_unknown_probe(self):
        self.assertProblem(mutated(lambda d: d["clauses"][0].update(probe={"use": "github.nope"})), "unknown probe 'github.nope'")

    def test_unknown_probe_nested_in_then_and_when(self):
        self.assertProblem(mutated(lambda d: d["clauses"][3]["probe"].update(then={"use": "judge.nope"})), "unknown probe 'judge.nope'")
        self.assertProblem(mutated(lambda d: d["clauses"][4]["applies"].update(when={"use": "fs.nope"})), "unknown probe 'fs.nope'")

    def test_probe_parameters_checked(self):
        self.assertProblem(mutated(lambda d: d["clauses"][0]["probe"].update({"with": {}})), "fs.exists")
        self.assertProblem(mutated(lambda d: d["clauses"][0]["probe"].update({"with": {"path": "a", "x": 1}})), "fs.exists")

    def test_unknown_category(self):
        self.assertProblem(mutated(lambda d: d["clauses"][4]["applies"].update(categories=["backend"])), "unknown category 'backend'")

    def test_non_waivable_must_exist(self):
        self.assertProblem(mutated(lambda d: d["waiver"].update(non_waivable=["T9"])), "non_waivable")

    def test_enforce_from_must_be_a_real_date(self):
        self.assertProblem(mutated(lambda d: d["clauses"][1].update(enforce_from="2026-02-30")), "enforce_from")

    def test_stack_kind_not_yet_supported(self):
        def to_stack(d):
            d["kind"] = "stack"
            d["stack"] = "FE"
            for k in ("tiers", "below_lowest", "gate", "waiver", "app_aggregation"):
                d.pop(k)
        self.assertProblem(mutated(to_stack), "kind 'stack'")

    def test_stack_kind_must_not_carry_tiers(self):
        self.assertProblem(mutated(lambda d: d.update(kind="stack", stack="FE")), "tiers")


class CliLintTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([str(ROOT / "bin" / "repo-readiness"), *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)

    def test_clean_file_exits_zero(self):
        p = self.run_cli("clauses", "lint", str(TOY))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("toy 1.0.0", p.stdout)

    def test_problems_exit_two(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text(json.dumps(mutated(lambda x: x["clauses"].append(copy.deepcopy(x["clauses"][0])))),
                           encoding="utf-8")
            p = self.run_cli("clauses", "lint", str(bad))
        self.assertEqual(p.returncode, 2)
        self.assertIn("duplicate clause id", p.stderr)

    def test_missing_file_exits_two(self):
        p = self.run_cli("clauses", "lint", "/nonexistent/x.json")
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
