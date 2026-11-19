"""T17: the agent-judgment handoff (stage 2 of detect).

check  -> judgment_requests (+ judgment-requests.json) for declare-then-judge clauses whose declaration holds up
agent  -> judgments.json: one verdict per request, bound to the request's fingerprint, citing a real file
check --judgments    -> verdicts applied (source "judge"); anything off-request or unverifiable is rejected
check --baseline OLD -> unchanged evidence keeps the previous verdict (source "carried-over")
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULER = {
    "schema": "repo-readiness.clauses/v1", "id": "j", "version": "1.0.0", "kind": "base", "owner": "x",
    "tiers": [{"id": "basic", "name": "基础档", "rank": 1, "trust_cap": "L2"}],
    "below_lowest": {"name": "未达标", "trust_cap": "L0"},
    "gate": {"should": {"rule": "ratio", "ratio": 0.8}},
    "clauses": [
        {"id": "J", "requirement": "rollback path written down", "guards": "g",
         "levels": [{"tier": "basic", "strength": "must"}], "scope": "repo", "applies": {"categories": "*"},
         "method": "declare",
         "probe": {"use": "declare", "with": {"key": "J"}, "then": {"use": "judge", "with": {"question": "steps, owner, time?"}}}},
        {"id": "AUTO", "requirement": "README", "guards": "g", "levels": [{"tier": "basic", "strength": "must"}],
         "scope": "repo", "applies": {"categories": "*"}, "method": "auto",
         "probe": {"use": "fs.exists", "with": {"path": "README.md"}}},
    ],
}
READINESS = 'category: plugin\nbasic:\n  J: { status: met, evidence: "docs/rollback.md:2" }\n'


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        for rel, text in {"README.md": "x\n", "docs/rollback.md": "# Rollback\nrevert the merge, retag, ~10 min\n",
                          ".github/autopr/readiness.yml": READINESS}.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        self.ruler = self.tmp / "ruler.json"
        self.ruler.write_text(json.dumps(RULER), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def cli(self, *args):
        return subprocess.run([str(ROOT / "bin" / "repo-readiness"), *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)

    def check(self, name, *extra):
        out = self.tmp / name
        p = self.cli("check", str(self.repo), "--clauses", str(self.ruler), "--out", str(out), "--as-of", "2026-11-20", *extra)
        report = json.loads((out / "report.json").read_text(encoding="utf-8")) if (out / "report.json").exists() else None
        return p, report, out

    def j(self, report):
        return next(r for r in report["results"] if r["clause"] == "J")

    def judgments(self, *items):
        f = self.tmp / ("judgments-%d.json" % len(list(self.tmp.glob("judgments-*"))))
        f.write_text(json.dumps({"schema": "repo-readiness.judgments/v1", "judgments": list(items)}), encoding="utf-8")
        return str(f)

    def verdict(self, request, status="met", evidence="docs/rollback.md:2 lists the revert steps and who runs them", **kw):
        v = {"clause": request["clause"], "target": request["target"], "fingerprint": request["fingerprint"],
             "status": status, "evidence": evidence}
        v.update(kw)
        return v

    # ---- stage 1: requests

    def test_pending_request_is_emitted(self):
        p, report, out = self.check("a")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.j(report)["status"], "unknown")
        (req,) = report["judgment_requests"]
        self.assertEqual((req["clause"], req["target"]), ("J", "repo"))
        self.assertEqual(req["question"], "steps, owner, time?")
        self.assertEqual(req["requirement"], "rollback path written down")
        self.assertIn("docs/rollback.md:2", " ".join(req["evidence"]))
        self.assertRegex(req["fingerprint"], "^[0-9a-f]{64}$")
        on_disk = json.loads((out / "judgment-requests.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["requests"], report["judgment_requests"])
        self.assertEqual(report["errors"], [])
        self.assertIn("待裁决", (out / "summary.md").read_text(encoding="utf-8"))
        c = self.cli("conclude", str(out / "report.json"), "--default-branch", "main", "--repo-name", "a/b",
                     "--out", str(self.tmp / "c.json"))
        self.assertEqual(c.returncode, 1)  # pending judgments block a conclusion

    def test_no_request_when_the_declaration_already_fails(self):
        (self.repo / ".github/autopr/readiness.yml").write_text('basic:\n  J: { status: gap, plan: "later" }\n',
                                                                 encoding="utf-8")
        _, report, _ = self.check("a")
        self.assertEqual(self.j(report)["status"], "gap")
        self.assertEqual(report["judgment_requests"], [])

    # ---- stage 2: verdicts

    def test_valid_verdicts_are_applied(self):
        _, first, _ = self.check("a")
        req = first["judgment_requests"][0]
        for status in ("met", "gap"):
            with self.subTest(status=status):
                _, report, out = self.check("b-" + status, "--judgments", self.judgments(self.verdict(req, status)))
                r = self.j(report)
                self.assertEqual((r["status"], r["source"]), (status, "judge"))
                self.assertIn("docs/rollback.md:2", " ".join(r["evidence"]))
                self.assertEqual(report["judgment_requests"], [])
                self.assertFalse((out / "judgment-requests.json").exists())

    def assertRejected(self, verdict, fragment):
        _, report, _ = self.check("r", "--judgments", self.judgments(verdict))
        self.assertEqual(self.j(report)["status"], "unknown")
        self.assertEqual(len(report["judgment_requests"]), 1)  # still pending
        self.assertTrue(any(fragment in e["message"] for e in report["errors"]), report["errors"])

    def test_verdict_for_an_unrequested_clause_is_rejected(self):
        _, first, _ = self.check("a")
        req = first["judgment_requests"][0]
        self.assertRejected(dict(self.verdict(req), clause="AUTO"), "was not requested")

    def test_stale_fingerprint_is_rejected(self):
        _, first, _ = self.check("a")
        self.assertRejected(dict(self.verdict(first["judgment_requests"][0]), fingerprint="0" * 64), "fingerprint")

    def test_citation_must_point_at_a_real_file_and_line(self):
        _, first, _ = self.check("a")
        req = first["judgment_requests"][0]
        self.assertRejected(self.verdict(req, evidence="see docs/nowhere.md:3"), "no cited file")
        self.assertRejected(self.verdict(req, evidence="docs/rollback.md:99 says so"), "line 99")
        self.assertRejected(self.verdict(req, evidence="looks fine to me"), "no cited file")

    def test_malformed_judgments_file_is_a_usage_error(self):
        f = self.tmp / "bad.json"
        f.write_text(json.dumps({"schema": "repo-readiness.judgments/v1",
                                 "judgments": [{"clause": "J", "status": "maybe"}]}), encoding="utf-8")
        p, _, _ = self.check("bad", "--judgments", str(f))
        self.assertEqual(p.returncode, 2)

    # ---- baseline carry-over

    def test_unchanged_evidence_carries_the_previous_verdict(self):
        _, first, _ = self.check("a")
        _, judged, out = self.check("b", "--judgments", self.judgments(self.verdict(first["judgment_requests"][0])))
        _, again, _ = self.check("c", "--baseline", str(out / "report.json"))
        r = self.j(again)
        self.assertEqual((r["status"], r["source"]), ("met", "carried-over"))
        self.assertEqual(again["judgment_requests"], [])
        self.assertRegex(again["baseline"], "^[0-9a-f]{64}$")

    def test_changed_evidence_asks_again(self):
        _, first, _ = self.check("a")
        _, judged, out = self.check("b", "--judgments", self.judgments(self.verdict(first["judgment_requests"][0])))
        (self.repo / ".github/autopr/readiness.yml").write_text(READINESS.replace(":2", ":1"), encoding="utf-8")
        _, again, _ = self.check("c", "--baseline", str(out / "report.json"))
        self.assertEqual(self.j(again)["status"], "unknown")
        self.assertEqual(len(again["judgment_requests"]), 1)


if __name__ == "__main__":
    unittest.main()
