"""Build the machine report (report.v1) and the one-screen human summary."""

import dataclasses
import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from repo_readiness import __version__
from repo_readiness.clauses import Ruleset
from repo_readiness.detect.engine import Scan
from repo_readiness.detect.score import Score, TierCheck
from repo_readiness.proc import run
from repo_readiness.resources import ROOT, schema_validator

__all__ = ["ReportError", "build", "summary", "write", "git_head", "tool_info"]

SUMMARY_MAX_LINES = 30


class ReportError(RuntimeError):
    """The report we built does not match our own schema: a bug in the tool."""


def git_head(path: Path) -> Optional[str]:
    r = run(["git", "-C", str(path), "rev-parse", "--verify", "HEAD"], cwd=path, timeout_s=15)
    head = r.stdout.strip()
    return head if r.code == 0 and len(head) == 40 else None


def tool_info() -> Dict[str, Any]:
    commit = git_head(ROOT) if (ROOT / ".git").exists() else None
    dirty = None
    if commit:
        r = run(["git", "-C", str(ROOT), "status", "--porcelain"], cwd=ROOT, timeout_s=15)
        dirty = bool(r.stdout.strip()) if r.code == 0 else None
    return {"name": "repo-readiness", "version": __version__, "commit": commit, "dirty": dirty}


def _check(chk: TierCheck) -> Dict[str, Any]:
    return dataclasses.asdict(chk)


def build(ruleset: Ruleset, scan: Scan, score: Score, *, repo_path: Path, repo_name: Optional[str],
          head: Optional[str], category: Optional[str], apps: Dict[str, str], as_of: datetime.date,
          min_tier: Optional[str], now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if score.tier:
        t = ruleset.tier(score.tier)
        tier_ref = {"id": t.id, "name": t.name, "trust_cap": t.trust_cap}
    else:
        tier_ref = {"id": None, "name": ruleset.below_lowest["name"], "trust_cap": ruleset.below_lowest.get("trust_cap")}
    unit_tier = {u.unit: u.tier for u in score.units}
    report = {
        "schema": "repo-readiness.report/v1",
        "tool": tool_info(),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": as_of.isoformat(),
        "repo": {"path": str(repo_path), "name": repo_name, "head": head},
        "rulesets": [{"id": ruleset.id, "kind": ruleset.kind, "version": ruleset.version, "sha256": ruleset.sha256}],
        "category": category,
        "apps": [{"id": a, "path": p, "tier": unit_tier.get(a)} for a, p in apps.items()],
        "tier": tier_ref,
        "next_tier": _check(score.next_tier) if score.next_tier else None,
        "units": [{"unit": u.unit, "tier": u.tier, "checks": [_check(c) for c in u.checks]} for u in score.units],
        "results": [{"clause": r.clause, "target": r.target, "status": r.status, "evidence": r.evidence,
                     "missing": r.missing, "error": r.error, "source": r.source, "fingerprint": r.fingerprint}
                    for r in scan.results],
        "unknown": [{"clause": c, "target": t} for c, t in score.unknown],
        "invalid_waivers": [{"clause": c, "target": t, "reason": why} for c, t, why in score.invalid_waivers],
        "not_evaluated": scan.not_evaluated,
        "errors": scan.errors,
        "judgment_requests": [],
        "baseline": None,
    }
    if min_tier:
        rank = {t.id: t.rank for t in ruleset.tiers}
        reached = rank.get(score.tier, 0) if score.tier else 0
        report["target"] = {"tier": min_tier, "met": reached >= rank[min_tier]}
    problems = schema_validator("report.v1").errors(report)
    if problems:
        raise ReportError("report does not match report.v1: %s" % "; ".join(str(p) for p in problems[:5]))
    return report


def summary(report: Dict[str, Any], ruleset: Ruleset) -> str:
    """Chinese one-screen summary (at most SUMMARY_MAX_LINES lines)."""
    name = report["repo"]["name"] or Path(report["repo"]["path"]).name
    head = report["repo"]["head"]
    tier = report["tier"]
    cap = "（%s）" % tier["trust_cap"] if tier["trust_cap"] else ""
    first = "%s @ %s · 尺子 %s %s · 当前：%s%s" % (
        name, head[:7] if head else "未提交", ruleset.id, ruleset.version, tier["name"], cap)
    if "target" in report:
        target = ruleset.tier(report["target"]["tier"]).name
        first += " · 目标：%s %s" % (target, "✓" if report["target"]["met"] else "✗")
    lines = [first]

    names = {t.id: t.name for t in ruleset.tiers}
    lowest = min(report["units"], key=lambda u: [c["reached"] for c in u["checks"]].count(True))
    for chk in lowest["checks"]:
        must_need = chk["must_total"] - chk["must_na"]
        lines.append("%s：必须 %d/%d · 建议 %d/%d（需 %d）%s" % (
            names[chk["tier"]], chk["must_met"], must_need, chk["should_met"], chk["should_applicable"],
            chk["should_required"], " ✓" if chk["reached"] else ""))
        if not chk["reached"]:
            break

    by_key = {(r["clause"], r["target"]): r for r in report["results"]}
    nxt = report["next_tier"]
    detail = []  # type: List[str]
    if nxt:
        detail.append("离%s还差：" % names[nxt["tier"]])
        target = lowest["unit"]
        for kind, ids in (("必须", nxt["must_failed"]), ("建议", nxt["should_failed"])):
            for cid in ids:
                r = by_key.get((cid, target)) or by_key.get((cid, "repo"))
                c = ruleset.clause(cid)
                if r and r["status"] == "unknown":
                    why = "无法判定：%s" % (r["error"] or "缺少结果")
                    mark = "?"
                else:
                    why = (r["missing"] if r else None) or "未满足"
                    mark = "✗"
                detail.append("  %s %s（%s）%s — %s" % (mark, cid, kind, c.requirement, why))
    if report["apps"]:
        detail.append("应用：" + " · ".join("%s %s" % (a["id"], names.get(a["tier"], ruleset.below_lowest["name"]))
                                            for a in report["apps"]))
    tail = "无法判定 %d 条 · 未评估 %d 条 · 探针错误 %d 条（详见 report.json）" % (
        len(report["unknown"]), len(report["not_evaluated"]), len(report["errors"]))

    room = SUMMARY_MAX_LINES - len(lines) - 1
    if len(detail) > room:
        hidden = len(detail) - (room - 1)
        detail = detail[: room - 1] + ["  …另有 %d 行，详见 report.json" % hidden]
    return "\n".join(lines + detail + [tail]) + "\n"


def write(report: Dict[str, Any], text: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(text, encoding="utf-8")
