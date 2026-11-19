"""Recheck: failure streaks, the held tier and drop signals (at check time), and `diff` between two reports.

The judgment of "drop a tier" lives here and only here (agreed with autopr-design, #21530): the
pipeline consumes drop_signals and never compares reports itself.

At check time, with a baseline report:
- streak: consecutive "not met" (gap) results per clause/target; met / n/a / waived reset it to 0,
  unknown leaves it unchanged (drops only count "not met", #21538);
- a clause can drop the held tier only while it is an effective must (not in enforce_from grace)
  at a tier at or below the held tier;
- it drops when its streak reaches drop.consecutive_failures, or on its first failure if listed
  in drop.immediate; the held tier then falls exactly one tier;
- without a qualifying drop, a failure is in grace and the held tier stays; with no blocking
  failure the held tier follows the computed tier.
"""

import datetime
from typing import Any, Dict, List, Optional

from repo_readiness.clauses import Clause, Ruleset

__all__ = ["DEFAULT_DROP", "drop_rule", "compute", "diff"]

DEFAULT_DROP = {"consecutive_failures": 2, "immediate": []}


def drop_rule(ruleset: Ruleset) -> Dict[str, Any]:
    rule = dict(DEFAULT_DROP)
    rule.update(ruleset.drop or {})
    return {"consecutive_failures": rule["consecutive_failures"], "immediate": list(rule["immediate"])}


def _must_tiers(c: Clause, as_of: datetime.date) -> List[str]:
    if c.enforce_from and datetime.date.fromisoformat(c.enforce_from) > as_of:
        return []
    return [lv.tier for lv in c.levels if lv.strength == "must"]


def compute(ruleset: Ruleset, results, computed_tier: Optional[str], baseline: Optional[Dict[str, Any]],
            as_of: datetime.date) -> Dict[str, Any]:
    rule = drop_rule(ruleset)
    rank = {t.id: t.rank for t in ruleset.tiers}
    ordered = [t.id for t in ruleset.ordered_tiers()]
    old = {(s["clause"], s["target"]): s["count"] for s in (baseline or {}).get("failure_streaks", [])}
    streaks = []
    for r in results:
        prev = old.get((r.clause, r.target), 0)
        count = prev + 1 if r.status == "gap" else (prev if r.status == "unknown" else 0)
        if count:
            streaks.append({"clause": r.clause, "target": r.target, "count": count})

    if baseline is None:
        return {"failure_streaks": streaks, "held_tier": computed_tier, "drop_signals": [], "drop_rule": rule}
    base_held = baseline.get("held_tier", (baseline.get("tier") or {}).get("id"))
    if base_held not in rank:
        return {"failure_streaks": streaks, "held_tier": computed_tier, "drop_signals": [], "drop_rule": rule}

    by_id = {c.id: c for c in ruleset.clauses}
    count_of = {(s["clause"], s["target"]): s["count"] for s in streaks}
    signals, blocking = [], False
    below = ordered[ordered.index(base_held) - 1] if ordered.index(base_held) > 0 else None
    for r in results:
        c = by_id.get(r.clause)
        if c is None or r.status != "gap":
            continue
        if not any(rank[t] <= rank[base_held] for t in _must_tiers(c, as_of) if t in rank):
            continue
        blocking = True
        n = count_of.get((r.clause, r.target), 0)
        how = "immediate" if r.clause in rule["immediate"] else ("consecutive" if n >= rule["consecutive_failures"] else None)
        if how:
            signals.append({"clause": r.clause, "target": r.target, "rule": how, "streak": n,
                            "from_tier": base_held, "to_tier": below})
    if signals:
        held = below
    elif not blocking and (computed_tier is not None and rank[computed_tier] >= rank[base_held]):
        held = computed_tier
    else:
        held = base_held
    return {"failure_streaks": streaks, "held_tier": held, "drop_signals": signals, "drop_rule": rule}


# --------------------------------------------------------------------------- diff

def _status_map(report: Dict[str, Any]) -> Dict:
    return {(r["clause"], r["target"]): r["status"] for r in report["results"]}


def _expired(report: Dict[str, Any]) -> set:
    return {(w["clause"], w["target"]) for w in report.get("invalid_waivers", []) if w["reason"] == "expired"}


def diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    a, b = _status_map(old), _status_map(new)
    old_exp, new_exp = _expired(old), _expired(new)
    changes = []
    for key in sorted(set(a) | set(b)):
        before, after = a.get(key), b.get(key)
        newly_expired = key in new_exp and key not in old_exp
        if before == after and not newly_expired:
            continue
        if before is None or after is None:
            reason = "ruler"
        elif newly_expired:
            reason = "waiver-expired"
        elif after == "unknown":
            reason = "environment"
        else:
            reason = "repo"
        changes.append({"clause": key[0], "target": key[1], "from": before, "to": after, "reason": reason})

    order = [c["tier"] for c in (new["units"][0]["checks"] if new.get("units") else [])]
    rank = {t: i + 1 for i, t in enumerate(order)}
    t_old, t_new = old["tier"]["id"], new["tier"]["id"]
    r_old, r_new = rank.get(t_old, 0), rank.get(t_new, 0)
    direction = "same" if r_old == r_new else ("up" if r_new > r_old else "down")
    rulesets = lambda r: [(x["id"], x["version"], x["sha256"]) for x in r["rulesets"]]
    return {
        "schema": "repo-readiness.diff/v1",
        "old": {"generated_at": old["generated_at"], "head": old["repo"]["head"]},
        "new": {"generated_at": new["generated_at"], "head": new["repo"]["head"]},
        "ruler_changed": rulesets(old) != rulesets(new),
        "tier": {"from": t_old, "to": t_new, "direction": direction,
                 "reasons": sorted({c["reason"] for c in changes}) if direction != "same" else []},
        "held_tier": {"from": old.get("held_tier", t_old), "to": new.get("held_tier", t_new)},
        "changes": changes,
        "drop_signals": new.get("drop_signals", []),
        "new_unknown": [c for c in changes if c["to"] == "unknown"],
    }


def render(d: Dict[str, Any]) -> str:
    names = {"repo": "仓库变化", "ruler": "尺子变化", "waiver-expired": "豁免过期", "environment": "环境或权限"}
    arrow = {"up": "↑", "down": "↓", "same": "="}[d["tier"]["direction"]]
    lines = ["档位 %s → %s %s%s；持有档位 %s → %s" % (
        d["tier"]["from"] or "未达标", d["tier"]["to"] or "未达标", arrow,
        "（%s）" % "、".join(names[r] for r in d["tier"]["reasons"]) if d["tier"]["reasons"] else "",
        d["held_tier"]["from"] or "未达标", d["held_tier"]["to"] or "未达标")]
    if d["ruler_changed"]:
        lines.append("尺子变了：条款增删与仓库变化分开列出")
    for c in d["changes"]:
        lines.append("  %s/%s：%s → %s（%s）" % (c["clause"], c["target"], c["from"] or "—", c["to"] or "—", names[c["reason"]]))
    for s in d["drop_signals"]:
        lines.append("掉档信号：%s/%s %s（%s，连续 %d 次）→ 持有档位 %s → %s" % (
            s["clause"], s["target"], "一次就掉" if s["rule"] == "immediate" else "连续不满足", s["rule"], s["streak"],
            s["from_tier"], s["to_tier"] or "未达标"))
    if not d["changes"]:
        lines.append("  没有条款变化")
    return "\n".join(lines) + "\n"
