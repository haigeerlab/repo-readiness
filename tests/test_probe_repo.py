"""G4 main CI green within 336 h, G5 secret scanning + push protection, G6 workflow token settings.

Real recordings (read-only GET, 2026-11-20 UTC) for pwa-platform, agent-relay, repo-readiness;
constructed cases change one field of a real recording.
"""

import copy
import datetime
import tempfile
import unittest
from pathlib import Path

from repo_readiness.platform.github import GhResponse, GitHub, ReplayTransport
from repo_readiness.probes.runtime import ProbeContext, evaluate

FIX = Path(__file__).resolve().parent / "fixtures" / "github"
NOW = datetime.datetime(2026, 11, 20, 0, 0, tzinfo=datetime.timezone.utc)
G4 = {"use": "github.main_ci_green", "with": {"branch": "main", "max_age_hours": 336}}
G5 = {"use": "github.secret_scanning"}
G6 = {"use": "github.workflow_permissions"}


class Overrides:
    def __init__(self, repo, overrides):
        self.replay = ReplayTransport(FIX / repo)
        self.overrides = overrides

    def fetch(self, path):
        return self.overrides[path] if path in self.overrides else self.replay.fetch(path)


def run(expr, repo, overrides=None, now=NOW, root=Path("/")):
    ctx = ProbeContext(repo_root=root, github=GitHub(Overrides(repo, overrides or {})),
                       repo_name="haigeerlab/" + repo, now=now)
    return evaluate(expr, ctx)


def runs_path(repo):
    return "repos/haigeerlab/%s/actions/runs?branch=main&status=completed&per_page=30" % repo


def recorded(repo, path):
    return ReplayTransport(FIX / repo).fetch(path)


def with_runs(repo, edit):
    data = copy.deepcopy(recorded(repo, runs_path(repo)).data)
    edit(data["workflow_runs"])
    return {runs_path(repo): GhResponse("ok", 200, data)}


class MainCiGreenTest(unittest.TestCase):
    def test_real_recordings(self):
        self.assertEqual(run(G4, "pwa-platform").status, "met")
        r = run(G4, "agent-relay")
        self.assertEqual(r.status, "met", r)  # last main run 2026-11-16, inside 336 h
        self.assertIn("2026-11-16", " ".join(r.evidence))
        r = run(G4, "repo-readiness")
        self.assertEqual(r.status, "gap")
        self.assertIn("no completed", r.missing)

    def test_too_old(self):
        later = datetime.datetime(2026, 12, 1, 0, 0, tzinfo=datetime.timezone.utc)  # > 336 h after 11-16 10:50
        r = run(G4, "agent-relay", now=later)
        self.assertEqual(r.status, "gap")
        self.assertIn("336", r.missing)

    def test_boundary_is_rolling_hours_not_calendar_days(self):
        latest = datetime.datetime(2026, 11, 16, 10, 50, 36, tzinfo=datetime.timezone.utc)
        self.assertEqual(run(G4, "agent-relay", now=latest + datetime.timedelta(hours=336)).status, "met")
        self.assertEqual(run(G4, "agent-relay", now=latest + datetime.timedelta(hours=336, seconds=1)).status, "gap")

    def test_latest_failure_is_gap(self):
        def fail_first(runs):
            runs[0]["conclusion"] = "failure"
        r = run(G4, "pwa-platform", with_runs("pwa-platform", fail_first))
        self.assertEqual(r.status, "gap")
        self.assertIn("failure", r.missing)

    def test_cancelled_and_skipped_runs_are_not_a_verdict(self):
        def cancel_first(runs):
            runs[0]["conclusion"] = "cancelled"
            runs[1]["conclusion"] = "skipped"
        r = run(G4, "pwa-platform", with_runs("pwa-platform", cancel_first))
        self.assertEqual(r.status, "met")  # the third run decides

    def test_pull_request_runs_do_not_count(self):
        def all_pr(runs):
            for x in runs:
                x["event"] = "pull_request"
        self.assertEqual(run(G4, "pwa-platform", with_runs("pwa-platform", all_pr)).status, "gap")

    def test_unreadable_is_unknown(self):
        forbidden = GhResponse("forbidden", 403, {"message": "Must have admin rights"}, "Must have admin rights")
        self.assertEqual(run(G4, "pwa-platform", {runs_path("pwa-platform"): forbidden}).status, "unknown")


class SecretScanningTest(unittest.TestCase):
    def repo_with(self, repo, **ssa_changes):
        data = copy.deepcopy(recorded(repo, "repos/haigeerlab/" + repo).data)
        if ssa_changes.get("drop"):
            data.pop("security_and_analysis", None)
        else:
            for k, v in ssa_changes.items():
                data["security_and_analysis"][k] = {"status": v}
        return {"repos/haigeerlab/" + repo: GhResponse("ok", 200, data)}

    def test_real_recordings_are_met(self):
        for repo in ("pwa-platform", "agent-relay", "repo-readiness"):
            with self.subTest(repo=repo):
                self.assertEqual(run(G5, repo).status, "met")

    def test_push_protection_off_is_gap(self):
        r = run(G5, "agent-relay", self.repo_with("agent-relay", secret_scanning_push_protection="disabled"))
        self.assertEqual(r.status, "gap")
        self.assertIn("push protection", r.missing)

    def test_scanning_off_is_gap(self):
        self.assertEqual(run(G5, "agent-relay", self.repo_with("agent-relay", secret_scanning="disabled")).status, "gap")

    def test_not_reported_with_ci_is_unknown_with_ci_hint(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".github" / "workflows").mkdir(parents=True)
            (Path(d) / ".github" / "workflows" / "ci.yml").write_text("on: push\njobs: {}\n", encoding="utf-8")
            r = run(G5, "agent-relay", self.repo_with("agent-relay", drop=True), root=Path(d))
        self.assertEqual(r.status, "unknown")
        self.assertIn("CI", r.error)

    def test_not_reported_and_no_ci_at_all_is_gap(self):
        # ai-dev-playbook shape: private, the platform reports nothing, and there is no CI to hold an equivalent.
        with tempfile.TemporaryDirectory() as d:
            r = run(G5, "agent-relay", self.repo_with("agent-relay", drop=True), root=Path(d))
        self.assertEqual(r.status, "gap")
        self.assertIn("no CI", r.missing)

    def test_repository_not_on_github_is_gap(self):
        gone = GhResponse("not_found", 404, {"message": "Not Found"}, "Not Found")
        for expr in (G4, G5, G6):
            with self.subTest(probe=expr["use"]):
                self.assertEqual(run(expr, "agent-relay", {"repos/haigeerlab/agent-relay": gone}).status, "gap")


class WorkflowPermissionsTest(unittest.TestCase):
    PATH = "repos/haigeerlab/agent-relay/actions/permissions/workflow"

    def perms(self, **changes):
        data = dict(recorded("agent-relay", self.PATH).data, **changes)
        return {self.PATH: GhResponse("ok", 200, data)}

    def test_real_recordings_are_met(self):
        for repo in ("pwa-platform", "agent-relay", "repo-readiness"):
            with self.subTest(repo=repo):
                self.assertEqual(run(G6, repo).status, "met")

    def test_write_token_is_gap(self):
        r = run(G6, "agent-relay", self.perms(default_workflow_permissions="write"))
        self.assertEqual(r.status, "gap")
        self.assertIn("write", r.missing)

    def test_workflows_may_approve_is_gap(self):
        r = run(G6, "agent-relay", self.perms(can_approve_pull_request_reviews=True))
        self.assertEqual(r.status, "gap")
        self.assertIn("approve", r.missing)

    def test_unreadable_is_unknown(self):
        hidden = GhResponse("not_found", 404, {"message": "Not Found"}, "Not Found")
        self.assertEqual(run(G6, "agent-relay", {self.PATH: hidden}).status, "unknown")


if __name__ == "__main__":
    unittest.main()
