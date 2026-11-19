"""T18: recheck. Failure streaks across baseline reports, `diff OLD NEW`, and drop signals.

Drop rule (ruler `drop`, agreed with autopr-standard #21609 and autopr-design #21530):
- a must clause at or below the old tier that is not met `consecutive_failures` times in a row -> drop one tier;
- a clause in `immediate` drops on its first failure;
- unknown neither counts nor resets ("drop only on not met");
- new clauses get their grace through enforce_from (counted as should until then), so they do not signal;
- "one tier down" is from the tier the repository holds (held_tier), which a single failure does not lower.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def ruler(version="1.0.0", extra_clauses=(), drop=True):
    data = {
        "schema": "repo-readiness.clauses/v1", "id": "r", "version": version, "kind": "base", "owner": "x",
        "tiers": [{"id": "basic", "name": "基础档", "rank": 1, "trust_cap": "L2"},
                  {"id": "standard", "name": "标准档", "rank": 2, "trust_cap": "L3"}],
        "below_lowest": {"name": "未达标", "trust_cap": "L0"},
        "gate": {"should": {"rule": "max_missing", "max_missing": 0}},
        "waiver": {"max_days": 90, "non_waivable": ["SAFE"]},
        "clauses": [
            {"id": "A", "requirement": "A.txt", "guards": "g", "levels": [{"tier": "basic", "strength": "must"}],
             "scope": "repo", "applies": {"categories": "*"}, "method": "auto", "probe": {"use": "fs.exists", "with": {"path": "A.txt"}}},
            {"id": "SAFE", "requirement": "SAFE.txt", "guards": "g", "levels": [{"tier": "basic", "strength": "must"}],
             "scope": "repo", "applies": {"categories": "*"}, "method": "auto", "probe": {"use": "fs.exists", "with": {"path": "SAFE.txt"}}},
            {"id": "S", "requirement": "S.txt", "guards": "g", "levels": [{"tier": "standard", "strength": "must"}],
             "scope": "repo", "applies": {"categories": "*"}, "method": "auto", "probe": {"use": "fs.exists", "with": {"path": "S.txt"}}},
        ] + list(extra_clauses),
    }
    if drop:
        data["drop"] = {"consecutive_failures": 2, "immediate": ["SAFE"]}
    return data


class RecheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        for f in ("A.txt", "SAFE.txt", "S.txt"):
            (self.repo / f).write_text("x", encoding="utf-8")
        self.n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def cli(self, *args):
        return subprocess.run([str(ROOT / "bin" / "repo-readiness"), *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)

    def check(self, baseline=None, rul=None, as_of="2026-11-20"):
        self.n += 1
        rf = self.tmp / ("ruler-%d.json" % self.n)
        rf.write_text(json.dumps(rul or ruler()), encoding="utf-8")
        out = self.tmp / ("out-%d" % self.n)
        args = ["check", str(self.repo), "--clauses", str(rf), "--out", str(out), "--as-of", as_of]
        if baseline:
            args += ["--baseline", str(baseline)]
        p = self.cli(*args)
        self.assertIn(p.returncode, (0, 1), p.stderr)
        return out / "report.json"

    def diff(self, old, new):
        p = self.cli("diff", str(old), str(new), "--json", str(self.tmp / "diff.json"))
        data = json.loads((self.tmp / "diff.json").read_text(encoding="utf-8")) if (self.tmp / "diff.json").exists() else None
        return p, data

    def streak(self, report, clause):
        data = json.loads(Path(report).read_text(encoding="utf-8"))
        for s in data.get("failure_streaks", []):
            if s["clause"] == clause:
                return s["count"]
        return 0

    # ---- streaks

    def test_streak_counts_consecutive_failures_across_baselines(self):
        r1 = self.check()
        (self.repo / "A.txt").unlink()
        r2 = self.check(baseline=r1)
        r3 = self.check(baseline=r2)
        self.assertEqual((self.streak(r2, "A"), self.streak(r3, "A")), (1, 2))
        (self.repo / "A.txt").write_text("x", encoding="utf-8")
        r4 = self.check(baseline=r3)
        self.assertEqual(self.streak(r4, "A"), 0)  # met resets

    def test_report_carries_the_drop_rule(self):
        data = json.loads(self.check().read_text(encoding="utf-8"))
        self.assertEqual(data["drop_rule"], {"consecutive_failures": 2, "immediate": ["SAFE"]})

    def test_default_drop_rule_when_the_ruler_has_none(self):
        data = json.loads(self.check(rul=ruler(drop=False)).read_text(encoding="utf-8"))
        self.assertEqual(data["drop_rule"], {"consecutive_failures": 2, "immediate": []})

    # ---- diff and drop signals

    def test_improvement(self):
        (self.repo / "S.txt").unlink()
        r1 = self.check()
        (self.repo / "S.txt").write_text("x", encoding="utf-8")
        r2 = self.check(baseline=r1)
        p, d = self.diff(r1, r2)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((d["tier"]["from"], d["tier"]["to"], d["tier"]["direction"]), ("basic", "standard", "up"))
        self.assertEqual(d["changes"], [{"clause": "S", "target": "repo", "from": "gap", "to": "met", "reason": "repo"}])
        self.assertEqual(d["drop_signals"], [])
        self.assertIn("S", p.stdout)

    def test_one_failure_is_not_yet_a_drop(self):
        r1 = self.check()
        (self.repo / "A.txt").unlink()
        r2 = self.check(baseline=r1)
        p, d = self.diff(r1, r2)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(d["drop_signals"], [])
        self.assertEqual(d["tier"]["direction"], "down")  # the computed tier fell, but the drop rule has not fired

    def test_two_consecutive_failures_signal_a_one_tier_drop(self):
        r1 = self.check()
        (self.repo / "A.txt").unlink()
        r2 = self.check(baseline=r1)
        r3 = self.check(baseline=r2)
        p, d = self.diff(r2, r3)
        self.assertEqual(p.returncode, 1)
        (sig,) = d["drop_signals"]
        self.assertEqual((sig["clause"], sig["rule"], sig["streak"]), ("A", "consecutive", 2))
        self.assertEqual((sig["from_tier"], sig["to_tier"]), ("standard", "basic"))  # one tier down from the old tier
        self.assertEqual(sig["to_trust_cap"], "L2")  # copied from the ruler (autopr-design #21678)

    def test_immediate_clause_drops_on_first_failure(self):
        r1 = self.check()
        (self.repo / "SAFE.txt").unlink()
        r2 = self.check(baseline=r1)
        p, d = self.diff(r1, r2)
        self.assertEqual(p.returncode, 1)
        self.assertEqual([(s["clause"], s["rule"]) for s in d["drop_signals"]], [("SAFE", "immediate")])

    def test_dropping_below_the_lowest_tier_uses_the_rulers_below_lowest_cap(self):
        (self.repo / "S.txt").unlink()
        r1 = self.check()  # held basic
        (self.repo / "SAFE.txt").unlink()
        r2 = self.check(baseline=r1)
        _, d = self.diff(r1, r2)
        (sig,) = d["drop_signals"]
        self.assertEqual((sig["from_tier"], sig["to_tier"], sig["to_trust_cap"]), ("basic", None, "L0"))

    def test_failure_above_the_old_tier_never_signals(self):
        (self.repo / "S.txt").unlink()
        r1 = self.check()  # tier basic: S (standard) already failing
        r2 = self.check(baseline=r1)
        r3 = self.check(baseline=r2)
        _, d = self.diff(r2, r3)
        self.assertEqual(d["drop_signals"], [])

    def test_unknown_neither_counts_nor_resets(self):
        r1 = self.check()
        (self.repo / "A.txt").unlink()
        r2 = self.check(baseline=r1)  # streak 1
        (self.repo / "A.txt").symlink_to("/etc/hosts")  # resolves outside the repo -> unknown
        r3 = self.check(baseline=r2)
        self.assertEqual(self.streak(r3, "A"), 1)
        _, d = self.diff(r2, r3)
        self.assertEqual(d["changes"], [{"clause": "A", "target": "repo", "from": "gap", "to": "unknown",
                                         "reason": "environment"}])
        self.assertEqual(d["drop_signals"], [])

    def test_ruler_change_is_kept_apart_from_repo_regressions(self):
        r1 = self.check()
        new_clause = {"id": "NEW", "requirement": "NEW.txt", "guards": "g", "levels": [{"tier": "basic", "strength": "must"}],
                      "scope": "repo", "applies": {"categories": "*"}, "method": "auto",
                      "probe": {"use": "fs.exists", "with": {"path": "NEW.txt"}}}
        new_clause["enforce_from"] = "2026-12-20"  # the standard's 30-day grace for new clauses
        r2 = self.check(baseline=r1, rul=ruler(version="1.1.0", extra_clauses=[new_clause]))
        r3 = self.check(baseline=r2, rul=ruler(version="1.1.0", extra_clauses=[new_clause]))
        _, d = self.diff(r1, r2)
        self.assertTrue(d["ruler_changed"])
        self.assertEqual(d["changes"], [{"clause": "NEW", "target": "repo", "from": None, "to": "gap", "reason": "ruler"}])
        self.assertEqual(d["tier"]["reasons"], ["ruler"])
        _, d = self.diff(r2, r3)
        self.assertEqual(d["drop_signals"], [])  # within enforce_from grace it counts as a should: no drop

    def test_held_tier_survives_one_failure_then_drops_one_tier(self):
        r1 = self.check()
        held = lambda r: json.loads(Path(r).read_text(encoding="utf-8"))["held_tier"]
        (self.repo / "A.txt").unlink()
        r2 = self.check(baseline=r1)
        r3 = self.check(baseline=r2)
        self.assertEqual((held(r1), held(r2), held(r3)), ("standard", "standard", "basic"))

    def test_expired_waiver_is_named(self):
        rul = ruler()
        (self.repo / "A.txt").unlink()
        (self.repo / ".github" / "autopr").mkdir(parents=True)
        (self.repo / ".github" / "autopr" / "readiness.yml").write_text(
            'basic:\n  A: { status: waived, reason: "r", until: 2026-11-30, approved-by: "u" }\n', encoding="utf-8")
        r1 = self.check(rul=rul)
        r2 = self.check(baseline=r1, rul=rul, as_of="2026-12-01")
        _, d = self.diff(r1, r2)
        self.assertEqual(d["changes"], [{"clause": "A", "target": "repo", "from": "waived", "to": "waived",
                                         "reason": "waiver-expired"}])
        self.assertIn("waiver-expired", d["tier"]["reasons"])

    def test_usage_errors(self):
        bad = self.tmp / "x.json"
        bad.write_text("{}", encoding="utf-8")
        self.assertEqual(self.cli("diff", str(bad), str(bad)).returncode, 2)
        self.assertEqual(self.cli("diff", str(self.tmp / "nope"), str(bad)).returncode, 2)

    def test_lint_checks_immediate_ids(self):
        rul = ruler()
        rul["drop"]["immediate"] = ["GHOST"]
        rf = self.tmp / "bad-ruler.json"
        rf.write_text(json.dumps(rul), encoding="utf-8")
        p = self.cli("clauses", "lint", str(rf))
        self.assertEqual(p.returncode, 2)
        self.assertIn("drop.immediate", p.stderr)


if __name__ == "__main__":
    unittest.main()
