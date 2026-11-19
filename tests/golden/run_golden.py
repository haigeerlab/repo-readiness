"""Golden comparison: the tool vs assessment-v2.md (autopr-standard's manual first assessment, 2026-11-19).

Not part of the unit tests: it needs the network (read-only GitHub GETs and shallow clones of remote main).
Nothing in any repository is executed (no --exec-entries), so V1 / V2 are "not evaluated".

    python3 tests/golden/run_golden.py WORKDIR OUT.json

WORKDIR receives the clones (use a scratch directory). Local checkouts are never touched, except
session-protocol, which has no remote and is read in place.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from repo_readiness.clauses import load  # noqa: E402
from repo_readiness.detect.declarations import load_declarations  # noqa: E402
from repo_readiness.detect.engine import scan  # noqa: E402
from repo_readiness.platform.github import GitHub, LiveTransport  # noqa: E402
from repo_readiness.probes.runtime import ProbeContext, evaluate  # noqa: E402
from repo_readiness.proc import run  # noqa: E402

RULER = ROOT / "tests" / "fixtures" / "rulesets" / "autopr-onboarding-2.0-basic.trial.json"
LOCAL = Path("/Users/vilin/Documents/haigeerlab")
TEMPLATES = Path("/Users/vilin/Documents/haigeerlab/plugin-ecosystem/.claude/worktrees/auto-pr-prompt-review-8c3133/"
                 "research/2026-11-18-自动PR系统设计/config/risk-tiers.categories.example.yml")

# assessment-v2.md §1 (G1-G6, V1, E1) and §2 (G9), transcribed cell by cell.
# met / gap / na / unknown ("?" in the assessment) / None (not assessed, "—").
# ⚠️ cells are transcribed as gap and annotated: G2 ⚠️ = "PR not required"; V1 ⚠️ = "no single command".
EXPECTED = {
    #                        G1       G2     G3     G4     G5     G6     V1        E1      G9
    "pwa-platform":        ("frontend", "met", "met", "met", "met", "met", "met", "met", "met", "met"),
    "agent-relay":         ("plugin", "met", "gap", "met", "met", "met", "met", "met", "met", "met"),
    "spec-guard-plugin":   ("plugin", "met", "gap", "met", "met", "met", "met", "met", "met", "gap"),
    "tab-leader":          ("frontend", "met", "gap", "met", "met", "met", "met", "gap", "met", "gap"),
    "sso-browser-sdk":     ("frontend", "met", "gap", "met", "gap", "met", "met", "met", "met", "gap"),
    "tier-guard":          ("plugin", "met", "gap", "gap", "gap", "met", "met", "met", "na", None),
    "delegate-plugin":     ("plugin", "met", "gap", "gap", "gap", "met", "met", "met", "na", None),
    "frontend-knowledge-tree": ("content", "met", "gap", "gap", "gap", "met", "met", "gap", "met", None),
    "module-crew":         ("plugin", "met", "gap", "gap", "gap", "met", "met", "gap", "na", None),
    "ai-dev-playbook":     ("content", "gap", "gap", "gap", "gap", "gap", "met", "gap", "na", None),
    "session-protocol":    ("contract", "gap", "gap", "gap", "gap", None, None, "unknown", "na", None),
    "decision-inbox":      ("plugin", "met", "gap", "gap", "gap", "gap", "met", "unknown", "na", None),
}
COLUMNS = ("G1", "G2", "G3", "G4", "G5", "G6", "V1", "E1", "G9")
NEW_REQUIREMENTS = ("G7", "D1", "R1")  # the assessment says all 12 lack these


def clone(repo: str, workdir: Path) -> Path:
    dest = workdir / repo
    if dest.exists():
        return dest
    r = run(["gh", "repo", "clone", "haigeerlab/%s" % repo, str(dest), "--", "--depth", "1", "-q"],
            cwd=workdir, timeout_s=300)
    if r.code != 0:
        raise SystemExit("clone %s failed: %s" % (repo, r.stderr.strip()))
    return dest


def main(workdir: str, out: str) -> int:
    workdir_p = Path(workdir)
    workdir_p.mkdir(parents=True, exist_ok=True)
    ruler = load(RULER)
    gh = GitHub(LiveTransport())
    from repo_readiness.yamlsub import load as load_yaml
    templates = load_yaml(TEMPLATES) if TEMPLATES.is_file() else None
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    results = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "ruler": ruler.version, "repos": {}}
    for repo, row in EXPECTED.items():
        category = row[0]
        path = LOCAL / repo if repo == "session-protocol" else clone(repo, workdir_p)
        head = run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"], cwd=path, timeout_s=30).stdout.strip()
        decls = load_declarations(path)  # same as `check`: the repository's readiness.yml, if any
        sc = scan(ruler, path, category=category, github=gh, repo_name="haigeerlab/%s" % repo, now=now,
                  risk_templates=templates, declarations=decls)
        got = {r.clause: {"status": r.status, "missing": r.missing, "error": r.error, "evidence": r.evidence}
               for r in sc.results}
        g9 = evaluate({"use": "workflow.actions_pinned"}, ProbeContext(repo_root=path))
        got["G9"] = {"status": g9.status, "missing": g9.missing, "error": g9.error, "evidence": g9.evidence}
        results["repos"][repo] = {
            "head": head, "category": category, "source": "local checkout" if repo == "session-protocol" else "clone of remote main",
            "expected": dict(zip(COLUMNS, row[1:])), "got": got,
            "not_evaluated": sc.not_evaluated, "errors": sc.errors, "env_errors": sc.env_errors,
        }
        cells = []
        for col, exp in zip(COLUMNS, row[1:]):
            st = got.get(col, {}).get("status")
            cells.append("%s %s%s" % (col, st, "" if exp is None or exp == st else "≠" + exp))
        print("%-24s %s  %s" % (repo, head, " | ".join(cells)))
    Path(out).write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
