"""Probe runtime: evaluate a clause's probe expression against one target.

A probe returns met / gap / unknown, plus evidence (what it saw) and, for a
gap, what is missing. Probes never return n/a: applicability is decided
before the probe runs (categories and the `applies.when` probe).

Combinators:
- all: any definite gap -> gap; otherwise any unknown -> unknown; else met.
- any: any met -> met; otherwise any unknown -> unknown; else gap.
- then: the follow-up runs only when the first probe is met; its result decides.

A probe that is declared in the catalog but not implemented in this version
yields unknown and is reported, so a ruler can never "pass" on a check the
tool cannot actually perform.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from repo_readiness.probes.catalog import CATALOG

__all__ = ["HarnessError", "ProbeContext", "ProbeResult", "evaluate", "register"]


class HarnessError(Exception):
    """A problem with the test harness (e.g. a missing recording). Never swallowed into "unknown"."""


@dataclass(frozen=True)
class ProbeContext:
    repo_root: Path
    base: str = ""  # path prefix of the app being judged, relative to repo_root ("" = repo)
    github: Optional[Any] = None  # platform.github.GitHub, or None when GitHub access is off
    repo_name: Optional[str] = None  # owner/name on GitHub
    now: Optional[Any] = None  # datetime (UTC) of the check; time-window probes need it
    declarations: Optional[Any] = None  # detect.declarations.Declarations (readiness.yml)
    registry: Optional[Any] = None  # frozenset of registered mailbox agent names, or None if not provided
    risk_templates: Optional[Any] = None  # parsed category risk templates, or None if not provided
    exec_entries: bool = False  # run interface.yml entries (executes repository code; opt-in)

    @property
    def base_dir(self) -> Path:
        return self.repo_root / self.base if self.base else self.repo_root


@dataclass
class ProbeResult:
    status: str  # met | gap | unknown
    evidence: List[str] = field(default_factory=list)
    missing: Optional[str] = None
    error: Optional[str] = None
    not_implemented: List[str] = field(default_factory=list)
    env_error: bool = False  # could not look (GitHub unreachable, not logged in, ...), not "the repo lacks it"
    skipped: List[str] = field(default_factory=list)  # not evaluated in this run by choice (an input was not given)


ProbeFn = Callable[[Dict, ProbeContext], ProbeResult]
_IMPLEMENTATIONS = {}  # type: Dict[str, ProbeFn]


def register(name: str) -> Callable[[ProbeFn], ProbeFn]:
    if name not in CATALOG:
        raise KeyError("probe %r is not declared in the catalog" % name)

    def deco(fn: ProbeFn) -> ProbeFn:
        _IMPLEMENTATIONS[name] = fn
        return fn
    return deco


def _merge(results: List[ProbeResult], status: str, missing: Optional[str] = None) -> ProbeResult:
    out = ProbeResult(status=status, missing=missing)
    errors = []
    for r in results:
        out.evidence.extend(r.evidence)
        out.not_implemented.extend(n for n in r.not_implemented if n not in out.not_implemented)
        if r.error:
            errors.append(r.error)
        out.env_error = out.env_error or r.env_error
        out.skipped.extend(x for x in r.skipped if x not in out.skipped)
    out.error = "; ".join(errors) or None
    return out


def evaluate(expr: Dict, ctx: ProbeContext) -> ProbeResult:
    if "all" in expr:
        rs = [evaluate(e, ctx) for e in expr["all"]]
        if any(r.status == "gap" for r in rs):
            return _merge(rs, "gap", "; ".join(r.missing for r in rs if r.status == "gap" and r.missing) or None)
        return _merge(rs, "unknown" if any(r.status == "unknown" for r in rs) else "met")
    if "any" in expr:
        rs = [evaluate(e, ctx) for e in expr["any"]]
        if any(r.status == "met" for r in rs):
            return _merge([r for r in rs if r.status == "met"], "met")
        if any(r.status == "unknown" for r in rs):
            return _merge(rs, "unknown")
        return _merge(rs, "gap", "none of: " + "; ".join(r.missing for r in rs if r.missing))

    name = expr["use"]
    fn = _IMPLEMENTATIONS.get(name)
    if fn is None:
        first = ProbeResult(status="unknown", error="probe %r is not implemented in this version" % name,
                            not_implemented=[name])
    else:
        try:
            first = fn(expr.get("with", {}), ctx)
        except HarnessError:
            raise
        except Exception as e:  # a probe bug must never turn into "met" or "gap"
            first = ProbeResult(status="unknown", error="probe %s crashed: %s: %s" % (name, type(e).__name__, e))
    if "then" not in expr or first.status != "met":
        return first
    second = evaluate(expr["then"], ctx)
    merged = _merge([first, second], second.status, second.missing)
    return merged


# Import implementations so they register themselves.
from repo_readiness.probes import config, ecosystem, entry, fs, github, workflow  # noqa: E402,F401  (registration side effect)
