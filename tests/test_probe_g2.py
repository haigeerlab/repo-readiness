"""G2: rules actually in force on main = legacy protection ∪ active rulesets, judged property by property.

Real recordings (read-only GET, 2026-11-19): pwa-platform (ruleset only), agent-relay (legacy only,
no PR requirement), repo-readiness (nothing). Constructed cases start from those recordings and
change one field, so their shape is the real API's.

Bypass rule (autopr-standard #21538): an app / integration / deploy key / team / non-admin role in
a bypass list -> gap; only admin roles or individual users -> met, flagged "存在绕过".
"""

import copy
import unittest
from pathlib import Path

from repo_readiness.platform.github import GhResponse, GitHub, ReplayTransport
from repo_readiness.probes.runtime import ProbeContext, evaluate

FIX = Path(__file__).resolve().parent / "fixtures" / "github"
EXPR = {"use": "github.effective_branch_rules",
        "with": {"branch": "main", "require": ["no_force_push", "no_deletion", "pull_request_required"]}}


class DictTransport:
    """Recorded responses, with optional overrides; unknown paths fall back to a replay directory."""

    def __init__(self, base_dir, overrides=None):
        self.replay = ReplayTransport(base_dir)
        self.overrides = overrides or {}

    def fetch(self, path):
        if path in self.overrides:
            return self.overrides[path]
        return self.replay.fetch(path)


def run(repo, overrides=None):
    gh = GitHub(DictTransport(FIX / repo, overrides))
    ctx = ProbeContext(repo_root=Path("/"), github=gh, repo_name="haigeerlab/" + repo)
    return evaluate(EXPR, ctx)


def recorded(repo, path):
    return ReplayTransport(FIX / repo).fetch(path)


PWA_RULESET = "repos/haigeerlab/pwa-platform/rulesets/23986228"
PWA_RULES = "repos/haigeerlab/pwa-platform/rules/branches/main"
PWA_LEGACY = "repos/haigeerlab/pwa-platform/branches/main/protection"
RELAY_LEGACY = "repos/haigeerlab/agent-relay/branches/main/protection"
RELAY_RULES = "repos/haigeerlab/agent-relay/rules/branches/main"


def ruleset_with(**changes):
    r = recorded("pwa-platform", PWA_RULESET)
    data = copy.deepcopy(r.data)
    data.update(changes)
    return GhResponse("ok", 200, data)


class RealRecordingsTest(unittest.TestCase):
    def test_pwa_platform_ruleset_is_met(self):
        r = run("pwa-platform")
        self.assertEqual(r.status, "met", r)
        joined = " ".join(r.evidence)
        self.assertIn("main: PR and CI gate", joined)
        self.assertNotIn("存在绕过", joined)

    def test_agent_relay_legacy_without_pr_is_gap(self):
        r = run("agent-relay")
        self.assertEqual(r.status, "gap", r)
        self.assertIn("pull_request_required", r.missing)
        self.assertNotIn("no_force_push", r.missing)
        self.assertNotIn("no_deletion", r.missing)

    def test_unprotected_repo_is_gap_on_everything(self):
        r = run("repo-readiness")
        self.assertEqual(r.status, "gap")
        for req in ("no_force_push", "no_deletion", "pull_request_required"):
            self.assertIn(req, r.missing)


class EnforcementTest(unittest.TestCase):
    def test_evaluate_mode_ruleset_does_not_count(self):
        r = run("pwa-platform", {PWA_RULESET: ruleset_with(enforcement="evaluate")})
        self.assertEqual(r.status, "gap")
        self.assertIn("evaluate", " ".join(r.evidence))

    def test_disabled_ruleset_does_not_count(self):
        self.assertEqual(run("pwa-platform", {PWA_RULESET: ruleset_with(enforcement="disabled")}).status, "gap")


class UnionTest(unittest.TestCase):
    def test_legacy_and_ruleset_combine_property_by_property(self):
        # agent-relay's legacy protection covers force push + deletion; a ruleset adds only the PR rule.
        rules = GhResponse("ok", 200, [{"type": "pull_request", "ruleset_source_type": "Repository",
                                        "ruleset_source": "haigeerlab/agent-relay", "ruleset_id": 7}])
        detail = GhResponse("ok", 200, {"id": 7, "name": "pr only", "enforcement": "active", "bypass_actors": []})
        r = run("agent-relay", {RELAY_RULES: rules, "repos/haigeerlab/agent-relay/rulesets/7": detail})
        self.assertEqual(r.status, "met", r)

    def test_legacy_pull_request_reviews_count_as_pr_required(self):
        legacy = recorded("agent-relay", RELAY_LEGACY)
        data = copy.deepcopy(legacy.data)
        data["required_pull_request_reviews"] = {"required_approving_review_count": 0}
        self.assertEqual(run("agent-relay", {RELAY_LEGACY: GhResponse("ok", 200, data)}).status, "met")


class BypassTest(unittest.TestCase):
    def with_bypass(self, *actors):
        return run("pwa-platform", {PWA_RULESET: ruleset_with(bypass_actors=list(actors))})

    def test_app_in_bypass_list_is_gap(self):
        r = self.with_bypass({"actor_id": 1, "actor_type": "Integration", "bypass_mode": "always"})
        self.assertEqual(r.status, "gap")
        self.assertIn("Integration", r.missing)

    def test_deploy_key_and_team_are_gap(self):
        self.assertEqual(self.with_bypass({"actor_id": None, "actor_type": "DeployKey", "bypass_mode": "always"}).status, "gap")
        self.assertEqual(self.with_bypass({"actor_id": 9, "actor_type": "Team", "bypass_mode": "always"}).status, "gap")

    def test_non_admin_role_is_gap(self):
        self.assertEqual(self.with_bypass({"actor_id": 4, "actor_type": "RepositoryRole", "bypass_mode": "always"}).status, "gap")

    def test_admin_roles_are_met_with_a_flag(self):
        for actor in ({"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"},
                      {"actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always"}):
            with self.subTest(actor=actor["actor_type"]):
                r = self.with_bypass(actor)
                self.assertEqual(r.status, "met", r)
                self.assertIn("存在绕过", " ".join(r.evidence))

    def test_legacy_without_enforce_admins_is_flagged(self):
        legacy = recorded("agent-relay", RELAY_LEGACY)
        data = copy.deepcopy(legacy.data)
        data["required_pull_request_reviews"] = {"required_approving_review_count": 0}
        data["enforce_admins"] = {"enabled": False}
        r = run("agent-relay", {RELAY_LEGACY: GhResponse("ok", 200, data)})
        self.assertEqual(r.status, "met")
        self.assertIn("存在绕过", " ".join(r.evidence))

    def test_legacy_pr_bypass_for_apps_is_gap(self):
        legacy = recorded("agent-relay", RELAY_LEGACY)
        data = copy.deepcopy(legacy.data)
        data["required_pull_request_reviews"] = {"bypass_pull_request_allowances": {"users": [], "teams": [],
                                                                                    "apps": [{"slug": "bot"}]}}
        r = run("agent-relay", {RELAY_LEGACY: GhResponse("ok", 200, data)})
        self.assertEqual(r.status, "gap")
        self.assertIn("bot", r.missing)

    def test_hidden_bypass_list_is_unknown(self):
        data = copy.deepcopy(recorded("pwa-platform", PWA_RULESET).data)
        del data["bypass_actors"]  # GitHub omits it for tokens without admin rights
        r = run("pwa-platform", {PWA_RULESET: GhResponse("ok", 200, data)})
        self.assertEqual(r.status, "unknown")
        self.assertIn("绕过名单", r.error)  # a reasoned unknown, not a crash caught by the runtime
        self.assertNotIn("crashed", r.error)


class PermissionTest(unittest.TestCase):
    def test_cannot_read_anything_is_unknown_not_gap(self):
        hidden = GhResponse("not_found", 404, {"message": "Not Found"}, "Not Found")
        forbidden = GhResponse("forbidden", 403, {"message": "Resource not accessible"}, "Resource not accessible")
        r = run("agent-relay", {RELAY_LEGACY: hidden, RELAY_RULES: forbidden})
        self.assertEqual(r.status, "unknown", r)
        self.assertFalse(r.env_error)

    def test_unreadable_legacy_does_not_matter_when_rulesets_cover_everything(self):
        hidden = GhResponse("not_found", 404, {"message": "Not Found"}, "Not Found")
        self.assertEqual(run("pwa-platform", {PWA_LEGACY: hidden}).status, "met")

    def test_unreadable_legacy_with_partial_rulesets_is_unknown(self):
        hidden = GhResponse("not_found", 404, {"message": "Not Found"}, "Not Found")
        self.assertEqual(run("repo-readiness", {"repos/haigeerlab/repo-readiness/branches/main/protection": hidden}).status,
                         "unknown")

    def test_environment_problem_propagates(self):
        down = GhResponse("network", message="error connecting to api.github.com")
        r = run("pwa-platform", {PWA_RULES: down})
        self.assertEqual(r.status, "unknown")
        self.assertTrue(r.env_error)

    def test_repository_not_on_github_is_gap_not_unknown(self):
        # session-protocol shape: no remote at all, so there is no protection to read.
        gone = GhResponse("not_found", 404, {"message": "Not Found"}, "Not Found")
        r = run("repo-readiness", {"repos/haigeerlab/repo-readiness": gone})
        self.assertEqual(r.status, "gap")
        self.assertIn("not on GitHub", r.missing)

    def test_org_ruleset_is_fetched_from_the_org(self):
        rules = GhResponse("ok", 200, [{"type": t, "ruleset_source_type": "Organization", "ruleset_source": "haigeerlab",
                                        "ruleset_id": 42} for t in ("deletion", "non_fast_forward", "pull_request")])
        detail = GhResponse("ok", 200, {"id": 42, "name": "org gate", "enforcement": "active", "bypass_actors": []})
        r = run("repo-readiness", {"repos/haigeerlab/repo-readiness/rules/branches/main": rules,
                                   "orgs/haigeerlab/rulesets/42": detail})
        self.assertEqual(r.status, "met", r)


if __name__ == "__main__":
    unittest.main()
