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
