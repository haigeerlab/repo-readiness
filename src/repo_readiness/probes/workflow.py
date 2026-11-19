"""Static analysis of .github/workflows (nothing is executed). Backs G3, G6 (trigger part) and G9.

A workflow that cannot be read with the YAML subset makes these probes unknown:
a verdict about "all workflows" must not skip the ones we could not read.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from repo_readiness.probes import runtime
from repo_readiness.probes.runtime import ProbeContext, ProbeResult
from repo_readiness.yamlsub import YamlSubsetError, load

INTERFACE = ".github/autopr/interface.yml"
WRAPPER = "autopr-entry run --entry check"
_SHA = re.compile(r"@[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\Z")
_PRIVILEGED = {"pull_request_target", "workflow_run"}
_PR_CODE = ("github.event.pull_request.head", "github.head_ref", "github.event.workflow_run.head", "refs/pull/")


def _load_workflows(root: Path) -> Tuple[List[Tuple[str, Any]], List[str]]:
    wf_dir = root / ".github" / "workflows"
    files = sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))) if wf_dir.is_dir() else []
    loaded, errors = [], []
    for f in files:
        try:
            data = load(f)
        except (YamlSubsetError, OSError, UnicodeDecodeError) as e:
            errors.append("%s: %s" % (f.name, e))
            continue
        if not isinstance(data, dict):
            errors.append("%s: not a mapping" % f.name)
            continue
        loaded.append((f.name, data))
    return loaded, errors


def _triggers(wf: Dict) -> Set[str]:
    on = wf.get("on")
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {x for x in on if isinstance(x, str)}
    if isinstance(on, dict):
        return set(on)
    return set()


def _jobs(wf: Dict) -> List[Dict]:
    jobs = wf.get("jobs")
    return [j for j in jobs.values() if isinstance(j, dict)] if isinstance(jobs, dict) else []


def _steps(job: Dict) -> List[Dict]:
    steps = job.get("steps")
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def _norm(s: str) -> str:
    return " ".join(s.split())


def _unreadable(errors: List[str]) -> ProbeResult:
    return ProbeResult(status="unknown", error="cannot read workflow(s): %s" % "; ".join(errors))


@runtime.register("workflow.actions_pinned")
def actions_pinned(params: Dict, ctx: ProbeContext) -> ProbeResult:
    """G9: every third-party action / reusable workflow is pinned to a 40-character commit SHA."""
    wfs, errors = _load_workflows(ctx.repo_root)
    if errors:
        return _unreadable(errors)
    if not wfs:
        return ProbeResult(status="met", evidence=["no workflow files, so no actions to pin"])
    refs, unpinned = 0, []
    for name, wf in wfs:
        for job in _jobs(wf):
            uses = [job.get("uses")] + [s.get("uses") for s in _steps(job)]
            for u in uses:
                if not isinstance(u, str) or u.startswith("./"):
                    continue
                refs += 1
                if u.startswith("docker://"):
                    ok = bool(_DIGEST.search(u))
                else:
                    ok = bool(_SHA.search(u))
                if not ok and "%s: %s" % (name, u) not in unpinned:
                    unpinned.append("%s: %s" % (name, u))
    ev = ["%d external action / workflow reference(s) in %d workflow file(s)" % (refs, len(wfs))]
    if unpinned:
        return ProbeResult(status="gap", evidence=ev, missing="not pinned to a commit SHA: " + ", ".join(unpinned))
    return ProbeResult(status="met", evidence=ev)


@runtime.register("workflow.no_dangerous_triggers")
def no_dangerous_triggers(params: Dict, ctx: ProbeContext) -> ProbeResult:
    """G6 (workflow part): no privileged trigger that checks out or runs pull-request code."""
    wfs, errors = _load_workflows(ctx.repo_root)
    if errors:
        return _unreadable(errors)
    bad, privileged = [], []
    for name, wf in wfs:
        trig = _triggers(wf) & _PRIVILEGED
        if not trig:
            continue
        privileged.append("%s (%s)" % (name, ", ".join(sorted(trig))))
        for job in _jobs(wf):
            for s in _steps(job):
                with_ = s.get("with") if isinstance(s.get("with"), dict) else {}
                texts = [str(s.get("run", "")), str(with_.get("ref", "")), str(with_.get("repository", ""))]
                hit = next((p for p in _PR_CODE for t in texts if p in t), None)
                if hit:
                    bad.append("%s: %s step uses pull-request code (%s)" % (name, "/".join(sorted(trig)), hit))
    ev = ["privileged triggers: %s" % (", ".join(privileged) if privileged else "none")]
    if bad:
        return ProbeResult(status="gap", evidence=ev, missing="; ".join(bad))
    return ProbeResult(status="met", evidence=ev)


def _check_command(root: Path) -> Tuple[Optional[str], Optional[str]]:
    """(command, problem). command None + problem None = interface.yml absent."""
    path = root / INTERFACE
    if not path.is_file():
        return None, None
    try:
        data = load(path)
    except (YamlSubsetError, OSError, UnicodeDecodeError) as e:
        return None, "cannot read %s: %s" % (INTERFACE, e)
    run = (((data or {}).get("entries") or {}).get("check") or {}).get("run") if isinstance(data, dict) else None
    if not isinstance(run, str) or not run.strip():
        return None, None
    return run, None


@runtime.register("workflow.pr_runs_check")
def pr_runs_check(params: Dict, ctx: ProbeContext) -> ProbeResult:
    """G3: a pull_request-triggered workflow runs the check entry registered in interface.yml (or the wrapper)."""
    entry = params.get("entry", "check")
    wfs, errors = _load_workflows(ctx.repo_root)
    if errors:
        return _unreadable(errors)
    command, problem = _check_command(ctx.repo_root)
    if problem:
        return ProbeResult(status="unknown", error=problem)
    if not wfs:
        return ProbeResult(status="gap", missing="no workflow files")
    pr = [(name, wf) for name, wf in wfs if "pull_request" in _triggers(wf)]
    if not pr:
        return ProbeResult(status="gap", missing="no workflow runs on pull_request")
    ev = ["pull_request workflows: %s" % ", ".join(name for name, _ in pr)]
    if command is None:
        return ProbeResult(status="gap", evidence=ev, missing="%s does not register a %s entry, so CI cannot be shown "
                                                              "to run the same entry as local runs" % (INTERFACE, entry))
    want, wrapper = _norm(command), WRAPPER.replace("check", entry)
    for name, wf in pr:
        for job in _jobs(wf):
            for s in _steps(job):
                run = _norm(str(s.get("run", "")))
                if run and (want in run or wrapper in run):
                    ev.append("%s runs %s" % (name, wrapper if wrapper in run else "'%s'" % want))
                    return ProbeResult(status="met", evidence=ev)
    return ProbeResult(status="gap", evidence=ev, missing="no pull_request workflow step runs the registered %s "
                                                          "command '%s' (or %s)" % (entry, command, wrapper))
