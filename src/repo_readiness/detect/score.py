"""Gate rules: turn per-clause outcomes into tiers. Pure: no files, no network.

Terminology
- target: where a clause was judged: "repo", or an app id for app-scoped clauses.
- unit:   what gets a tier: each app (repo-scoped results + that app's results),
          or the repo itself when there are no apps. The repo tier is the
          minimum over units (app_aggregation = "min").

Rules (from the ruler's gate):
- must: every applicable must of the tier is met (or validly waived);
- should: the tier's should rule (ratio with floor/ceil, or max_missing);
- n/a leaves both counts; more than half n/a among a tier's musts -> not reached
  when na_majority = "not-reached" (the standard hands that case to the user);
- unknown and missing outcomes count as gap but are listed separately;
- waivers: must have an end date, not be past it, not exceed waiver.max_days
  from today, and not target a non_waivable clause; otherwise they count as gap;
- enforce_from in the future: the clause counts as a should at its must tiers;
- lifecycle future / obsolete: not scored at all;
- cumulative: a tier needs every lower tier.
"""

import datetime
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from repo_readiness.clauses import Clause, Ruleset

__all__ = ["Outcome", "TierCheck", "UnitScore", "Score", "score"]

REPO = "repo"
_STATUSES = ("met", "gap", "na", "waived", "unknown")


@dataclass(frozen=True)
class Outcome:
    status: str  # met | gap | na | waived | unknown
    waiver_until: Optional[datetime.date] = None

    def __post_init__(self):
        if self.status not in _STATUSES:
            raise ValueError("unknown status %r" % self.status)


@dataclass
class TierCheck:
    tier: str
    reached: bool = False
    must_total: int = 0
    must_met: int = 0
    must_na: int = 0
    must_failed: List[str] = field(default_factory=list)
    should_applicable: int = 0
    should_met: int = 0
    should_required: int = 0  # for max_missing: applicable - max_missing (floored at 0)
    should_failed: List[str] = field(default_factory=list)
    na_majority: bool = False
    grace: List[str] = field(default_factory=list)  # musts counted as should before enforce_from

    @property
    def must_ok(self) -> bool:
        return not self.must_failed

    @property
    def should_ok(self) -> bool:
        return self.should_met >= self.should_required


@dataclass
class UnitScore:
    unit: str
    tier: Optional[str]
    checks: List[TierCheck]


@dataclass
class Score:
    tier: Optional[str]
    units: List[UnitScore]
    unknown: List[Tuple[str, str]]
    invalid_waivers: List[Tuple[str, str, str]]
    next_tier: Optional[TierCheck]


def _should_required(rule: Dict, applicable: int) -> int:
    if rule["rule"] == "ratio":
        x = rule["ratio"] * applicable
        # guard float noise such as 0.8 * 5 = 4.000000000000001
        x = round(x, 9)
        return math.ceil(x) if rule.get("rounding") == "ceil" else math.floor(x)
    return max(0, applicable - rule["max_missing"])


def score(ruleset: Ruleset, outcomes: Dict[Tuple[str, str], Outcome], *,
          apps: Sequence[str] = (), today: datetime.date) -> Score:
    clauses = [c for c in ruleset.clauses if c.lifecycle == "active"]
    max_days = ruleset.waiver.get("max_days")
    non_waivable = set(ruleset.waiver.get("non_waivable", []))
    unknown = []  # type: List[Tuple[str, str]]
    invalid = []  # type: List[Tuple[str, str, str]]
    effective = {}  # type: Dict[Tuple[str, str], str]  # met | gap | na

    def resolve(c: Clause, target: str) -> str:
        key = (c.id, target)
        if key in effective:
            return effective[key]
        o = outcomes.get(key)
        status = o.status if o else "unknown"
        if status == "unknown":
            unknown.append(key)
            status = "gap"
        elif status == "waived":
            reason = None
            if c.id in non_waivable:
                reason = "not waivable"
            elif o.waiver_until is None:
                reason = "no end date"
            elif o.waiver_until < today:
                reason = "expired"
            elif max_days is not None and (o.waiver_until - today).days > max_days:
                reason = "longer than %d days" % max_days
            if reason:
                invalid.append((c.id, target, reason))
                status = "gap"
            else:
                status = "met"
        effective[key] = status
        return status

    def strength_at(c: Clause, tier_id: str) -> Optional[str]:
        for lv in c.levels:
            if lv.tier == tier_id:
                if lv.strength == "must" and c.enforce_from and datetime.date.fromisoformat(c.enforce_from) > today:
                    return "grace"
                return lv.strength
        return None

    units = list(apps) or [REPO]
    tiers = ruleset.ordered_tiers()
    unit_scores = []  # type: List[UnitScore]
    for unit in units:
        checks = []  # type: List[TierCheck]
        reached_so_far = True
        reached_tier = None
        for t in tiers:
            chk = TierCheck(tier=t.id)
            shoulds = []  # type: List[Tuple[str, str]]
            for c in clauses:
                strength = strength_at(c, t.id)
                if strength is None:
                    continue
                target = unit if (c.scope == "app" and apps) else REPO
                status = resolve(c, target)
                if strength == "must":
                    chk.must_total += 1
                    if status == "na":
                        chk.must_na += 1
                    elif status == "met":
                        chk.must_met += 1
                    else:
                        chk.must_failed.append(c.id)
                else:
                    if strength == "grace":
                        chk.grace.append(c.id)
                    shoulds.append((c.id, status))
            applicable = [(cid, s) for cid, s in shoulds if s != "na"]
            chk.should_applicable = len(applicable)
            chk.should_met = sum(1 for _, s in applicable if s == "met")
            chk.should_failed = [cid for cid, s in applicable if s != "met"]
            chk.should_required = _should_required(ruleset.should_rule(t.id), chk.should_applicable)
            if ruleset.gate.get("na_majority", "not-reached") == "not-reached" and chk.must_na * 2 > chk.must_total:
                chk.na_majority = True
            chk.reached = reached_so_far and chk.must_ok and chk.should_ok and not chk.na_majority
            reached_so_far = chk.reached
            if chk.reached:
                reached_tier = t.id
            checks.append(chk)
        unit_scores.append(UnitScore(unit=unit, tier=reached_tier, checks=checks))

    rank = {t.id: t.rank for t in tiers}

    def unit_rank(u: UnitScore) -> int:
        return rank[u.tier] if u.tier else 0

    lowest = min(unit_scores, key=unit_rank)
    next_check = next((chk for chk in lowest.checks if not chk.reached), None)
    order = {c.id: i for i, c in enumerate(ruleset.clauses)}
    unknown.sort(key=lambda k: (order[k[0]], k[1]))
    return Score(tier=lowest.tier, units=unit_scores, unknown=unknown,
                 invalid_waivers=invalid, next_tier=next_check)
