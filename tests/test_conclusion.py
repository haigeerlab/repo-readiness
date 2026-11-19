import copy
import datetime
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from repo_readiness.conclusion import ConclusionError, conclude, verify
from repo_readiness.resources import schema_validator

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime.datetime(2026, 11, 19, 12, 0, 0, tzinfo=datetime.timezone.utc)
SHA = "c" * 40
TOOL_SHA = "d" * 40


def base_report(tier_id="basic", name="基础档", cap="L2"):
    return {
        "schema": "repo-readiness.report/v1",
        "tool": {"name": "repo-readiness", "version": "0.1.0", "commit": TOOL_SHA, "dirty": False},
        "generated_at": "2026-11-19T11:59:00Z", "as_of": "2026-11-19",
        "repo": {"path": "/tmp/r", "name": "haigeerlab/agent-relay", "head": SHA},
        "rulesets": [{"id": "toy", "kind": "base", "version": "1.0.0", "sha256": "e" * 64}],
        "category": "plugin",
        "apps": [],
        "tier": {"id": tier_id, "name": name, "trust_cap": cap},
        "next_tier": None,
        "units": [{"unit": "repo", "tier": tier_id, "checks": []}],
        "results": [], "unknown": [], "invalid_waivers": [], "not_evaluated": [], "errors": [],
        "judgment_requests": [], "baseline": None,
    }


def dumped(report):
    return json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")


class ConcludeTest(unittest.TestCase):
    def test_basic_conclusion(self):
        raw = dumped(base_report())
        c = conclude(raw, default_branch="main", now=NOW)
        self.assertEqual(schema_validator("conclusion.v1").errors(c), [])
        self.assertEqual((c["repo"], c["head"], c["default_branch"]), ("haigeerlab/agent-relay", SHA, "main"))
        self.assertEqual(c["tier"], {"id": "basic", "name": "基础档"})
        self.assertEqual(c["trust_cap"], "L2")
        self.assertEqual(c["basis"]["report_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(c["basis"]["tool"], {"version": "0.1.0", "commit": TOOL_SHA})
        self.assertEqual(c["issued_at"], "2026-11-19T12:00:00Z")
        self.assertEqual(c["valid_until"], "2026-12-03T12:00:00Z")  # 14 days
        self.assertEqual(c["attestation"], {"method": "none"})

    def test_below_lowest_tier_still_concludes_l0(self):
        c = conclude(dumped(base_report(tier_id=None, name="未达标", cap="L0")), default_branch="main", now=NOW)
        self.assertEqual((c["tier"]["id"], c["trust_cap"]), (None, "L0"))

    def test_apps_carry_their_own_caps(self):
        r = base_report()
        r["apps"] = [{"id": "web", "root": "apps/web", "paths": ["apps/web/**", "packages/web/**"],
                      "tier": "standard", "trust_cap": "L3"},
                     {"id": "api", "root": "apps/api", "paths": ["apps/api/**"], "tier": None, "trust_cap": "L0"}]
        c = conclude(dumped(r), default_branch="main", now=NOW)
        # The conclusion carries paths (file -> app mapping for admission), not root.
        self.assertEqual(c["apps"], [{"id": "web", "paths": ["apps/web/**", "packages/web/**"],
                                      "tier": "standard", "trust_cap": "L3"},
                                     {"id": "api", "paths": ["apps/api/**"], "tier": None, "trust_cap": "L0"}])
        self.assertEqual(verify(c, dumped(r), now=NOW), [])
        tampered = copy.deepcopy(c)
        tampered["apps"][0]["paths"] = ["apps/web/**"]
        self.assertTrue(any("apps" in p for p in verify(tampered, dumped(r), now=NOW)))

    def assertRefused(self, report, fragment, **kw):
        with self.assertRaises(ConclusionError) as cm:
            conclude(dumped(report), default_branch=kw.pop("default_branch", "main"), now=NOW, **kw)
        self.assertTrue(any(fragment in p for p in cm.exception.problems), cm.exception.problems)

    def test_refuses_incomplete_reports(self):
        r = base_report()
        r["errors"] = [{"clause": "G2", "target": "repo", "message": "boom"}]
        self.assertRefused(r, "probe error")
        r = base_report()
        r["judgment_requests"] = [{"clause": "R1"}]
        self.assertRefused(r, "judgment")

    def test_refuses_without_identity(self):
        r = base_report()
        r["repo"]["head"] = None
        self.assertRefused(r, "head")
        r = base_report()
        r["repo"]["name"] = None
        self.assertRefused(r, "repo name")

    def test_repo_name_can_be_supplied(self):
        r = base_report()
        r["repo"]["name"] = None
        c = conclude(dumped(r), default_branch="main", now=NOW, repo_name="haigeerlab/x")
        self.assertEqual(c["repo"], "haigeerlab/x")

    def test_refuses_dirty_or_uncommitted_tool(self):
        r = base_report()
        r["tool"]["dirty"] = True
        self.assertRefused(r, "uncommitted")
        r = base_report()
        r["tool"]["commit"] = None
        r["tool"]["dirty"] = None
        self.assertRefused(r, "commit")

    def test_refuses_invalid_report(self):
        r = base_report()
        del r["results"]
        self.assertRefused(r, "report.v1")

    def test_refuses_empty_default_branch(self):
        self.assertRefused(base_report(), "default branch", default_branch="")


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.raw = dumped(base_report())
        self.c = conclude(self.raw, default_branch="main", now=NOW)

    def test_matching_pair_verifies(self):
        self.assertEqual(verify(self.c, self.raw, now=NOW), [])

    def test_report_changed_by_one_byte(self):
        tampered = self.raw.replace(b'"L2"', b'"L3"')
        self.assertTrue(any("sha256" in p for p in verify(self.c, tampered, now=NOW)))

    def test_conclusion_edited(self):
        c = copy.deepcopy(self.c)
        c["trust_cap"] = "L4"
        self.assertTrue(any("trust_cap" in p for p in verify(c, self.raw, now=NOW)))

    def test_expired(self):
        later = NOW + datetime.timedelta(days=15)
        self.assertTrue(any("expired" in p for p in verify(self.c, self.raw, now=later)))

    def test_schema_violation(self):
        c = copy.deepcopy(self.c)
        c["head"] = "nope"
        self.assertTrue(any("conclusion.v1" in p for p in verify(c, self.raw, now=NOW)))


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([str(ROOT / "bin" / "repo-readiness"), *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)

    def test_conclude_and_verify_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "report.json").write_bytes(dumped(base_report()))
            p = self.run_cli("conclude", str(d / "report.json"), "--default-branch", "main",
                             "--out", str(d / "conclusion.json"), "--now", "2026-11-19T12:00:00Z")
            self.assertEqual(p.returncode, 0, p.stderr)
            p = self.run_cli("conclusion", "verify", str(d / "conclusion.json"), "--report", str(d / "report.json"),
                             "--now", "2026-11-20T00:00:00Z")
            self.assertEqual(p.returncode, 0, p.stderr)
            p = self.run_cli("conclusion", "verify", str(d / "conclusion.json"), "--report", str(d / "report.json"),
                             "--now", "2026-12-04T00:00:00Z")
            self.assertEqual(p.returncode, 1)
            self.assertIn("expired", p.stderr)

    def test_incomplete_report_exits_one(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            r = base_report()
            r["errors"] = [{"clause": "G2", "target": "repo", "message": "boom"}]
            (d / "report.json").write_bytes(dumped(r))
            p = self.run_cli("conclude", str(d / "report.json"), "--default-branch", "main",
                             "--out", str(d / "conclusion.json"))
            self.assertEqual(p.returncode, 1)
            self.assertFalse((d / "conclusion.json").exists())


if __name__ == "__main__":
    unittest.main()
