"""GitHub platform adapter: GET-only, status classification, record / replay, github.repo probe, exit 3.

A fake `gh` executable stands in for the real one, so nothing here touches the network.
Its output format (status line, headers, blank line, body; exit 0 / 1 / 4) was observed
from gh 2.98.0 on 2026-11-19.
"""

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from repo_readiness.platform.github import (GitHub, LiveTransport, RecordingTransport, ReplayMissing,
                                            ReplayTransport)
from repo_readiness.probes.runtime import ProbeContext, evaluate

ROOT = Path(__file__).resolve().parent.parent

REPO_JSON = {"full_name": "haigeerlab/demo", "owner": {"login": "haigeerlab"}, "default_branch": "main"}


def fake_gh(dir_: Path, status_line, body="", exit_code=0, stderr="", headers=(), sleep=0):
    """Write a fake gh that logs its argv and prints an HTTP response like `gh api -i`."""
    log = dir_ / "argv.log"
    lines = [status_line] + list(headers) + ["", body] if status_line else [body]
    script = textwrap.dedent("""\
        #!/bin/bash
        printf '%s\\n' "$*" >> {log}
        sleep {sleep}
        cat <<'__OUT__'
        {out}
        __OUT__
        printf '%s' {err} >&2
        exit {code}
        """).format(log=log, sleep=sleep, out="\n".join(lines), err=json.dumps(stderr), code=exit_code)
    path = dir_ / "gh"
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path, log


class LiveTransportTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def get(self, *args, path="repos/haigeerlab/demo", timeout_s=10, **kw):
        gh, log = fake_gh(self.dir, *args, **kw)
        return GitHub(LiveTransport(gh=str(gh), timeout_s=timeout_s)).get(path), log

    def test_ok(self):
        r, log = self.get("HTTP/2.0 200 OK", json.dumps(REPO_JSON), headers=["Content-Type: application/json"])
        self.assertEqual((r.status, r.http_status, r.env_error), ("ok", 200, False))
        self.assertEqual(r.data["default_branch"], "main")
        argv = log.read_text(encoding="utf-8")
        self.assertIn("api -i --method GET", argv)
        self.assertIn("repos/haigeerlab/demo", argv)

    def test_not_found(self):
        r, _ = self.get("HTTP/2.0 404 Not Found", '{"message":"Not Found"}', exit_code=1,
                        stderr="gh: Not Found (HTTP 404)")
        self.assertEqual((r.status, r.http_status, r.env_error), ("not_found", 404, False))

    def test_forbidden_is_not_an_environment_problem(self):
        r, _ = self.get("HTTP/2.0 403 Forbidden", '{"message":"Resource not accessible by integration"}', exit_code=1,
                        headers=["X-RateLimit-Remaining: 4999"])
        self.assertEqual((r.status, r.env_error), ("forbidden", False))

    def test_rate_limit_is_an_environment_problem(self):
        r, _ = self.get("HTTP/2.0 403 Forbidden", '{"message":"API rate limit exceeded"}', exit_code=1,
                        headers=["X-RateLimit-Remaining: 0"])
        self.assertEqual((r.status, r.env_error), ("rate_limited", True))

    def test_server_error_is_an_environment_problem(self):
        r, _ = self.get("HTTP/2.0 502 Bad Gateway", "", exit_code=1)
        self.assertEqual((r.status, r.env_error), ("server_error", True))

    def test_not_logged_in(self):
        r, _ = self.get(None, "", exit_code=4, stderr="To get started with GitHub CLI, please run:  gh auth login")
        self.assertEqual((r.status, r.env_error), ("unauthenticated", True))
        self.assertIn("gh auth login", r.message)

    def test_network_failure(self):
        r, _ = self.get(None, "", exit_code=1, stderr="error connecting to api.github.com")
        self.assertEqual((r.status, r.env_error), ("network", True))

    def test_timeout(self):
        r, _ = self.get("HTTP/2.0 200 OK", "{}", sleep=3, timeout_s=1)
        self.assertEqual((r.status, r.env_error), ("network", True))

    def test_gh_missing(self):
        r = GitHub(LiveTransport(gh=str(self.dir / "no-gh-here"))).get("repos/a/b")
        self.assertEqual((r.status, r.env_error), ("gh_missing", True))

    def test_only_plain_read_paths_are_accepted(self):
        gh, log = fake_gh(self.dir, "HTTP/2.0 200 OK", "{}")
        client = GitHub(LiveTransport(gh=str(gh)))
        for bad in ("-X", "--method=POST", "repos/a/b -X DELETE", "https://evil.example/x", "repos/a/../b",
                    "repos/a/b\n", ""):
            with self.subTest(path=bad):
                with self.assertRaises(ValueError):
                    client.get(bad)
        self.assertFalse(log.exists())  # nothing was executed


class RecordReplayTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            gh, _ = fake_gh(d, "HTTP/2.0 200 OK", json.dumps(REPO_JSON))
            rec_dir = d / "rec"
            live = GitHub(RecordingTransport(LiveTransport(gh=str(gh)), rec_dir))
            first = live.get("repos/haigeerlab/demo")
            self.assertEqual(len(list(rec_dir.glob("*.json"))), 1)
            replay = GitHub(ReplayTransport(rec_dir))
            again = replay.get("repos/haigeerlab/demo")
            self.assertEqual((again.status, again.data), (first.status, first.data))

    def test_missing_recording_fails_loudly(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ReplayMissing):
                GitHub(ReplayTransport(Path(d))).get("repos/x/y")

    def test_missing_recording_is_not_swallowed_by_the_probe_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = ProbeContext(repo_root=Path(d), github=GitHub(ReplayTransport(Path(d))), repo_name="x/y")
            with self.assertRaises(ReplayMissing):
                evaluate({"use": "github.repo", "with": {"owner": "x", "default_branch": "main"}}, ctx)


class RepoProbeTest(unittest.TestCase):
    """github.repo backs G1: owner and default branch."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def probe(self, data=None, http="HTTP/2.0 200 OK", code=0, stderr="", repo_name="haigeerlab/demo"):
        gh, _ = fake_gh(self.dir, http, json.dumps(data) if data is not None else "", exit_code=code, stderr=stderr)
        ctx = ProbeContext(repo_root=self.dir, github=GitHub(LiveTransport(gh=str(gh))), repo_name=repo_name)
        return evaluate({"use": "github.repo", "with": {"owner": "haigeerlab", "default_branch": "main"}}, ctx)

    def test_met(self):
        r = self.probe(REPO_JSON)
        self.assertEqual(r.status, "met")
        self.assertTrue(any("haigeerlab/demo" in e for e in r.evidence))

    def test_wrong_owner_or_branch(self):
        r = self.probe(dict(REPO_JSON, owner={"login": "someone"}))
        self.assertEqual(r.status, "gap")
        self.assertIn("someone", r.missing)
        r = self.probe(dict(REPO_JSON, default_branch="master"))
        self.assertEqual(r.status, "gap")
        self.assertIn("master", r.missing)

    def test_repo_not_on_github(self):
        r = self.probe({"message": "Not Found"}, http="HTTP/2.0 404 Not Found", code=1)
        self.assertEqual(r.status, "gap")

    def test_not_logged_in_is_unknown_and_flags_environment(self):
        r = self.probe(None, http=None, code=4, stderr="gh auth login")
        self.assertEqual(r.status, "unknown")
        self.assertTrue(r.env_error)

    def test_without_repo_name_is_unknown(self):
        r = self.probe(REPO_JSON, repo_name=None)
        self.assertEqual(r.status, "unknown")
        self.assertIn("--repo-name", r.error)
        self.assertFalse(r.env_error)


class RealRecordingTest(unittest.TestCase):
    """A real response recorded on 2026-11-19 (read-only GET) replays to G1 met."""

    def test_repo_readiness_g1_from_recording(self):
        rec = ROOT / "tests" / "fixtures" / "github" / "repo-readiness"
        ctx = ProbeContext(repo_root=ROOT, github=GitHub(ReplayTransport(rec)), repo_name="haigeerlab/repo-readiness")
        r = evaluate({"use": "github.repo", "with": {"owner": "haigeerlab", "default_branch": "main"}}, ctx)
        self.assertEqual(r.status, "met", r)
        r = evaluate({"use": "github.repo", "with": {"owner": "someone-else", "default_branch": "main"}}, ctx)
        self.assertEqual(r.status, "gap")


class CheckExitThreeTest(unittest.TestCase):
    """End to end: a GitHub probe that cannot reach GitHub makes `check` exit 3, report still written."""

    def test_exit_three_when_gh_is_not_logged_in(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            bindir = d / "bin"
            bindir.mkdir()
            fake_gh(bindir, None, "", exit_code=4, stderr="To get started with GitHub CLI, please run:  gh auth login")
            ruler = d / "ruler.json"
            ruler.write_text(json.dumps({
                "schema": "repo-readiness.clauses/v1", "id": "g", "version": "1.0.0", "kind": "base", "owner": "x",
                "tiers": [{"id": "basic", "name": "基础档", "rank": 1}], "below_lowest": {"name": "未达标"},
                "gate": {"should": {"rule": "ratio", "ratio": 0.8}},
                "clauses": [{"id": "G1", "requirement": "r", "guards": "g", "levels": [{"tier": "basic", "strength": "must"}],
                             "scope": "repo", "applies": {"categories": "*"}, "method": "auto",
                             "probe": {"use": "github.repo", "with": {"owner": "haigeerlab", "default_branch": "main"}}}],
            }), encoding="utf-8")
            (d / "repo").mkdir()
            env = dict(os.environ, PATH="%s:%s" % (bindir, os.environ["PATH"]))
            p = subprocess.run([str(ROOT / "bin" / "repo-readiness"), "check", str(d / "repo"), "--clauses", str(ruler),
                                "--out", str(d / "out"), "--repo-name", "haigeerlab/demo"],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, env=env)
            self.assertEqual(p.returncode, 3, p.stderr)
            self.assertIn("gh auth login", p.stderr)
            report = json.loads((d / "out" / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["results"][0]["status"], "unknown")
            self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
