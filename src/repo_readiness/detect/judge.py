"""Stage 2 of detect: hand judgment questions to an agent and take verdicts back, safely.

The tool never calls a model. It emits judgment requests; an agent answers in a judgments file.
A verdict is accepted only if
- it answers a request of this run (same clause, target and fingerprint), and
- its one-sentence evidence cites a file that exists in the repository (and, for path:line,
  a line that exists), so a verdict cannot rest on something invented.
With a baseline report, a clause whose evidence fingerprint is unchanged keeps its previous
verdict ("carried-over") instead of being asked again, which keeps judgments stable.
"""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["fingerprint", "request", "check_verdict", "index_verdicts", "previous_verdict"]

_CITE = re.compile(r"(?<![\w/.-])([A-Za-z0-9_][\w./-]*\.[A-Za-z0-9]+|[A-Za-z0-9_][\w.-]*/[\w./-]+)(?::(\d+))?")


def fingerprint(clause: str, target: str, evidence: List[str]) -> str:
    blob = json.dumps({"clause": clause, "target": target, "evidence": evidence}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def request(clause, target: str, evidence: List[str], question: str, fp: str) -> Dict[str, Any]:
    return {"clause": clause.id, "target": target, "requirement": clause.requirement, "guards": clause.guards,
            "question": question or clause.requirement, "evidence": list(evidence), "fingerprint": fp,
            "answer_with": "met or gap, plus one sentence citing path or path:line in the repository"}


def _citation_problem(text: str, repo_root: Path) -> Optional[str]:
    root = repo_root.resolve()
    seen_line_problem = None
    for m in _CITE.finditer(text):
        rel, line = m.group(1).rstrip("."), m.group(2)
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts:
            continue
        path = (repo_root / rel)
        try:
            real = path.resolve()
        except OSError:
            continue
        if root not in real.parents or not path.is_file():
            continue
        if line is None:
            return None
        n = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        if 1 <= int(line) <= n:
            return None
        seen_line_problem = "cited line %s is beyond %s (%d lines)" % (line, rel, n)
    return seen_line_problem or "no cited file exists in the repository (cite path or path:line)"


def check_verdict(verdict: Dict[str, Any], req: Optional[Dict[str, Any]], repo_root: Path) -> Optional[str]:
    """Why the verdict is rejected, or None when it is accepted."""
    if req is None:
        return "judgment for %s/%s was not requested in this run" % (verdict["clause"], verdict["target"])
    if verdict["fingerprint"] != req["fingerprint"]:
        return "judgment for %s/%s has a stale fingerprint (the evidence changed; judge the new request)" % (
            verdict["clause"], verdict["target"])
    problem = _citation_problem(verdict["evidence"], repo_root)
    if problem:
        return "judgment for %s/%s rejected: %s" % (verdict["clause"], verdict["target"], problem)
    return None


def index_verdicts(judgments: Optional[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    out = {}  # type: Dict[Tuple[str, str], Dict[str, Any]]
    for v in (judgments or {}).get("judgments", []):
        out[(v["clause"], v["target"])] = v
    return out


def previous_verdict(baseline: Optional[Dict[str, Any]], clause: str, target: str, fp: str) -> Optional[Dict[str, Any]]:
    """The baseline's judged result for this clause, if its evidence fingerprint is unchanged."""
    for r in (baseline or {}).get("results", []):
        if (r.get("clause"), r.get("target")) == (clause, target) and r.get("source") in ("judge", "carried-over") \
                and r.get("judge_fingerprint") == fp and r.get("status") in ("met", "gap"):
            return r
    return None
