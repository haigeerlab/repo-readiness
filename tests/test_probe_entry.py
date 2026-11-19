"""entry.run (V1, V2): run an interface.yml entry per the interface contract, in a throwaway clone.

Only toy repositories built here are executed. Nothing runs unless exec_entries is on.
"""

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from repo_readiness.clauses import from_data
from repo_readiness.detect.engine import scan
from repo_readiness.probes.runtime import ProbeContext, evaluate

V1 = {"use": "entry.run", "with": {"entry": "check", "mode": "full"}}
V2 = {"use": "entry.run", "with": {"entry": "check", "mode": "changed"}}
GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]


def git(repo, *args):
    subprocess.run(GIT + ["-C", str(repo)] + list(args), check=True, stdin=subprocess.DEVNULL,
                   capture_output=True, text=True)


class ToyRepo:
    def __init__(self, script, interface=None, commit=True, extra=None):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        (self.root / "check.sh").write_text("#!/bin/sh\n" + textwrap.dedent(script), encoding="utf-8")
        (self.root / "tracked.txt").write_text("original\n", encoding="utf-8")
        for rel, text in (extra or {}).items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        if interface is None:
            interface = ('version: 1\nentries:\n  check:\n    run: "sh check.sh"\n    timeout_minutes: 1\n'
                         '    report: wrapped\n    changed: "sh check.sh --changed {base}"\n')
        if interface is not False:
            (self.root / ".github" / "autopr").mkdir(parents=True)
            (self.root / ".github" / "autopr" / "interface.yml").write_text(interface, encoding="utf-8")
        git(self.root, "init", "-q")
        if commit:
            git(self.root, "add", "-A")
            git(self.root, "commit", "-qm", "one")
            (self.root / "tracked.txt").write_text("second\n", encoding="utf-8")
            git(self.root, "commit", "-qam", "two")

    def ev(self, expr=V1, exec_entries=True):
        return evaluate(expr, ProbeContext(repo_root=self.root, exec_entries=exec_entries))

    def close(self):
        self._tmp.cleanup()


class Base(unittest.TestCase):
    def toy(self, *a, **kw):
        t = ToyRepo(*a, **kw)
        self.addCleanup(t.close)
        return t


class ExitCodeTest(Base):
    def test_exit_zero_is_met(self):
        r = self.toy("exit 0\n").ev()
        self.assertEqual(r.status, "met", r)
        self.assertIn("exit 0", " ".join(r.evidence))

    def test_exit_one_is_gap(self):
        r = self.toy("echo boom >&2\nexit 1\n").ev()
        self.assertEqual(r.status, "gap")
        self.assertIn("exit 1", r.missing)

    def test_exit_two_is_an_entry_error_not_a_patch_failure(self):
        r = self.toy("exit 2\n").ev()
        self.assertEqual(r.status, "unknown")
        self.assertFalse(r.env_error)
        self.assertIn("exit 2", r.error)

    def test_other_nonzero_is_treated_as_two(self):
        self.assertEqual(self.toy("exit 7\n").ev().status, "unknown")

    def test_exit_three_is_environment(self):
        r = self.toy("exit 3\n").ev()
        self.assertEqual(r.status, "unknown")
        self.assertTrue(r.env_error)

    def test_timeout_is_environment(self):
        iface = 'version: 1\nentries:\n  check:\n    run: "sh check.sh"\n    timeout_minutes: 0.02\n    report: wrapped\n'
        r = self.toy("sleep 5\n", interface=iface).ev()
        self.assertEqual(r.status, "unknown")
        self.assertTrue(r.env_error)
        self.assertIn("timeout", r.error)

    def test_stdin_is_closed(self):
        self.assertEqual(self.toy("cat > /dev/null\nexit 0\n").ev().status, "met")


class ContractTest(Base):
    def test_environment_variables_and_scrubbed_secrets(self):
        script = ('echo "AUTOPR=$AUTOPR ENTRY=$AUTOPR_ENTRY HEAD=$AUTOPR_HEAD GH=${GH_TOKEN:-absent}"\n'
                  '[ -n "$AUTOPR_REPORT" ] || exit 1\nexit 0\n')
        t = self.toy(script)
        os.environ["GH_TOKEN"] = "secret-should-not-leak"
        try:
            r = t.ev()
        finally:
            del os.environ["GH_TOKEN"]
        self.assertEqual(r.status, "met", r)
        env_dump = " ".join(r.evidence)  # the tail of the entry's output is part of the evidence
        self.assertIn("AUTOPR=1", env_dump)
        self.assertIn("ENTRY=check", env_dump)
        head = subprocess.run(["git", "-C", str(t.root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertIn("HEAD=" + head, env_dump)
        self.assertIn("GH=absent", env_dump)

    def test_runs_the_committed_head_not_uncommitted_changes(self):
        t = self.toy('grep -q second tracked.txt || exit 1\nexit 0\n')
        (t.root / "tracked.txt").write_text("uncommitted\n", encoding="utf-8")
        self.assertEqual(t.ev().status, "met")

    def test_source_repository_is_untouched(self):
        t = self.toy("echo built > artifact.out\nexit 0\n")
        before = subprocess.run(["git", "-C", str(t.root), "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertEqual(t.ev().status, "met")
        after = subprocess.run(["git", "-C", str(t.root), "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertEqual(before, after)
        self.assertFalse((t.root / "artifact.out").exists())
        self.assertFalse((t.root / ".git" / "worktrees").exists())

    def test_entry_that_changes_tracked_files_is_an_error(self):
        r = self.toy("echo changed > tracked.txt\nexit 0\n").ev()
        self.assertEqual(r.status, "unknown")
        self.assertIn("modified", r.error)

    def test_entry_that_commits_is_an_error(self):
        r = self.toy("git -c user.email=a@b.invalid -c user.name=a commit -q --allow-empty -m x\nexit 0\n").ev()
        self.assertEqual(r.status, "unknown")
        self.assertIn("HEAD", r.error)

    def test_native_report_is_validated(self):
        good = textwrap.dedent('''\
            cat > "$AUTOPR_REPORT" <<EOF
            {"schema":"autopr.entry-report/v1","entry":"check","repo":"a/b","head":"$AUTOPR_HEAD","status":"pass",
             "exit_code":0,"started_at":"2026-11-20T00:00:00Z","duration_s":1,"producer":"native"}
            EOF
            exit 0
            ''')
        iface = 'version: 1\nentries:\n  check:\n    run: "sh check.sh"\n    report: native\n'
        self.assertEqual(self.toy(good, interface=iface).ev().status, "met")
        wrong_head = good.replace("$AUTOPR_HEAD", "a" * 40)
        r = self.toy(wrong_head, interface=iface).ev()
        self.assertEqual(r.status, "unknown")
        self.assertIn("does not match the commit", r.error)  # evidence must be bound to the commit that ran
        r = self.toy('echo "{}" > "$AUTOPR_REPORT"\nexit 0\n', interface=iface).ev()
        self.assertEqual(r.status, "unknown")
        self.assertIn("entry-report", r.error)
        r = self.toy("exit 0\n", interface=iface).ev()
        self.assertEqual(r.status, "unknown")
        self.assertIn("no report", r.error)


class ConfigurationTest(Base):
    def test_no_interface_file_is_gap(self):
        self.assertEqual(self.toy("exit 0\n", interface=False).ev().status, "gap")

    def test_entry_not_registered_is_gap(self):
        r = self.toy("exit 0\n", interface="version: 1\nentries: {}\n").ev()
        self.assertEqual(r.status, "gap")
        self.assertIn("check", r.missing)

    def test_changed_mode_needs_the_changed_command(self):
        iface = 'version: 1\nentries:\n  check:\n    run: "sh check.sh"\n'
        r = self.toy("exit 0\n", interface=iface).ev(V2)
        self.assertEqual(r.status, "gap")
        self.assertIn("changed", r.missing)

    def test_changed_mode_substitutes_base(self):
        r = self.toy('[ "$1" = "--changed" ] && [ ${#2} -eq 40 ] || exit 1\nexit 0\n').ev(V2)
        self.assertEqual(r.status, "met", r)

    def test_not_a_git_checkout_is_unknown(self):
        t = self.toy("exit 0\n", commit=False)
        self.assertEqual(t.ev().status, "unknown")


class OptInTest(Base):
    def test_disabled_by_default_and_reported_as_not_evaluated(self):
        t = self.toy("exit 0\n")
        r = t.ev(exec_entries=False)
        self.assertEqual(r.status, "unknown")
        self.assertTrue(r.skipped)
        ruler = from_data({
            "schema": "repo-readiness.clauses/v1", "id": "e", "version": "1.0.0", "kind": "base", "owner": "x",
            "tiers": [{"id": "basic", "name": "B", "rank": 1}], "below_lowest": {"name": "none"},
            "gate": {"should": {"rule": "ratio", "ratio": 0.8}},
            "clauses": [{"id": "V1", "requirement": "r", "guards": "g", "levels": [{"tier": "basic", "strength": "must"}],
                         "scope": "repo", "applies": {"categories": "*"}, "method": "interface", "probe": V1}]})
        sc = scan(ruler, t.root)
        self.assertEqual(sc.results[0].status, "unknown")
        self.assertEqual(sc.errors, [])  # not a probe error: a conclusion can still be issued
        self.assertTrue(any("--exec-entries" in n["reason"] for n in sc.not_evaluated))


if __name__ == "__main__":
    unittest.main()
