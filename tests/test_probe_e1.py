"""E1: third-party dependencies are locked and CI installs from the lock (ecosystem adapters, data-driven)."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from repo_readiness.clauses import load
from repo_readiness.detect.engine import scan
from repo_readiness.probes.runtime import ProbeContext, evaluate

FIX = Path(__file__).resolve().parent / "fixtures"
HAS = {"use": "ecosystem.has_dependencies"}
LOCKED = {"use": "ecosystem.lockfile_installed"}
PKG = json.dumps({"name": "x", "dependencies": {"ws": "^8.0.0"}})
GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]


def workflow(*steps):
    body = "".join("      - %s\n" % s for s in steps)
    return "on: pull_request\njobs:\n  a:\n    runs-on: x\n    steps:\n" + body


class Base(unittest.TestCase):
    def repo(self, files, git=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        if git:
            subprocess.run(GIT + ["-C", str(root), "init", "-q"], check=True, stdin=subprocess.DEVNULL)
            subprocess.run(GIT + ["-C", str(root), "add", "-A"], check=True, stdin=subprocess.DEVNULL)
        return root

    def ev(self, root, expr, base=""):
        return evaluate(expr, ProbeContext(repo_root=root, base=base))


class HasDependenciesTest(Base):
    def test_nested_package_json_counts(self):
        r = self.ev(self.repo({"plugins/bridge/package.json": PKG}), HAS)
        self.assertEqual(r.status, "met")
        self.assertIn("plugins/bridge/package.json", " ".join(r.evidence))

    def test_no_manifest_means_no_dependencies(self):
        r = self.ev(self.repo({"scripts/check.py": "print(1)\n"}), HAS)
        self.assertEqual(r.status, "gap")

    def test_package_json_without_dependencies(self):
        self.assertEqual(self.ev(self.repo({"package.json": '{"name": "x", "scripts": {}}'}), HAS).status, "gap")

    def test_untracked_and_node_modules_manifests_are_ignored(self):
        root = self.repo({"README.md": "x"})
        (root / "node_modules" / "a").mkdir(parents=True)
        (root / "node_modules" / "a" / "package.json").write_text(PKG, encoding="utf-8")
        (root / "scratch").mkdir()
        (root / "scratch" / "package.json").write_text(PKG, encoding="utf-8")  # untracked
        self.assertEqual(self.ev(root, HAS).status, "gap")

    def test_python_requirements_and_pyproject(self):
        self.assertEqual(self.ev(self.repo({"requirements.txt": "# only comments\n\n"}), HAS).status, "gap")
        self.assertEqual(self.ev(self.repo({"requirements.txt": "requests==2.32.3\n"}), HAS).status, "met")
        pyproject = '[project]\nname = "x"\ndependencies = [\n  "httpx>=0.27",\n]\n'
        self.assertEqual(self.ev(self.repo({"pyproject.toml": pyproject}), HAS).status, "met")
        self.assertEqual(self.ev(self.repo({"pyproject.toml": '[project]\nname = "x"\ndependencies = []\n'}), HAS).status, "gap")

    def test_unparseable_package_json_is_unknown(self):
        self.assertEqual(self.ev(self.repo({"package.json": "{nope"}), HAS).status, "unknown")

    def test_app_scope_looks_only_inside_the_app(self):
        root = self.repo({"apps/web/package.json": PKG, "apps/api/README.md": "x"})
        self.assertEqual(self.ev(root, HAS, base="apps/api").status, "gap")
        self.assertEqual(self.ev(root, HAS, base="apps/web").status, "met")

    def test_works_without_git(self):
        self.assertEqual(self.ev(self.repo({"package.json": PKG}, git=False), HAS).status, "met")


class LockfileInstalledTest(Base):
    def test_agent_relay_shape_nested_lock_and_npm_ci(self):
        wf = (FIX / "workflows" / "agent-relay.ci.yml").read_text(encoding="utf-8")
        root = self.repo({"plugins/agent-relay/bridge/package.json": PKG,
                          "plugins/agent-relay/bridge/package-lock.json": "{}",
                          ".github/workflows/ci.yml": wf})
        r = self.ev(root, LOCKED)
        self.assertEqual(r.status, "met", r)
        self.assertIn("npm ci", " ".join(r.evidence))

    def test_pwa_platform_shape_install_through_an_action(self):
        wf = (FIX / "workflows" / "pwa-platform.ci.yml").read_text(encoding="utf-8")
        root = self.repo({"package.json": PKG, "pnpm-lock.yaml": "lockfileVersion: 9\n", ".github/workflows/ci.yml": wf})
        r = self.ev(root, LOCKED)
        self.assertEqual(r.status, "met", r)
        self.assertIn("pnpm/setup", " ".join(r.evidence))

    def test_tab_leader_shape(self):
        wf = (FIX / "workflows" / "tab-leader.ci.yml").read_text(encoding="utf-8")
        root = self.repo({"package.json": PKG, "pnpm-lock.yaml": "x", ".github/workflows/ci.yml": wf})
        self.assertEqual(self.ev(root, LOCKED).status, "met")

    def test_lock_in_a_parent_directory_counts(self):
        root = self.repo({"package.json": '{"workspaces": ["packages/*"]}', "pnpm-lock.yaml": "x",
                          "packages/a/package.json": PKG,
                          ".github/workflows/ci.yml": workflow("run: pnpm install --frozen-lockfile")})
        self.assertEqual(self.ev(root, LOCKED).status, "met")

    def test_no_lockfile_is_gap(self):
        root = self.repo({"package.json": PKG, ".github/workflows/ci.yml": workflow("run: npm ci")})
        r = self.ev(root, LOCKED)
        self.assertEqual(r.status, "gap")
        self.assertIn("no lockfile", r.missing)

    def test_ci_not_installing_from_the_lock_is_gap(self):
        root = self.repo({"package.json": PKG, "package-lock.json": "{}",
                          ".github/workflows/ci.yml": workflow("run: npm install", "run: pnpm install")})
        r = self.ev(root, LOCKED)
        self.assertEqual(r.status, "gap")
        self.assertIn("without the lockfile", r.missing)

    def test_action_without_the_lock_flag_is_not_enough(self):
        wf = workflow("uses: pnpm/setup@%s" % ("a" * 40))
        root = self.repo({"package.json": PKG, "pnpm-lock.yaml": "x", ".github/workflows/ci.yml": wf})
        self.assertEqual(self.ev(root, LOCKED).status, "gap")

    def test_ci_that_never_installs_this_ecosystem_is_fine(self):
        # spec-guard shape: a locked package.json that CI does not install at all.
        root = self.repo({"tools/x/package.json": PKG, "tools/x/package-lock.json": "{}",
                          ".github/workflows/ci.yml": workflow("run: bash scripts/validate.sh")})
        r = self.ev(root, LOCKED)
        self.assertEqual(r.status, "met", r)
        self.assertIn("does not install node", " ".join(r.evidence))

    def test_ci_never_installing_does_not_excuse_a_missing_lock(self):
        root = self.repo({"package.json": PKG, ".github/workflows/ci.yml": workflow("run: make test")})
        self.assertEqual(self.ev(root, LOCKED).status, "gap")

    def test_no_ci_at_all_leaves_it_to_the_lockfile(self):
        # frontend-knowledge-tree shape: locked demo dependencies, no CI. Missing CI is G3's finding, not E1's.
        r = self.ev(self.repo({"package.json": PKG, "package-lock.json": "{}"}), LOCKED)
        self.assertEqual(r.status, "met", r)
        self.assertIn("no CI workflow", " ".join(r.evidence))

    def test_no_ci_does_not_excuse_a_missing_lock(self):
        self.assertEqual(self.ev(self.repo({"package.json": PKG}), LOCKED).status, "gap")

    def test_pinned_requirements_are_a_lock(self):
        wf = workflow("run: python -m pip install -r requirements.txt")
        root = self.repo({"requirements.txt": "requests==2.32.3\nidna==3.7 --hash=sha256:abc\n",
                          ".github/workflows/ci.yml": wf})
        self.assertEqual(self.ev(root, LOCKED).status, "met")
        root = self.repo({"requirements.txt": "requests>=2\n", ".github/workflows/ci.yml": wf})
        r = self.ev(root, LOCKED)
        self.assertEqual(r.status, "gap")
        self.assertIn("requests>=2", r.missing)

    def test_uv_lock(self):
        root = self.repo({"pyproject.toml": '[project]\ndependencies = ["httpx"]\n', "uv.lock": "x",
                          ".github/workflows/ci.yml": workflow("run: uv sync --frozen")})
        self.assertEqual(self.ev(root, LOCKED).status, "met")

    def test_unreadable_workflow_is_unknown(self):
        root = self.repo({"package.json": PKG, "package-lock.json": "{}", ".github/workflows/ci.yml": "on: &a x\n"})
        self.assertEqual(self.ev(root, LOCKED).status, "unknown")


class TrialRulerTest(Base):
    def test_e1_is_na_without_dependencies_and_judged_with_them(self):
        ruler = load(FIX / "rulesets" / "autopr-onboarding-2.0-basic.trial.json")
        plain = scan(ruler, self.repo({"scripts/x.sh": "echo\n"}), category="plugin")
        e1 = next(r for r in plain.results if r.clause == "E1")
        self.assertEqual(e1.status, "na")
        deps = scan(ruler, self.repo({"package.json": PKG, "package-lock.json": "{}",
                                      ".github/workflows/ci.yml": workflow("run: npm ci")}), category="plugin")
        self.assertEqual(next(r for r in deps.results if r.clause == "E1").status, "met")


if __name__ == "__main__":
    unittest.main()
