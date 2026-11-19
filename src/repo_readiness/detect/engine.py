"""Stage 1 of detection: run every active clause's probes against its targets.

Applicability is settled first (categories, then the `applies.when` probe);
only applicable clauses run their probe. The output feeds score.score().
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from repo_readiness.clauses import Clause, Ruleset
from repo_readiness.detect import judge
from repo_readiness.detect.declarations import apply as apply_declaration
from repo_readiness.detect.score import REPO
from repo_readiness.probes.runtime import ProbeContext, ProbeResult, evaluate

__all__ = ["ClauseResult", "Scan", "scan"]


@dataclass
class ClauseResult:
    clause: str
    target: str
    status: str  # met | gap | na | unknown
    evidence: List[str] = field(default_factory=list)
    missing: Optional[str] = None
    error: Optional[str] = None
    source: str = "scan"
    waiver_until: Optional[str] = None
    judge_fingerprint: Optional[str] = None

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({"status": self.status, "evidence": self.evidence, "missing": self.missing},
                          sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class Scan:
    results: List[ClauseResult]
    not_evaluated: List[Dict[str, str]]
    errors: List[Dict[str, str]]
    env_errors: List[str] = field(default_factory=list)  # the environment, not the repo, stopped a probe
    judgment_requests: List[Dict[str, Any]] = field(default_factory=list)


def _targets(c: Clause, apps: Dict[str, str]) -> List[Tuple[str, str]]:
    if c.scope == "app" and apps:
        return [(app_id, path) for app_id, path in apps.items()]
    return [(REPO, "")]


def _judge_one(c: Clause, ctx: ProbeContext, category: Optional[str]) -> Tuple[ClauseResult, ProbeResult]:
    target = REPO if not ctx.base else None  # filled by caller
    cats = c.applies["categories"]
    if cats != "*":
        if category is None:
            return ClauseResult(c.id, target, "unknown", error="repository category not declared; clause applies only to %s"
                                % ", ".join(cats)), ProbeResult("unknown")
        if category not in cats:
            return ClauseResult(c.id, target, "na", evidence=["category %s is not one of %s" % (category, ", ".join(cats))]), \
                ProbeResult("met")
    if "when" in c.applies:
        cond = evaluate(c.applies["when"], ctx)
        if cond.status == "gap":
            return ClauseResult(c.id, target, "na", evidence=["condition not met: %s" % (cond.missing or "")]), cond
        if cond.status == "unknown":
            return ClauseResult(c.id, target, "unknown", evidence=cond.evidence, error=cond.error), cond
    r = evaluate(c.probe, ctx)
    return ClauseResult(c.id, target, r.status, evidence=r.evidence, missing=r.missing, error=r.error), r


def scan(ruleset: Ruleset, repo_root: Path, *, category: Optional[str] = None,
         apps: Optional[Dict[str, str]] = None, github: Optional[Any] = None,
         repo_name: Optional[str] = None, now: Optional[Any] = None, declarations: Optional[Any] = None,
         registry: Optional[Any] = None, risk_templates: Optional[Any] = None,
         exec_entries: bool = False, judgments: Optional[Dict[str, Any]] = None,
         baseline: Optional[Dict[str, Any]] = None, stacks: Optional[Dict[str, Any]] = None) -> Scan:
    apps = apps or {}
    verdicts = judge.index_verdicts(judgments)
    requests = []  # type: List[Dict[str, Any]]
    results = []  # type: List[ClauseResult]
    not_evaluated = []  # type: List[Dict[str, str]]
    errors = []  # type: List[Dict[str, str]]
    env_errors = []  # type: List[str]
    for c in ruleset.clauses:
        if c.lifecycle != "active":
            not_evaluated.append({"clause": c.id, "reason": "lifecycle is %s" % c.lifecycle})
            continue
        for target, path in _targets(c, apps):
            ctx = ProbeContext(repo_root=repo_root, base=path, github=github, repo_name=repo_name, now=now,
                               declarations=declarations, registry=registry, risk_templates=risk_templates,
                               exec_entries=exec_entries)
            if c.stack and not _stack_applies(c.stack, target, stacks):
                res, probe = ClauseResult(c.id, target, "na", evidence=[
                    "stack %s is not used by this target (see report.stacks)" % c.stack]), ProbeResult("met")
            else:
                res, probe = _judge_one(c, ctx, category)
            res.target = target
            res = apply_declaration(c, res, declarations)
            if probe.judge_question is not None and res.status == "unknown" and not res.error:
                _settle_judgment(c, res, probe.judge_question, repo_root, verdicts, baseline, requests, errors)
            results.append(res)
            for name in probe.not_implemented:
                not_evaluated.append({"clause": c.id, "target": target,
                                      "reason": "probe %s is not implemented in this version" % name})
            for why in probe.skipped:
                not_evaluated.append({"clause": c.id, "target": target, "reason": why})
            if res.error and not probe.not_implemented and not probe.skipped:
                errors.append({"clause": c.id, "target": target, "message": res.error})
            if probe.env_error and res.error not in env_errors:
                env_errors.append(res.error)
    for (cid, target), v in verdicts.items():  # verdicts nobody asked for
        if not any(r["clause"] == cid and r["target"] == target for r in requests) and \
                not any(r.clause == cid and r.target == target and r.source == "judge" for r in results):
            errors.append({"clause": cid, "target": target, "message": judge.check_verdict(v, None, repo_root)})
    return Scan(results=results, not_evaluated=not_evaluated, errors=errors, env_errors=env_errors,
                judgment_requests=requests)


def _stack_applies(code: str, target: str, stacks: Optional[Dict[str, Any]]) -> bool:
    if stacks is None:
        return False
    if target != REPO:
        return code in stacks["apps"].get(target, stacks["used"])
    return code in stacks["used"] or any(code in v for v in stacks["apps"].values())


def _settle_judgment(c: Clause, res: ClauseResult, question: str, repo_root: Path, verdicts: Dict,
                     baseline: Optional[Dict], requests: List[Dict], errors: List[Dict]) -> None:
    fp = judge.fingerprint(c.id, res.target, res.evidence)
    res.judge_fingerprint = fp
    prev = judge.previous_verdict(baseline, c.id, res.target, fp)
    if prev is not None:
        res.status, res.source = prev["status"], "carried-over"
        res.evidence = res.evidence + [e for e in prev.get("evidence", []) if e.startswith("judged ")]
        res.missing = prev.get("missing")
        return
    req = judge.request(c, res.target, res.evidence, question, fp)
    v = verdicts.get((c.id, res.target))
    if v is not None:
        problem = judge.check_verdict(v, req, repo_root)
        if problem is None:
            res.status, res.source = v["status"], "judge"
            res.evidence = res.evidence + ["judged %s: %s" % (v["status"], v["evidence"])]
            res.missing = v["evidence"] if v["status"] == "gap" else None
            return
        errors.append({"clause": c.id, "target": res.target, "message": problem})
    requests.append(req)
