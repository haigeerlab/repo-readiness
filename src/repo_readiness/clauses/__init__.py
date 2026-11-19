"""Clause files (rulers): load, check and expose them as plain data classes.

`lint_data` returns human-readable problems; an empty list means the ruler is
usable. `load` raises ClauseFileError carrying those problems, so nothing
downstream ever sees a ruler that failed lint.
"""

import datetime
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from repo_readiness.probes.catalog import CATALOG, param_validator
from repo_readiness.resources import schema_validator

__all__ = ["ClauseFileError", "Clause", "Level", "Ruleset", "Tier", "compose", "from_data", "lint_data", "load",
           "load_stack"]

DEFAULT_SHOULD = {"rule": "ratio", "ratio": 0.8, "rounding": "floor"}


class ClauseFileError(ValueError):
    def __init__(self, path: Union[str, Path], problems: List[str]):
        super().__init__("%s:\n  %s" % (path, "\n  ".join(problems)))
        self.problems = problems


@dataclass(frozen=True)
class Tier:
    id: str
    name: str
    rank: int
    trust_cap: Optional[str] = None
    should: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class Level:
    tier: str
    strength: str  # "must" | "should"


@dataclass(frozen=True)
class Clause:
    id: str
    requirement: str
    guards: str
    levels: Tuple[Level, ...]
    scope: str
    applies: Dict[str, Any]
    method: str
    probe: Dict[str, Any]
    layer: Optional[str] = None
    rationale: Optional[str] = None
    remedy: Optional[Dict[str, Any]] = None
    na_allowed: bool = True
    na_justification_required: bool = True
    since: Optional[str] = None
    enforce_from: Optional[str] = None
    lifecycle: str = "active"
    stack: Optional[str] = None  # set for clauses that come from a stack ruler
    tightened_by: Tuple[str, ...] = ()  # stacks that tightened this base clause


@dataclass(frozen=True)
class Ruleset:
    id: str
    version: str
    kind: str
    owner: str
    sha256: str
    clauses: Tuple[Clause, ...]
    tiers: Tuple[Tier, ...] = ()
    below_lowest: Dict[str, Any] = field(default_factory=dict)
    gate: Dict[str, Any] = field(default_factory=dict)
    waiver: Dict[str, Any] = field(default_factory=dict)
    categories: Tuple[str, ...] = ()
    title: Optional[str] = None
    drop: Dict[str, Any] = field(default_factory=dict)
    stack: Optional[str] = None  # kind=stack: the stack code
    detect: Dict[str, Any] = field(default_factory=dict)  # kind=stack: detection hints
    tighten: Tuple[Dict[str, Any], ...] = ()  # kind=stack: tightenings of base clauses
    parts: Tuple[Dict[str, Any], ...] = ()  # the files this ruler was composed from (base first)
    warnings: Tuple[str, ...] = ()

    def clause(self, clause_id: str) -> Clause:
        for c in self.clauses:
            if c.id == clause_id:
                return c
        raise KeyError(clause_id)

    def tier(self, tier_id: str) -> Tier:
        for t in self.tiers:
            if t.id == tier_id:
                return t
        raise KeyError(tier_id)

    def ordered_tiers(self) -> List[Tier]:
        return sorted(self.tiers, key=lambda t: t.rank)

    def should_rule(self, tier_id: str) -> Dict[str, Any]:
        rule = self.tier(tier_id).should or self.gate.get("should") or DEFAULT_SHOULD
        if rule["rule"] == "ratio":
            return dict({"rounding": "floor"}, **rule)
        return dict(rule)


# --------------------------------------------------------------------------- lint

def _walk_probes(expr: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    if "use" in expr:
        yield expr
        if "then" in expr:
            yield from _walk_probes(expr["then"])
    for key in ("all", "any"):
        for sub in expr.get(key, []):
            yield from _walk_probes(sub)


def _lint_probe(cid: str, where: str, expr: Dict[str, Any], out: List[str]) -> None:
    for p in _walk_probes(expr):
        name = p["use"]
        if name not in CATALOG:
            out.append("clause %s: %s uses unknown probe %r" % (cid, where, name))
            continue
        for e in param_validator(name).errors(p.get("with", {})):
            out.append("clause %s: %s probe %s parameters: %s" % (cid, where, name, str(e)))


def lint_data(data: Any) -> List[str]:
    problems = ["schema: %s" % str(e) for e in schema_validator("clauses.v1").errors(data)]
    if problems:
        return problems  # semantic checks assume the shape is right

    if data["kind"] == "stack":
        return ["kind 'stack' rulesets can only be checked together with a base ruleset "
                "(clauses lint STACK --base BASE)"]

    tiers = data["tiers"]
    rank_of = {}  # type: Dict[str, int]
    seen_ranks = set()
    for t in tiers:
        if t["id"] in rank_of:
            problems.append("duplicate tier id %r" % t["id"])
        if t["rank"] in seen_ranks:
            problems.append("duplicate tier rank %d" % t["rank"])
        rank_of[t["id"]] = t["rank"]
        seen_ranks.add(t["rank"])

    categories = set(data.get("categories", []))
    ids = _lint_clauses(data["clauses"], rank_of, categories, problems)

    for cid in data.get("waiver", {}).get("non_waivable", []):
        if cid not in ids:
            problems.append("waiver.non_waivable: unknown clause id %r" % cid)
    for cid in data.get("drop", {}).get("immediate", []):
        if cid not in ids:
            problems.append("drop.immediate: unknown clause id %r" % cid)
    return problems


def _lint_clauses(clauses: List[Dict[str, Any]], rank_of: Optional[Dict[str, int]], categories: set,
                  problems: List[str], taken: Optional[set] = None) -> set:
    """Per-clause checks; rank_of None skips tier checks (a stack ruler alone has no tiers)."""
    ids = set(taken or ())  # type: set
    for c in clauses:
        cid = c["id"]
        if cid in ids:
            problems.append("duplicate clause id %r" % cid if taken is None
                            else "clause %s is already defined (by the base or another stack)" % cid)
        ids.add(cid)
        if rank_of is None:
            _lint_probe(cid, "probe", c["probe"], problems)
            continue

        listed = set()  # type: set
        for lv in c["levels"]:
            if lv["tier"] not in rank_of:
                problems.append("clause %s: unknown tier %r in levels" % (cid, lv["tier"]))
            if lv["tier"] in listed:
                problems.append("clause %s: lists tier %r twice in levels" % (cid, lv["tier"]))
            listed.add(lv["tier"])
        known = sorted((lv for lv in c["levels"] if lv["tier"] in rank_of), key=lambda lv: rank_of[lv["tier"]])
        for lower, higher in zip(known, known[1:]):
            if lower["strength"] == "must" and higher["strength"] == "should":
                problems.append("clause %s: weakens from must (%s) to should (%s)" % (cid, lower["tier"], higher["tier"]))

        cats = c["applies"]["categories"]
        if cats != "*" and categories:
            for cat in cats:
                if cat not in categories:
                    problems.append("clause %s: unknown category %r" % (cid, cat))

        _lint_probe(cid, "probe", c["probe"], problems)
        if "when" in c["applies"]:
            _lint_probe(cid, "applies.when", c["applies"]["when"], problems)
    return ids


# --------------------------------------------------------------------------- load

def _clause(c: Dict[str, Any]) -> Clause:
    return Clause(
        id=c["id"], requirement=c["requirement"], guards=c["guards"],
        levels=tuple(Level(lv["tier"], lv["strength"]) for lv in c["levels"]),
        scope=c["scope"], applies=c["applies"], method=c["method"], probe=c["probe"],
        layer=c.get("layer"), rationale=c.get("rationale"), remedy=c.get("remedy"),
        na_allowed=c.get("na_allowed", True), na_justification_required=c.get("na_justification_required", True),
        since=c.get("since"), enforce_from=c.get("enforce_from"), lifecycle=c.get("lifecycle", "active"),
    )


def _read(path: Union[str, Path]) -> Tuple[Any, str]:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ClauseFileError(path, ["cannot read file: %s" % e])
    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, ValueError) as e:
        raise ClauseFileError(path, ["not valid JSON: %s" % e])


def load(path: Union[str, Path]) -> Ruleset:
    data, sha = _read(path)
    return from_data(data, sha256=sha, source=path)


def load_stack(path: Union[str, Path]) -> Ruleset:
    """A kind=stack ruler on its own: shape and probes only; tiers are checked by compose()."""
    data, sha = _read(path)
    problems = ["schema: %s" % str(e) for e in schema_validator("clauses.v1").errors(data)]
    if not problems and data["kind"] != "stack":
        problems.append("expected kind 'stack', got %r" % data["kind"])
    if not problems:
        _lint_clauses(data["clauses"], None, set(), problems)
    if problems:
        raise ClauseFileError(path, problems)
    return Ruleset(id=data["id"], version=data["version"], kind="stack", owner=data["owner"], sha256=sha,
                   clauses=tuple(_clause(c) for c in data["clauses"]), title=data.get("title"),
                   categories=tuple(data.get("categories", [])), stack=data["stack"],
                   detect=data.get("detect", {}), tighten=tuple(data.get("tighten", [])),
                   parts=({"id": data["id"], "kind": "stack", "version": data["version"], "sha256": sha,
                           "stack": data["stack"]},))


_STRENGTH = {"should": 0, "must": 1}
MAX_STACK_MUSTS = 2  # autopr-standard's content rule (#21538): a warning, not an error


def compose(base: Ruleset, stacks: List[Ruleset]) -> Ruleset:
    """Base + stack rulers -> one ruler. Stacks add clauses and may only tighten base clauses."""
    if not stacks:
        return base
    import dataclasses
    rank_of = {t.id: t.rank for t in base.tiers}
    clauses = {c.id: c for c in base.clauses}
    base_ids = set(clauses)
    problems, warnings, codes = [], [], set()  # type: List[str], List[str], set
    for st in stacks:
        if st.stack in codes:
            problems.append("stack %s is given twice" % st.stack)
        codes.add(st.stack)
        raw = [{"id": c.id, "levels": [{"tier": lv.tier, "strength": lv.strength} for lv in c.levels],
                "applies": c.applies, "probe": c.probe} for c in st.clauses]
        _lint_clauses(raw, rank_of, set(base.categories), problems, taken=set(clauses))
        for c in st.clauses:
            if c.id not in clauses:
                clauses[c.id] = dataclasses.replace(c, stack=st.stack)
        musts = sum(1 for c in st.clauses if any(lv.strength == "must" for lv in c.levels))
        if musts > MAX_STACK_MUSTS:
            warnings.append("stack %s has %d must clauses (the standard's limit is %d)" % (st.stack, musts, MAX_STACK_MUSTS))
        for t in st.tighten:
            cid = t["id"]
            if cid not in base_ids:
                problems.append("stack %s: tighten refers to unknown clause %r (only base clauses can be tightened)"
                                % (st.stack, cid))
                continue
            old = {lv.tier: lv.strength for lv in clauses[cid].levels}
            new = {}
            for lv in t["levels"]:
                if lv["tier"] not in rank_of:
                    problems.append("stack %s: tighten %s: unknown tier %r" % (st.stack, cid, lv["tier"]))
                new[lv["tier"]] = lv["strength"]
            loose = ["%s %s" % (tier, s) for tier, s in old.items() if _STRENGTH.get(new.get(tier), -1) < _STRENGTH[s]]
            if loose:
                problems.append("stack %s: tighten %s loosens it (drops or weakens: %s)" % (st.stack, cid, ", ".join(loose)))
                continue
            levels = tuple(Level(tier, s) for tier, s in sorted(new.items(), key=lambda kv: rank_of.get(kv[0], 99)))
            clauses[cid] = dataclasses.replace(clauses[cid], levels=levels,
                                               tightened_by=clauses[cid].tightened_by + (st.stack,))
    if problems:
        raise ClauseFileError("<composed ruler>", problems)
    order = [c.id for c in base.clauses] + [c.id for st in stacks for c in st.clauses if c.id not in base_ids]
    return dataclasses.replace(base, clauses=tuple(clauses[i] for i in order),
                               parts=base.parts + tuple(p for st in stacks for p in st.parts),
                               warnings=tuple(warnings))


def from_data(data: Any, sha256: str = "", source: Union[str, Path] = "<data>") -> Ruleset:
    """Build a Ruleset from already-parsed JSON (lints first, like load)."""
    problems = lint_data(data)
    if problems:
        raise ClauseFileError(source, problems)
    return Ruleset(
        id=data["id"], version=data["version"], kind=data["kind"], owner=data["owner"],
        sha256=sha256,
        clauses=tuple(_clause(c) for c in data["clauses"]),
        tiers=tuple(Tier(t["id"], t["name"], t["rank"], t.get("trust_cap"), t.get("should")) for t in data["tiers"]),
        below_lowest=data["below_lowest"], gate=data["gate"], waiver=data.get("waiver", {}),
        categories=tuple(data.get("categories", [])), title=data.get("title"), drop=data.get("drop", {}),
        parts=({"id": data["id"], "kind": data["kind"], "version": data["version"], "sha256": sha256},),
    )


def enforce_date(clause: Clause) -> Optional[datetime.date]:
    return datetime.date.fromisoformat(clause.enforce_from) if clause.enforce_from else None
