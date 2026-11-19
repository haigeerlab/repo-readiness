"""Table-driven tests for the gate rules. Every rule has a 'just short' counter-example."""

import datetime
import unittest

from repo_readiness.clauses import from_data
from repo_readiness.detect.score import Outcome, score

TODAY = datetime.date(2026, 11, 19)


def ruler(clauses, should=None, tiers=None, na_majority="not-reached", non_waivable=(), max_days=90,
          empty_tier="reached"):
    """Table tests use sparse tiers on purpose, so they opt into empty_tier=reached; EmptyTierTest covers the default."""
    gate = {"should": should or {"rule": "ratio", "ratio": 0.8, "rounding": "floor"}, "na_majority": na_majority}
    if empty_tier:
        gate["empty_tier"] = empty_tier
    return from_data({
        "schema": "repo-readiness.clauses/v1", "id": "t", "version": "1.0.0", "kind": "base", "owner": "x",
        "tiers": tiers or [
            {"id": "basic", "name": "B", "rank": 1},
            {"id": "standard", "name": "S", "rank": 2},
        ],
        "below_lowest": {"name": "none"},
        "gate": gate,
        "waiver": {"max_days": max_days, "non_waivable": list(non_waivable)},
        "clauses": clauses,
    })


def clause(cid, *levels, scope="repo", **extra):
    c = {"id": cid, "requirement": cid, "guards": "g", "scope": scope, "applies": {"categories": "*"},
         "method": "auto", "probe": {"use": "fs.exists", "with": {"path": "x"}},
         "levels": [{"tier": t, "strength": s} for t, s in levels]}
    c.update(extra)
    return c


def must(cid, tier="basic", **kw):
    return clause(cid, (tier, "must"), **kw)


def should(cid, tier="basic", **kw):
    return clause(cid, (tier, "should"), **kw)


def outcomes(**statuses):
    """outcomes(A='met', B='gap') -> {(A, 'repo'): Outcome('met'), ...}"""
    return {(cid, "repo"): (s if isinstance(s, Outcome) else Outcome(s)) for cid, s in statuses.items()}


def tier_of(rs, outs, apps=()):
    return score(rs, outs, apps=apps, today=TODAY).tier


class MustTest(unittest.TestCase):
    def test_all_met_reaches_top(self):
        rs = ruler([must("A"), must("B", "standard")])
        self.assertEqual(tier_of(rs, outcomes(A="met", B="met")), "standard")

    def test_one_basic_must_gap_is_below_lowest(self):
        rs = ruler([must("A"), must("B")])
        res = score(rs, outcomes(A="met", B="gap"), today=TODAY)
        self.assertIsNone(res.tier)
        self.assertEqual(res.units[0].checks[0].must_failed, ["B"])

    def test_cumulative_lower_tier_failure_blocks_higher(self):
        rs = ruler([must("A"), must("B", "standard")])
        self.assertIsNone(tier_of(rs, outcomes(A="gap", B="met")))

    def test_missing_outcome_is_unknown_and_counts_as_gap(self):
        rs = ruler([must("A")])
        res = score(rs, {}, today=TODAY)
        self.assertIsNone(res.tier)
        self.assertEqual(res.unknown, [("A", "repo")])

    def test_unknown_counts_as_gap_but_is_listed(self):
        rs = ruler([must("A")])
        res = score(rs, outcomes(A="unknown"), today=TODAY)
        self.assertIsNone(res.tier)
        self.assertEqual(res.unknown, [("A", "repo")])


class ShouldRuleTest(unittest.TestCase):
    CASES = [
        # (rule, n_should, n_met, reached)
        ({"rule": "ratio", "ratio": 0.8, "rounding": "floor"}, 5, 4, True),
        ({"rule": "ratio", "ratio": 0.8, "rounding": "floor"}, 5, 3, False),
        ({"rule": "ratio", "ratio": 0.8, "rounding": "floor"}, 3, 2, True),   # floor(2.4) = 2
        ({"rule": "ratio", "ratio": 0.8, "rounding": "floor"}, 3, 1, False),
        ({"rule": "ratio", "ratio": 0.8, "rounding": "ceil"}, 3, 3, True),    # ceil(2.4) = 3
        ({"rule": "ratio", "ratio": 0.8, "rounding": "ceil"}, 3, 2, False),
        ({"rule": "ratio", "ratio": 0.8, "rounding": "floor"}, 1, 0, True),   # floor(0.8) = 0
        ({"rule": "max_missing", "max_missing": 1}, 3, 2, True),
        ({"rule": "max_missing", "max_missing": 1}, 3, 1, False),
        ({"rule": "max_missing", "max_missing": 0}, 2, 1, False),
    ]

    def test_cases(self):
        for rule, n, met, reached in self.CASES:
            with self.subTest(rule=rule, n=n, met=met):
                rs = ruler([should("S%d" % i) for i in range(n)], should=rule)
                outs = outcomes(**{"S%d" % i: ("met" if i < met else "gap") for i in range(n)})
                self.assertEqual(tier_of(rs, outs) == "standard", reached)

    def test_required_count_is_reported(self):
        rs = ruler([should("S%d" % i) for i in range(5)])
        res = score(rs, outcomes(**{"S%d" % i: "gap" for i in range(5)}), today=TODAY)
        basic = res.units[0].checks[0]
        self.assertEqual((basic.should_applicable, basic.should_met, basic.should_required), (5, 0, 4))
        self.assertEqual(basic.should_failed, ["S0", "S1", "S2", "S3", "S4"])

    def test_per_tier_override(self):
        tiers = [{"id": "basic", "name": "B", "rank": 1},
                 {"id": "standard", "name": "S", "rank": 2, "should": {"rule": "max_missing", "max_missing": 1}}]
        rs = ruler([should("A", "standard"), should("B", "standard")], tiers=tiers,
                   should={"rule": "ratio", "ratio": 1.0})
        self.assertEqual(tier_of(rs, outcomes(A="met", B="gap")), "standard")
        self.assertEqual(tier_of(rs, outcomes(A="gap", B="gap")), "basic")

    def test_na_shoulds_leave_the_denominator(self):
        rs = ruler([should("A"), should("B"), should("C")], should={"rule": "ratio", "ratio": 1.0})
        self.assertEqual(tier_of(rs, outcomes(A="met", B="na", C="na")), "standard")
        self.assertIsNone(tier_of(rs, outcomes(A="gap", B="na", C="na")))


class LevelsTest(unittest.TestCase):
    def test_should_at_basic_must_at_standard(self):
        rs = ruler([clause("R2", ("basic", "should"), ("standard", "must"))], should={"rule": "max_missing", "max_missing": 1})
        self.assertEqual(tier_of(rs, outcomes(R2="gap")), "basic")
        self.assertEqual(tier_of(rs, outcomes(R2="met")), "standard")


class NaMajorityTest(unittest.TestCase):
    def test_more_than_half_na_is_not_reached(self):
        rs = ruler([must("A"), must("B"), must("C")])
        res = score(rs, outcomes(A="met", B="na", C="na"), today=TODAY)
        self.assertIsNone(res.tier)
        self.assertTrue(res.units[0].checks[0].na_majority)

    def test_exactly_half_is_fine(self):
        rs = ruler([must("A"), must("B")])
        self.assertEqual(tier_of(rs, outcomes(A="met", B="na")), "standard")

    def test_ignore_mode(self):
        rs = ruler([must("A"), must("B"), must("C")], na_majority="ignore")
        self.assertEqual(tier_of(rs, outcomes(A="met", B="na", C="na")), "standard")


class WaiverTest(unittest.TestCase):
    def waived(self, until):
        return Outcome("waived", waiver_until=until)

    def test_valid_waiver_counts_as_met(self):
        rs = ruler([must("A")])
        self.assertEqual(tier_of(rs, outcomes(A=self.waived(TODAY + datetime.timedelta(days=30)))), "standard")

    def test_waiver_ending_today_still_valid_yesterday_not(self):
        rs = ruler([must("A")])
        self.assertEqual(tier_of(rs, outcomes(A=self.waived(TODAY))), "standard")
        res = score(rs, outcomes(A=self.waived(TODAY - datetime.timedelta(days=1))), today=TODAY)
        self.assertIsNone(res.tier)
        self.assertEqual(res.invalid_waivers, [("A", "repo", "expired")])

    def test_non_waivable(self):
        rs = ruler([must("A")], non_waivable=["A"])
        res = score(rs, outcomes(A=self.waived(TODAY + datetime.timedelta(days=1))), today=TODAY)
        self.assertIsNone(res.tier)
        self.assertEqual(res.invalid_waivers, [("A", "repo", "not waivable")])

    def test_waiver_longer_than_max_days(self):
        rs = ruler([must("A")], max_days=90)
        self.assertEqual(tier_of(rs, outcomes(A=self.waived(TODAY + datetime.timedelta(days=90)))), "standard")
        res = score(rs, outcomes(A=self.waived(TODAY + datetime.timedelta(days=91))), today=TODAY)
        self.assertEqual(res.invalid_waivers, [("A", "repo", "longer than 90 days")])

    def test_waiver_without_end_date_is_invalid(self):
        rs = ruler([must("A")])
        res = score(rs, outcomes(A=Outcome("waived")), today=TODAY)
        self.assertEqual(res.invalid_waivers, [("A", "repo", "no end date")])


class EnforceFromTest(unittest.TestCase):
    def test_must_counts_as_should_before_enforce_date(self):
        rs = ruler([must("A", enforce_from="2026-11-20"), must("B")])
        res = score(rs, outcomes(A="gap", B="met"), today=TODAY)
        self.assertEqual(res.tier, "standard")  # A is a should for now; floor(0.8 * 1) = 0 needed
        self.assertEqual(res.units[0].checks[0].grace, ["A"])

    def test_must_enforced_on_the_date(self):
        rs = ruler([must("A", enforce_from="2026-11-19"), must("B")])
        self.assertIsNone(tier_of(rs, outcomes(A="gap", B="met")))


class LifecycleTest(unittest.TestCase):
    def test_future_and_obsolete_clauses_do_not_count(self):
        rs = ruler([must("A"), must("F", lifecycle="future"), must("O", lifecycle="obsolete")])
        res = score(rs, outcomes(A="met"), today=TODAY)
        self.assertEqual(res.tier, "standard")
        self.assertEqual(res.unknown, [])


class AppsTest(unittest.TestCase):
    def test_repo_tier_is_minimum_over_apps(self):
        rs = ruler([must("G"), must("P", "standard", scope="app")])
        outs = {("G", "repo"): Outcome("met"), ("P", "web"): Outcome("met"), ("P", "api"): Outcome("gap")}
        res = score(rs, outs, apps=["web", "api"], today=TODAY)
        self.assertEqual(res.tier, "basic")
        self.assertEqual({u.unit: u.tier for u in res.units}, {"web": "standard", "api": "basic"})

    def test_repo_scoped_failure_hits_every_app(self):
        rs = ruler([must("G"), must("P", scope="app")])
        outs = {("G", "repo"): Outcome("gap"), ("P", "web"): Outcome("met")}
        res = score(rs, outs, apps=["web"], today=TODAY)
        self.assertIsNone(res.tier)

    def test_app_scope_without_apps_is_judged_on_the_repo(self):
        rs = ruler([must("P", scope="app")])
        self.assertEqual(tier_of(rs, outcomes(P="met")), "standard")


class EmptyTierTest(unittest.TestCase):
    """Default: a tier without any effective must clause is not reached (fail closed)."""

    def test_tier_with_only_shoulds_is_not_reached_by_default(self):
        rs = ruler([must("A"), should("S", "standard")], empty_tier=None)
        res = score(rs, outcomes(A="met", S="met"), today=TODAY)
        self.assertEqual(res.tier, "basic")
        self.assertTrue(res.units[0].checks[1].empty)

    def test_future_only_tier_is_not_reached(self):
        rs = ruler([must("A"), must("F", "standard", lifecycle="future")], empty_tier=None)
        self.assertEqual(tier_of(rs, outcomes(A="met")), "basic")

    def test_must_in_grace_does_not_fill_a_tier(self):
        rs = ruler([must("A"), must("G", "standard", enforce_from="2027-01-01")], empty_tier=None)
        self.assertEqual(tier_of(rs, outcomes(A="met", G="met")), "basic")

    def test_all_na_musts_are_not_empty_but_hit_na_majority(self):
        rs = ruler([must("A"), must("B", "standard")], empty_tier=None)
        res = score(rs, outcomes(A="met", B="na"), today=TODAY)
        self.assertEqual(res.tier, "basic")
        chk = res.units[0].checks[1]
        self.assertFalse(chk.empty)
        self.assertTrue(chk.na_majority)

    def test_opt_in_reached(self):
        rs = ruler([must("A"), should("S", "standard")], empty_tier="reached")
        self.assertEqual(tier_of(rs, outcomes(A="met", S="met")), "standard")


class NextTierTest(unittest.TestCase):
    def test_next_tier_lists_what_is_missing(self):
        rs = ruler([must("A"), must("B", "standard"), should("C", "standard"), should("D", "standard")],
                   should={"rule": "max_missing", "max_missing": 0})
        res = score(rs, outcomes(A="met", B="gap", C="met", D="unknown"), today=TODAY)
        self.assertEqual(res.tier, "basic")
        nxt = res.next_tier
        self.assertEqual(nxt.tier, "standard")
        self.assertEqual(nxt.must_failed, ["B"])
        self.assertEqual(nxt.should_failed, ["D"])

    def test_no_next_tier_at_top(self):
        rs = ruler([must("A")])
        self.assertIsNone(score(rs, outcomes(A="met"), today=TODAY).next_tier)


if __name__ == "__main__":
    unittest.main()
