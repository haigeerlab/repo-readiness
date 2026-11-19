"""The repository's self-assessment (readiness.yml, the standard's template) and how it affects results.

File shape (YAML subset): top-level `category`, `owner`, `apps`, and sections such as
`general`, `basic`, `standard_tier`, `high` whose entries are keyed by clause id:

    basic:
      R2: { status: met, evidence: "docs/rollback.md" }
      E1: { status: na, reason: "...", approved-by: "user" }
      G9: { status: waived, reason: "...", until: 2027-01-31, approved-by: "user" }

Effects (applied after probing, and only when the probe did not already find the clause met):
- na:     allowed only if the clause has na_allowed; needs reason + approved-by when
          na_justification_required; otherwise the result is gap with the reason;
- waived: needs reason + until (YYYY-MM-DD) + approved-by; scoring then checks expiry,
          waiver.max_days and non_waivable.
`met` / `gap` declarations are read by the `declare` probe. Entries are repo-level in v1.
"""

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from repo_readiness.yamlsub import YamlSubsetError, load

__all__ = ["DEFAULT_PATH", "Declaration", "Declarations", "apply", "load_declarations"]

DEFAULT_PATH = ".github/autopr/readiness.yml"
STATUSES = ("met", "gap", "na", "waived")


@dataclass
class Declaration:
    status: Any
    evidence: Optional[str] = None
    plan: Optional[str] = None
    reason: Optional[str] = None
    until: Optional[str] = None
    approved_by: Optional[str] = None

    @property
    def problems(self) -> List[str]:
        if self.status not in STATUSES:
            return ["status %r is not one of %s" % (self.status, ", ".join(STATUSES))]
        return []


@dataclass
class Declarations:
    path: str
    exists: bool = False
    error: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    entries: Dict[str, Declaration] = field(default_factory=dict)

    @property
    def category(self) -> Optional[str]:
        c = self.data.get("category")
        return c if isinstance(c, str) else None

    def apps(self) -> Dict[str, Dict[str, Any]]:
        apps = self.data.get("apps")
        return apps if isinstance(apps, dict) else {}


def _text(v: Any) -> Optional[str]:
    return None if v is None else str(v)


def load_declarations(repo_root: Path, rel: str = DEFAULT_PATH) -> Declarations:
    d = Declarations(path=rel)
    p = repo_root / rel
    if not p.is_file():
        return d
    d.exists = True
    try:
        data = load(p)
    except (YamlSubsetError, OSError, UnicodeDecodeError) as e:
        d.error = "cannot read %s: %s" % (rel, e)
        return d
    if not isinstance(data, dict):
        d.error = "%s is not a mapping" % rel
        return d
    d.data = data
    for section in data.values():
        if not isinstance(section, dict):
            continue
        for key, entry in section.items():
            if isinstance(entry, dict) and "status" in entry:
                d.entries[key] = Declaration(
                    status=entry.get("status"), evidence=_text(entry.get("evidence")), plan=_text(entry.get("plan")),
                    reason=_text(entry.get("reason")), until=_text(entry.get("until")),
                    approved_by=_text(entry.get("approved-by", entry.get("approved_by"))))
    return d


def apply(clause, result, decls: Optional[Declarations]):
    """Adjust a ClauseResult with the clause's n/a or waiver declaration. Returns the result."""
    if decls is None or result.status in ("met", "na"):
        return result
    entry = decls.entries.get(clause.id)
    if entry is None or entry.status not in ("na", "waived"):
        return result
    where = decls.path
    if entry.status == "na":
        if not clause.na_allowed:
            return _gap(result, "N/A is not allowed for %s (declared in %s)" % (clause.id, where))
        if clause.na_justification_required and (not entry.reason or not entry.approved_by):
            return _gap(result, "N/A for %s needs reason and approved-by (%s)" % (clause.id, where))
        result.status = "na"
        result.evidence = ["declared N/A in %s: %s%s" % (where, entry.reason or "(no reason needed)",
                                                        " (approved-by %s)" % entry.approved_by if entry.approved_by else "")]
        result.missing = result.error = None
        return result
    missing = [f for f, v in (("reason", entry.reason), ("until", entry.until), ("approved-by", entry.approved_by)) if not v]
    if missing:
        return _gap(result, "waiver for %s needs %s (%s)" % (clause.id, ", ".join(missing), where))
    try:
        datetime.date.fromisoformat(entry.until)
    except ValueError:
        return _gap(result, "waiver for %s has until %r, expected YYYY-MM-DD (%s)" % (clause.id, entry.until, where))
    result.status = "waived"
    result.waiver_until = entry.until
    result.evidence = result.evidence + ["waived in %s until %s: %s (approved-by %s)"
                                         % (where, entry.until, entry.reason, entry.approved_by)]
    result.error = None
    return result


def _gap(result, why: str):
    result.status = "gap"
    result.missing = why if not result.missing else "%s; %s" % (why, result.missing)
    result.error = None
    return result
