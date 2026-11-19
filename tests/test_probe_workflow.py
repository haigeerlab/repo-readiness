"""Workflow static analysis: G3 (PR CI runs the registered check), G6 (no dangerous triggers), G9 (actions pinned).

Real workflows (tests/fixtures/workflows, copied 2026-11-20) give the expected answers from
assessment-v2: G9 pinned in pwa-platform and agent-relay, tags in the other three; no dangerous triggers anywhere.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from repo_readiness.probes.runtime import ProbeContext, evaluate

FIX = Path(__file__).resolve().parent / "fixtures" / "workflows"
G3 = {"use": "workflow.pr_runs_check", "with": {"entry": "check"}}
G6 = {"use": "workflow.no_dangerous_triggers"}
G9 = {"use": "workflow.actions_pinned"}


class Repo:
    def __init__(self, workflows=None, interface=None):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        wf = self.root / ".github" / "workflows"
        wf.mkdir(parents=True)
        for name, content in (workflows or {}).items():
            (wf / name).write_text(content, encoding="utf-8")
        if interface is not None:
            (self.root / ".github" / "autopr").mkdir(parents=True)
            (self.root / ".github" / "autopr" / "interface.yml").write_text(interface, encoding="utf-8")

    def ev(self, expr):
        return evaluate(expr, ProbeContext(repo_root=self.root))

    def close(self):
        self._tmp.cleanup()


def real(name):
    return {"ci.yml": (FIX / ("%s.ci.yml" % name)).read_text(encoding="utf-8")}


def interface(check_run):
    return 'version: 1\nentries:\n  check:\n    run: "%s"\n    report: wrapped\n' % check_run


class Base(unittest.TestCase):
    def repo(self, *a, **kw):
        r = Repo(*a, **kw)
        self.addCleanup(r.close)
        return r


class PinnedTest(Base):
    def test_real_workflows(self):
        expected = {"pwa-platform": ("met", []), "agent-relay": ("met", []),
                    "spec-guard-plugin": ("gap", ["actions/checkout@v7"]),
                    "tab-leader": ("gap", ["actions/checkout@v7", "pnpm/action-setup@v6", "actions/setup-node@v7",
                                           "actions/upload-artifact@v7"]),
                    "sso-browser-sdk": ("gap", ["actions/checkout@v7", "actions/setup-node@v7",
                                                "actions/setup-python@v7", "actions/setup-java@v6"])}
        for name, (status, unpinned) in expected.items():
            with self.subTest(repo=name):
                r = self.repo(real(name)).ev(G9)
                self.assertEqual(r.status, status, r)
                for u in unpinned:
                    self.assertIn(u, r.missing)

    def test_local_and_digest_references_are_fine(self):
        wf = ("on: push\njobs:\n  a:\n    uses: ./.github/workflows/reuse.yml\n  b:\n    runs-on: x\n    steps:\n"
              "      - uses: ./actions/local\n      - uses: docker://alpine@sha256:%s\n" % ("a" * 64))
        self.assertEqual(self.repo({"ci.yml": wf}).ev(G9).status, "met")

    def test_reusable_workflow_from_another_repo_must_be_pinned(self):
        wf = "on: push\njobs:\n  a:\n    uses: org/hub/.github/workflows/x.yml@main\n"
        r = self.repo({"ci.yml": wf}).ev(G9)
        self.assertEqual(r.status, "gap")
        self.assertIn("org/hub/.github/workflows/x.yml@main", r.missing)

    def test_short_sha_is_not_pinned(self):
        wf = "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: actions/checkout@1234567\n"
        self.assertEqual(self.repo({"ci.yml": wf}).ev(G9).status, "gap")

    def test_unreadable_workflow_is_unknown_not_skipped(self):
        files = dict(real("agent-relay"), **{"bad.yml": "on: push\njobs: &x\n  a: 1\n"})
        r = self.repo(files).ev(G9)
        self.assertEqual(r.status, "unknown")
        self.assertIn("bad.yml", r.error)

    def test_no_workflows_is_met_with_note(self):
        r = self.repo({}).ev(G9)
        self.assertEqual(r.status, "met")
        self.assertIn("no workflow", r.evidence[0])


class DangerousTriggerTest(Base):
    def test_real_workflows_are_safe(self):
        for name in ("pwa-platform", "agent-relay", "spec-guard-plugin", "tab-leader", "sso-browser-sdk"):
            with self.subTest(repo=name):
                self.assertEqual(self.repo(real(name)).ev(G6).status, "met")

    def test_pull_request_target_checking_out_pr_head(self):
        wf = ("on: pull_request_target\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: actions/checkout@%s\n"
              "        with:\n          ref: ${{ github.event.pull_request.head.sha }}\n" % ("a" * 40))
        r = self.repo({"t.yml": wf}).ev(G6)
        self.assertEqual(r.status, "gap")
        self.assertIn("t.yml", r.missing)

    def test_workflow_run_using_head_branch_in_a_script(self):
        wf = ("on:\n  workflow_run:\n    workflows: [CI]\njobs:\n  a:\n    runs-on: x\n    steps:\n"
              "      - run: |\n          git fetch origin ${{ github.event.workflow_run.head_branch }}\n")
        self.assertEqual(self.repo({"t.yml": wf}).ev(G6).status, "gap")

    def test_pull_request_target_without_pr_code_is_fine(self):
        wf = "on: [pull_request_target]\njobs:\n  a:\n    runs-on: x\n    steps:\n      - run: echo label\n"
        self.assertEqual(self.repo({"t.yml": wf}).ev(G6).status, "met")

    def test_unparseable_workflow_is_unknown(self):
        r = self.repo({"bad.yml": "on: push\njobs: &x\n  a: 1\n"}).ev(G6)
        self.assertEqual(r.status, "unknown")
        self.assertIn("bad.yml", r.error)


class PrRunsCheckTest(Base):
    def test_agent_relay_with_matching_interface(self):
        r = self.repo(real("agent-relay"), interface("bash scripts/validate.sh")).ev(G3)
        self.assertEqual(r.status, "met", r)
        self.assertIn("ci.yml", " ".join(r.evidence))

    def test_whitespace_is_normalised(self):
        self.assertEqual(self.repo(real("agent-relay"), interface("bash   scripts/validate.sh")).ev(G3).status, "met")

    def test_command_mismatch_is_gap(self):
        r = self.repo(real("agent-relay"), interface("/bin/bash scripts/validate.sh")).ev(G3)
        self.assertEqual(r.status, "gap")
        self.assertIn("/bin/bash scripts/validate.sh", r.missing)

    def test_missing_interface_is_gap(self):
        r = self.repo(real("agent-relay")).ev(G3)
        self.assertEqual(r.status, "gap")
        self.assertIn("interface.yml", r.missing)
        self.assertIn("pull_request", " ".join(r.evidence))  # the PR trigger itself was seen

    def test_wrapper_counts(self):
        wf = ("on: pull_request\njobs:\n  a:\n    runs-on: x\n    steps:\n"
              "      - run: autopr-entry run --entry check -- make verify\n")
        self.assertEqual(self.repo({"ci.yml": wf}, interface("make everything")).ev(G3).status, "met")

    def test_check_only_on_push_is_gap(self):
        wf = "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - run: make check\n"
        r = self.repo({"ci.yml": wf}, interface("make check")).ev(G3)
        self.assertEqual(r.status, "gap")
        self.assertIn("pull_request", r.missing)

    def test_trigger_forms(self):
        for on in ("on: pull_request", "on: [push, pull_request]", "on:\n  pull_request:\n    branches: [main]"):
            with self.subTest(on=on):
                wf = on + "\njobs:\n  a:\n    runs-on: x\n    steps:\n      - run: make check\n"
                self.assertEqual(self.repo({"ci.yml": wf}, interface("make check")).ev(G3).status, "met")

    def test_no_workflows_is_gap(self):
        self.assertEqual(self.repo({}, interface("make check")).ev(G3).status, "gap")

    def test_unreadable_workflow_is_unknown(self):
        files = dict(real("agent-relay"), **{"bad.yml": "on: push\njobs: &x\n  a: 1\n"})
        self.assertEqual(self.repo(files, interface("bash scripts/validate.sh")).ev(G3).status, "unknown")

    def test_unreadable_interface_is_unknown(self):
        r = self.repo(real("agent-relay"), "entries: &a\n  x: 1\n").ev(G3)
        self.assertEqual(r.status, "unknown")
        self.assertIn("interface.yml", r.error)


if __name__ == "__main__":
    unittest.main()
