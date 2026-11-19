"""The v2.0 basic-tier trial transcription must match the standard's tables row by row.

EXPECTED is copied by hand from onboarding-standard-v2.md (2026-11-19) §4 and §5.3,
with the corrections agreed in mailbox #21538 (V2 counted once, at basic).
"""

import unittest
from pathlib import Path

from repo_readiness.clauses import load

TRIAL = Path(__file__).resolve().parent / "fixtures" / "rulesets" / "autopr-onboarding-2.0-basic.trial.json"
ALL = "*"

# id: (levels, scope, categories)
EXPECTED = {
    "G1": ([("basic", "must")], "repo", ALL),
    "G2": ([("basic", "must")], "repo", ALL),
    "G3": ([("basic", "must")], "repo", ALL),
    "G4": ([("basic", "must")], "repo", ALL),
    "G5": ([("basic", "must")], "repo", ALL),
    "G6": ([("basic", "must")], "repo", ALL),
    "G7": ([("basic", "must")], "repo", ALL),
    "V1": ([("basic", "must")], "repo", ALL),
    "V2": ([("basic", "should")], "repo", ["plugin", "frontend"]),
    "D1": ([("basic", "must")], "repo", ALL),
    "D2": ([("basic", "should"), ("standard", "must")], "repo", ALL),
    "E1": ([("basic", "must")], "app", ALL),
    "K1": ([("basic", "should")], "repo", ["plugin", "frontend"]),
    "R1": ([("basic", "must")], "repo", ALL),
    "R2": ([("basic", "should"), ("standard", "must")], "app", ALL),
}


class TrialRulesetTest(unittest.TestCase):
    def setUp(self):
        self.rs = load(TRIAL)

    def test_exactly_the_basic_tier_clauses(self):
        self.assertEqual(sorted(c.id for c in self.rs.clauses), sorted(EXPECTED))

    def test_each_clause_matches_the_standard(self):
        for cid, (levels, scope, cats) in EXPECTED.items():
            with self.subTest(clause=cid):
                c = self.rs.clause(cid)
                self.assertEqual([(lv.tier, lv.strength) for lv in c.levels], levels)
                self.assertEqual(c.scope, scope)
                self.assertEqual(c.applies["categories"], cats)

    def test_gate_and_caps_follow_the_standard(self):
        self.assertEqual([(t.id, t.trust_cap) for t in self.rs.ordered_tiers()],
                         [("basic", "L2"), ("standard", "L3"), ("high", "L4")])
        self.assertEqual(self.rs.below_lowest["trust_cap"], "L0")
        self.assertEqual(self.rs.should_rule("basic"), {"rule": "ratio", "ratio": 0.8, "rounding": "floor"})
        self.assertEqual(sorted(self.rs.waiver["non_waivable"]), ["G2", "G5", "G6"])
        self.assertEqual(self.rs.waiver["max_days"], 90)

    def test_security_floor_clauses_cannot_be_marked_na(self):
        for cid in ("G2", "G5", "G6"):
            self.assertFalse(self.rs.clause(cid).na_allowed, cid)


if __name__ == "__main__":
    unittest.main()
