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
         registry: Optional[Any] = None, risk_templates: Optional[Any] = None) -> Scan:
    apps = apps or {}
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
                               declarations=declarations, registry=registry, risk_templates=risk_templates)
            res, probe = _judge_one(c, ctx, category)
            res.target = target
            res = apply_declaration(c, res, declarations)
            results.append(res)
            for name in probe.not_implemented:
                not_evaluated.append({"clause": c.id, "target": target,
                                      "reason": "probe %s is not implemented in this version" % name})
            if res.error and not probe.not_implemented:
                errors.append({"clause": c.id, "target": target, "message": res.error})
            if probe.env_error and res.error not in env_errors:
                env_errors.append(res.error)
    return Scan(results=results, not_evaluated=not_evaluated, errors=errors, env_errors=env_errors)
