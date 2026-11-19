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

__all__ = ["ClauseFileError", "Clause", "Level", "Ruleset", "Tier", "lint_data", "load"]

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
        return ["kind 'stack' rulesets can only be checked together with a base ruleset (not supported yet)"]

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
    ids = set()  # type: set
    for c in data["clauses"]:
        cid = c["id"]
        if cid in ids:
            problems.append("duplicate clause id %r" % cid)
        ids.add(cid)

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

    for cid in data.get("waiver", {}).get("non_waivable", []):
        if cid not in ids:
            problems.append("waiver.non_waivable: unknown clause id %r" % cid)
    return problems


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


def load(path: Union[str, Path]) -> Ruleset:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ClauseFileError(path, ["cannot read file: %s" % e])
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ClauseFileError(path, ["not valid JSON: %s" % e])
    problems = lint_data(data)
    if problems:
        raise ClauseFileError(path, problems)
    return Ruleset(
        id=data["id"], version=data["version"], kind=data["kind"], owner=data["owner"],
        sha256=hashlib.sha256(raw).hexdigest(),
        clauses=tuple(_clause(c) for c in data["clauses"]),
        tiers=tuple(Tier(t["id"], t["name"], t["rank"], t.get("trust_cap"), t.get("should")) for t in data["tiers"]),
        below_lowest=data["below_lowest"], gate=data["gate"], waiver=data.get("waiver", {}),
        categories=tuple(data.get("categories", [])), title=data.get("title"),
    )


def enforce_date(clause: Clause) -> Optional[datetime.date]:
    return datetime.date.fromisoformat(clause.enforce_from) if clause.enforce_from else None
