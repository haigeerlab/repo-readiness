"""GitHub probes. All requests go through the read-only platform adapter in ctx.github."""

from typing import Dict, Optional, Tuple

from repo_readiness.probes import runtime
from repo_readiness.probes.runtime import ProbeContext, ProbeResult


def _ready(ctx: ProbeContext) -> Optional[ProbeResult]:
    if ctx.github is None:
        return ProbeResult(status="unknown", error="GitHub access is off for this run")
    if not ctx.repo_name:
        return ProbeResult(status="unknown", error="repository name unknown; pass --repo-name owner/name")
    return None


def _fetch(ctx: ProbeContext, path: str) -> Tuple[Optional[object], Optional[ProbeResult]]:
    r = ctx.github.get(path)
    if r.env_error:
        return None, ProbeResult(status="unknown", env_error=True,
                                 error="GitHub not reachable (%s): %s" % (r.status, r.message))
    return r, None


@runtime.register("github.repo")
def repo(params: Dict, ctx: ProbeContext) -> ProbeResult:
    blocked = _ready(ctx)
    if blocked:
        return blocked
    r, failed = _fetch(ctx, "repos/%s" % ctx.repo_name)
    if failed:
        return failed
    if r.status == "not_found":
        return ProbeResult(status="gap", missing="repository %s not found on GitHub (or not visible to this token)"
                           % ctx.repo_name)
    if not r.ok:
        return ProbeResult(status="unknown", error="cannot read repos/%s: %s %s" % (ctx.repo_name, r.status, r.message))
    owner = (r.data.get("owner") or {}).get("login")
    branch = r.data.get("default_branch")
    problems = []
    if owner != params["owner"]:
        problems.append("owner is %s, expected %s" % (owner, params["owner"]))
    if branch != params["default_branch"]:
        problems.append("default branch is %s, expected %s" % (branch, params["default_branch"]))
    evidence = ["GET repos/%s: owner %s, default branch %s" % (ctx.repo_name, owner, branch)]
    if problems:
        return ProbeResult(status="gap", evidence=evidence, missing="; ".join(problems))
    return ProbeResult(status="met", evidence=evidence)


# --------------------------------------------------------------------------- G2

_RULE_TYPES = {"deletion": "no_deletion", "non_fast_forward": "no_force_push", "pull_request": "pull_request_required"}
_ADMIN_ROLE_ID = 5  # built-in repository role id of "admin" in ruleset bypass lists
_HUMAN_ADMIN_TYPES = {"OrganizationAdmin", "EnterpriseOwner", "User"}


class _Source:
    def __init__(self, label: str):
        self.label = label
        self.blocked = []  # bypassers that could be (or act for) an agent
        self.flagged = []  # admin / individual bypassers: allowed, reported


def _classify_bypass(actor: Dict, src: _Source) -> None:
    kind = actor.get("actor_type")
    who = "%s(%s)" % (kind, actor.get("actor_id"))
    if kind == "RepositoryRole" and actor.get("actor_id") == _ADMIN_ROLE_ID:
        src.flagged.append("admin role")
    elif kind in _HUMAN_ADMIN_TYPES:
        src.flagged.append(who)
    else:
        src.blocked.append(who)


def _legacy(ctx: ProbeContext, branch: str, provided: Dict, unreadable: list, notes: list):
    r, failed = _fetch(ctx, "repos/%s/branches/%s/protection" % (ctx.repo_name, branch))
    if failed:
        return failed
    if r.status == "not_found" and r.message == "Branch not protected":
        notes.append("旧版保护：未设置")
        return None
    if not r.ok:
        unreadable.append("旧版分支保护（%s）" % (r.message or r.status))
        return None
    d = r.data
    src = _Source("旧版保护")
    if not d.get("enforce_admins", {}).get("enabled", False):
        src.flagged.append("管理员不受旧版保护约束")
    rpr = d.get("required_pull_request_reviews")
    if rpr:
        allow = rpr.get("bypass_pull_request_allowances") or {}
        for a in allow.get("apps", []):
            src.blocked.append("app %s" % a.get("slug"))
        for t in allow.get("teams", []):
            src.blocked.append("team %s" % t.get("slug"))
        for u in allow.get("users", []):
            src.flagged.append("user %s" % u.get("login"))
        provided["pull_request_required"].append(src)
    if not d.get("allow_force_pushes", {}).get("enabled", True):
        provided["no_force_push"].append(src)
    if not d.get("allow_deletions", {}).get("enabled", True):
        provided["no_deletion"].append(src)
    gives = [k for k, v in provided.items() if src in v]
    notes.append("旧版保护：%s" % (", ".join(gives) if gives else "无相关规则"))
    return None


def _rulesets(ctx: ProbeContext, branch: str, provided: Dict, unreadable: list, notes: list):
    r, failed = _fetch(ctx, "repos/%s/rules/branches/%s" % (ctx.repo_name, branch))
    if failed:
        return failed
    if not r.ok or not isinstance(r.data, list):
        unreadable.append("生效规则（%s）" % (r.message or r.status))
        return None
    by_id = {}  # type: Dict[Tuple[str, str, int], set]
    for rule in r.data:
        key = (rule.get("ruleset_source_type"), rule.get("ruleset_source"), rule.get("ruleset_id"))
        by_id.setdefault(key, set()).add(rule.get("type"))
    if not by_id:
        notes.append("规则集：无")
    for (stype, source, rid), types in sorted(by_id.items(), key=lambda kv: str(kv[0])):
        prefix = "orgs" if stype == "Organization" else "repos"
        d, failed = _fetch(ctx, "%s/%s/rulesets/%s" % (prefix, source, rid))
        if failed:
            return failed
        if not d.ok:
            unreadable.append("规则集 %s（%s）" % (rid, d.message or d.status))
            continue
        name = d.data.get("name", rid)
        if d.data.get("enforcement") != "active":
            notes.append("规则集「%s」处于 %s，不计" % (name, d.data.get("enforcement")))
            continue
        if "bypass_actors" not in d.data:
            unreadable.append("规则集「%s」的绕过名单（需要管理员权限）" % name)
            continue
        src = _Source("规则集「%s」" % name)
        for actor in d.data["bypass_actors"]:
            _classify_bypass(actor, src)
        gives = sorted(_RULE_TYPES[t] for t in types if t in _RULE_TYPES)
        for req in gives:
            provided[req].append(src)
        notes.append("%s（%s）：%s" % (src.label, d.data.get("enforcement"), ", ".join(gives) or "无相关规则"))
    return None


@runtime.register("github.effective_branch_rules")
def effective_branch_rules(params: Dict, ctx: ProbeContext) -> ProbeResult:
    blocked = _ready(ctx)
    if blocked:
        return blocked
    branch, required = params["branch"], params["require"]
    provided = {req: [] for req in _RULE_TYPES.values()}  # type: Dict[str, list]
    unreadable, notes = [], []  # type: list, list
    for step in (_legacy, _rulesets):
        failed = step(ctx, branch, provided, unreadable, notes)
        if failed:
            return failed

    missing, bypass_flags, evidence = [], [], list(notes)
    for req in required:
        sources = provided[req]
        clean = [s for s in sources if not s.blocked]
        if clean:
            if all(s.flagged for s in clean):
                bypass_flags.extend(f for s in clean for f in s.flagged)
            continue
        if sources:
            missing.append("%s 可被绕过：%s" % (req, "; ".join(
                "%s 的绕过名单含 %s" % (s.label, ", ".join(s.blocked)) for s in sources)))
        else:
            missing.append("%s 未生效" % req)
    if bypass_flags:
        evidence.append("存在绕过（只有管理员或个人账号）：%s" % ", ".join(sorted(set(bypass_flags))))
    if missing:
        if unreadable:
            return ProbeResult(status="unknown", evidence=evidence,
                               error="无法读取 %s；已读到的部分不足以判定：%s" % ("、".join(unreadable), "；".join(missing)))
        return ProbeResult(status="gap", evidence=evidence, missing="; ".join(missing))
    return ProbeResult(status="met", evidence=evidence)
