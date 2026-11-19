"""Onboarding conclusions: issue one from a report, and verify a conclusion against its report.

A conclusion is only issued from a complete report: valid against report.v1,
no probe errors, no pending agent judgments, a known head commit and repo
name, and produced by a committed, clean checkout of this tool (the
self-maintenance firewall: consumers match tool version + commit against an
allow-list, which is meaningless for uncommitted code).

Unknown outcomes do not block a conclusion: they already count as gaps in the
tier, so the conclusion is conservative by construction.
"""

import datetime
import hashlib
import json
from typing import Any, Dict, List, Optional

from repo_readiness.resources import schema_validator

__all__ = ["ConclusionError", "VALIDITY", "conclude", "verify"]

VALIDITY = datetime.timedelta(days=14)


class ConclusionError(ValueError):
    def __init__(self, problems: List[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _ts(t: datetime.datetime) -> str:
    return t.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: str) -> datetime.datetime:
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def conclude(report_bytes: bytes, *, default_branch: str, now: datetime.datetime,
             repo_name: Optional[str] = None) -> Dict[str, Any]:
    try:
        report = json.loads(report_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ConclusionError(["report is not valid JSON: %s" % e])
    schema_problems = schema_validator("report.v1").errors(report)
    if schema_problems:
        raise ConclusionError(["report does not match report.v1: %s" % p for p in schema_problems[:5]])

    problems = []  # type: List[str]
    if report["errors"]:
        problems.append("report has %d probe error(s); fix or re-run before concluding" % len(report["errors"]))
    if report["judgment_requests"]:
        problems.append("report has %d pending judgment request(s)" % len(report["judgment_requests"]))
    head = report["repo"]["head"]
    if not head:
        problems.append("report has no head commit (was the repository a git checkout?)")
    name = repo_name or report["repo"]["name"]
    if not name:
        problems.append("report has no repo name; pass it explicitly (owner/name)")
    if not default_branch:
        problems.append("default branch is required")
    tool = report["tool"]
    if not tool["commit"]:
        problems.append("report was produced by a tool without a known commit")
    elif tool["dirty"] is not False:
        problems.append("report was produced by a tool checkout with uncommitted changes")
    if problems:
        raise ConclusionError(problems)

    waivers = [{"clause": r["clause"], "target": r["target"], "until": r["waiver_until"]}
               for r in report["results"] if r["status"] == "waived" and r.get("waiver_until")]
    conclusion = {
        "schema": "repo-readiness.conclusion/v1",
        "repo": name,
        "default_branch": default_branch,
        "head": head,
        "tier": {"id": report["tier"]["id"], "name": report["tier"]["name"]},
        "trust_cap": report["tier"]["trust_cap"],
        "apps": [{"id": a["id"], "paths": a["paths"], "tier": a["tier"], "trust_cap": a["trust_cap"]}
                 for a in report["apps"]],
        "basis": {
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "rulesets": report["rulesets"],
            "tool": {"version": tool["version"], "commit": tool["commit"]},
        },
        "issued_at": _ts(now),
        "valid_until": _ts(now + VALIDITY),
        "declarations_expire_at": None,
        "waivers": waivers,
        "attestation": {"method": "none"},
    }
    own = schema_validator("conclusion.v1").errors(conclusion)
    if own:
        raise ConclusionError(["conclusion does not match conclusion.v1: %s" % p for p in own[:5]])
    return conclusion


def verify(conclusion: Any, report_bytes: bytes, *, now: datetime.datetime) -> List[str]:
    """Problems found; an empty list means the pair is consistent and the conclusion is current."""
    problems = ["conclusion does not match conclusion.v1: %s" % p for p in schema_validator("conclusion.v1").errors(conclusion)]
    if problems:
        return problems
    if hashlib.sha256(report_bytes).hexdigest() != conclusion["basis"]["report_sha256"]:
        return ["report sha256 does not match basis.report_sha256 (report changed or wrong file)"]
    report = json.loads(report_bytes.decode("utf-8"))
    expect = {
        "head": report["repo"]["head"],
        "tier.id": report["tier"]["id"],
        "trust_cap": report["tier"]["trust_cap"],
        "basis.tool.commit": report["tool"]["commit"],
    }
    actual = {
        "head": conclusion["head"],
        "tier.id": conclusion["tier"]["id"],
        "trust_cap": conclusion["trust_cap"],
        "basis.tool.commit": conclusion["basis"]["tool"]["commit"],
    }
    for k in expect:
        if expect[k] != actual[k]:
            problems.append("%s is %r in the conclusion but %r in the report" % (k, actual[k], expect[k]))
    def app_key(a):
        return (a["id"], a["paths"], a["tier"], a["trust_cap"])
    if [app_key(a) for a in conclusion["apps"]] != [app_key(a) for a in report["apps"]]:
        problems.append("apps differ between conclusion and report")
    if now >= parse_ts(conclusion["valid_until"]):
        problems.append("conclusion expired at %s" % conclusion["valid_until"])
    return problems
