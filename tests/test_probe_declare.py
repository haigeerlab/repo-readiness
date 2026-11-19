"""T13: registration files (G7), owner registry (G7), risk template paths (R1), and self-assessment (declarations).

Declarations come from the repository's readiness.yml (the standard's self-assessment file). They can:
- back a `declare` probe (met with evidence / gap with plan);
- mark a clause n/a (only where the clause allows it, with reason + approved-by when required);
- waive a clause (reason + until + approved-by; expiry, max days and non-waivable are enforced by scoring).
"""

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from repo_readiness.probes.runtime import ProbeContext, evaluate

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
TEMPLATE = textwrap.dedent("""\
    version: 1
    common:
      T4_paths:
        - ".github/**"
        - "LICENSE"
      T3_paths:
        - "CLAUDE.md"
    categories:
      plugin:
        T4_paths:
          - "**/plugin.json"
          - "scripts/validate.sh"
        T2_paths:
          - "skills/**"
    """)


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def ev(self, expr, **ctx):
        return evaluate(expr, ProbeContext(repo_root=self.root, **ctx))


class ConfigParsesTest(Base):
    E = {"use": "config.parses", "with": {"path": ".github/autopr/interface.yml", "format": "yaml"}}

    def test_parses(self):
        write(self.root, ".github/autopr/interface.yml", "version: 1\nentries: {}\n")
        self.assertEqual(self.ev(self.E).status, "met")

    def test_missing_is_gap(self):
        r = self.ev(self.E)
        self.assertEqual(r.status, "gap")
        self.assertIn("not found", r.missing)

    def test_unparseable_is_gap_with_line(self):
        write(self.root, ".github/autopr/interface.yml", "a: &x 1\n")
        r = self.ev(self.E)
        self.assertEqual(r.status, "gap")
        self.assertIn("line 1", r.missing)

    def test_json(self):
        write(self.root, "x.json", "{\"a\": 1}")
        self.assertEqual(self.ev({"use": "config.parses", "with": {"path": "x.json", "format": "json"}}).status, "met")
        write(self.root, "x.json", "{nope")
        self.assertEqual(self.ev({"use": "config.parses", "with": {"path": "x.json", "format": "json"}}).status, "gap")


class OwnerRegisteredTest(Base):
    E = {"use": "registry.owner_registered", "with": {"path": ".github/autopr/readiness.yml", "key": "owner"}}

    def test_registered(self):
        write(self.root, ".github/autopr/readiness.yml", "owner: agent-relay-owner\n")
        r = self.ev(self.E, registry=frozenset({"agent-relay-owner", "x"}))
        self.assertEqual(r.status, "met")

    def test_not_registered(self):
        write(self.root, ".github/autopr/readiness.yml", "owner: ghost\n")
        r = self.ev(self.E, registry=frozenset({"agent-relay-owner"}))
        self.assertEqual(r.status, "gap")
        self.assertIn("ghost", r.missing)

    def test_no_registry_in_this_run_is_unknown(self):
        write(self.root, ".github/autopr/readiness.yml", "owner: agent-relay-owner\n")
        r = self.ev(self.E)
        self.assertEqual(r.status, "unknown")
        self.assertIn("--registry", r.error)

    def test_owner_missing_is_gap(self):
        write(self.root, ".github/autopr/readiness.yml", "category: plugin\n")
        self.assertEqual(self.ev(self.E, registry=frozenset({"a"})).status, "gap")


class RiskTemplateTest(Base):
    E = {"use": "risk.template_paths_kept", "with": {"path": ".github/autopr/risk-tiers.yml"}}

    def ctx(self):
        return {"risk_templates": __import__("repo_readiness.yamlsub", fromlist=["loads"]).loads(TEMPLATE)}

    def test_kept(self):
        write(self.root, ".github/autopr/risk-tiers.yml", "extends: plugin\nT4_paths:\n  - \"release/**\"\nT1_paths:\n  - \"tests/**\"\n")
        r = self.ev(self.E, **self.ctx())
        self.assertEqual(r.status, "met", r)

    def test_template_t4_path_downgraded_is_gap(self):
        write(self.root, ".github/autopr/risk-tiers.yml", "extends: plugin\nT1_paths:\n  - \"scripts/validate.sh\"\n")
        r = self.ev(self.E, **self.ctx())
        self.assertEqual(r.status, "gap")
        self.assertIn("scripts/validate.sh", r.missing)

    def test_common_t4_path_downgraded_is_gap(self):
        write(self.root, ".github/autopr/risk-tiers.yml", "extends: plugin\nT2_paths: [\".github/**\"]\n")
        self.assertEqual(self.ev(self.E, **self.ctx()).status, "gap")

    def test_unknown_category_is_gap(self):
        write(self.root, ".github/autopr/risk-tiers.yml", "extends: backend\n")
        r = self.ev(self.E, **self.ctx())
        self.assertEqual(r.status, "gap")
        self.assertIn("backend", r.missing)

    def test_no_template_is_unknown(self):
        write(self.root, ".github/autopr/risk-tiers.yml", "extends: plugin\n")
        r = self.ev(self.E)
        self.assertEqual(r.status, "unknown")
        self.assertIn("--risk-templates", r.error)

    def test_missing_file_is_gap(self):
        self.assertEqual(self.ev(self.E, **self.ctx()).status, "gap")


RULER = {
    "schema": "repo-readiness.clauses/v1", "id": "d", "version": "1.0.0", "kind": "base", "owner": "x",
    "categories": ["plugin", "frontend"],
    "tiers": [{"id": "basic", "name": "基础档", "rank": 1, "trust_cap": "L2"}],
    "below_lowest": {"name": "未达标", "trust_cap": "L0"},
    "gate": {"should": {"rule": "ratio", "ratio": 0.8}},
    "waiver": {"max_days": 90, "non_waivable": ["SAFE"]},
    "clauses": [
        {"id": "DECL", "requirement": "rollback path written", "guards": "g", "levels": [{"tier": "basic", "strength": "must"}],
         "scope": "repo", "applies": {"categories": "*"}, "method": "declare",
         "probe": {"use": "declare", "with": {"key": "DECL"}}},
        {"id": "AUTO", "requirement": "LICENSE", "guards": "g", "levels": [{"tier": "basic", "strength": "must"}],
         "scope": "repo", "applies": {"categories": "*"}, "method": "auto",
         "probe": {"use": "fs.exists", "with": {"path": "LICENSE"}}},
        {"id": "SAFE", "requirement": "SECURITY.md", "guards": "g", "levels": [{"tier": "basic", "strength": "must"}],
         "scope": "repo", "applies": {"categories": "*"}, "method": "auto", "na_allowed": False,
         "probe": {"use": "fs.exists", "with": {"path": "SECURITY.md"}}},
        {"id": "LOOSE", "requirement": "lockfile", "guards": "g", "levels": [{"tier": "basic", "strength": "must"}],
         "scope": "repo", "applies": {"categories": "*"}, "method": "auto", "na_justification_required": False,
         "probe": {"use": "fs.exists", "with": {"path": "package-lock.json"}}},
    ],
}


class DeclarationsE2ETest(Base):
    """Through `check`, so the engine's handling of n/a and waivers is exercised end to end."""

    def check(self, readiness, *extra):
        ruler = self.root / "ruler.json"
        ruler.write_text(json.dumps(RULER), encoding="utf-8")
        repo = self.root / "repo"
        write(repo, ".github/autopr/readiness.yml", readiness)
        out = self.root / "out"
        p = subprocess.run([str(ROOT / "bin" / "repo-readiness"), "check", str(repo), "--clauses", str(ruler),
                            "--out", str(out), "--as-of", "2026-11-20", *extra],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertIn(p.returncode, (0, 1), p.stderr)
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        return {r["clause"]: r for r in report["results"]}, report

    def test_declare_met_and_gap(self):
        res, _ = self.check("category: plugin\nbasic:\n  DECL: { status: met, evidence: \"docs/rollback.md\" }\n")
        self.assertEqual(res["DECL"]["status"], "met")
        self.assertIn("docs/rollback.md", " ".join(res["DECL"]["evidence"]))
        res, _ = self.check("category: plugin\nbasic:\n  DECL: { status: gap, plan: \"write it next week\" }\n")
        self.assertEqual(res["DECL"]["status"], "gap")
        self.assertIn("write it next week", res["DECL"]["missing"])

    def test_met_without_evidence_is_gap(self):
        res, _ = self.check("category: plugin\nbasic:\n  DECL: { status: met }\n")
        self.assertEqual(res["DECL"]["status"], "gap")
        self.assertIn("without evidence", res["DECL"]["missing"])

    def test_undeclared_is_gap(self):
        res, _ = self.check("category: plugin\n")
        self.assertEqual(res["DECL"]["status"], "gap")
        self.assertIn("DECL", res["DECL"]["missing"])

    def test_category_and_sections_come_from_readiness(self):
        _, report = self.check("category: frontend\ngeneral:\n  AUTO: { status: met }\n")
        self.assertEqual(report["category"], "frontend")

    def test_na_with_reason_and_approval(self):
        res, _ = self.check('category: plugin\nbasic:\n  AUTO: { status: na, reason: "no files to license", approved-by: "user" }\n')
        self.assertEqual(res["AUTO"]["status"], "na")

    def test_na_without_approval_is_gap(self):
        res, _ = self.check('category: plugin\nbasic:\n  AUTO: { status: na, reason: "nothing to license" }\n')
        self.assertEqual(res["AUTO"]["status"], "gap")
        self.assertIn("approved-by", res["AUTO"]["missing"])

    def test_na_not_allowed(self):
        res, _ = self.check('category: plugin\ngeneral:\n  SAFE: { status: na, reason: "r", approved-by: "user" }\n')
        self.assertEqual(res["SAFE"]["status"], "gap")
        self.assertIn("N/A is not allowed", res["SAFE"]["missing"])

    def test_na_without_justification_where_not_required(self):
        res, _ = self.check("category: plugin\nbasic:\n  LOOSE: { status: na }\n")
        self.assertEqual(res["LOOSE"]["status"], "na")

    def test_a_met_probe_wins_over_a_stale_declaration(self):
        write(self.root / "repo", "LICENSE", "MIT")
        res, _ = self.check('category: plugin\nbasic:\n  AUTO: { status: na, reason: "r", approved-by: "u" }\n')
        self.assertEqual(res["AUTO"]["status"], "met")

    def test_waiver(self):
        res, report = self.check('category: plugin\nbasic:\n  AUTO: { status: waived, reason: "r", until: 2027-01-31, approved-by: "u" }\n')
        self.assertEqual(res["AUTO"]["status"], "waived")
        self.assertEqual(res["AUTO"]["waiver_until"], "2027-01-31")
        self.assertEqual(report["invalid_waivers"], [])

    def test_waiver_beyond_90_days_is_invalid(self):
        _, report = self.check('category: plugin\nbasic:\n  AUTO: { status: waived, reason: "r", until: 2027-06-30, approved-by: "u" }\n')
        self.assertEqual(report["invalid_waivers"], [{"clause": "AUTO", "target": "repo", "reason": "longer than 90 days"}])

    def test_non_waivable(self):
        _, report = self.check('category: plugin\ngeneral:\n  SAFE: { status: waived, reason: "r", until: 2026-12-01, approved-by: "u" }\n')
        self.assertEqual(report["invalid_waivers"][0]["reason"], "not waivable")

    def test_incomplete_waiver_is_gap(self):
        res, _ = self.check("category: plugin\nbasic:\n  AUTO: { status: waived, until: 2026-12-01 }\n")
        self.assertEqual(res["AUTO"]["status"], "gap")
        self.assertIn("reason", res["AUTO"]["missing"])

    def test_bad_status_is_reported(self):
        res, _ = self.check("category: plugin\nbasic:\n  DECL: { status: maybe }\n")
        self.assertEqual(res["DECL"]["status"], "gap")
        self.assertIn("maybe", res["DECL"]["missing"])

    def test_unreadable_readiness_makes_declarations_unknown(self):
        res, report = self.check("category: plugin\nbasic: &a\n  DECL: { status: met }\n", "--category", "plugin")
        self.assertEqual(res["DECL"]["status"], "unknown")
        self.assertTrue(any("readiness.yml" in e["message"] for e in report["errors"]))

    def test_real_template_parses_as_a_declaration(self):
        src = (FIX / "yaml" / "readiness.example.v2.yml").read_text(encoding="utf-8")
        res, report = self.check(src)
        self.assertEqual(report["category"], "plugin")


if __name__ == "__main__":
    unittest.main()
