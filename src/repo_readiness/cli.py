"""Command-line entry point. Subcommands are registered here as they land."""

import argparse
import sys
from typing import List, Optional

from repo_readiness import __version__
from repo_readiness.proc import EXIT_FAIL, EXIT_OK, EXIT_USAGE


def _clauses_lint(args: argparse.Namespace) -> int:
    from repo_readiness.clauses import ClauseFileError, load

    try:
        rs = load(args.file)
    except ClauseFileError as e:
        for p in e.problems:
            print("error: %s" % p, file=sys.stderr)
        print("%s: %d problem(s)" % (args.file, len(e.problems)), file=sys.stderr)
        return EXIT_USAGE
    print("ok: %s %s (%s, %d clauses, %d tiers, sha256 %s)"
          % (rs.id, rs.version, rs.kind, len(rs.clauses), len(rs.tiers), rs.sha256))
    return EXIT_OK


def _usage_error(msg: str) -> int:
    print("error: %s" % msg, file=sys.stderr)
    return EXIT_USAGE


def _check(args: argparse.Namespace) -> int:
    import datetime
    from pathlib import Path

    from repo_readiness import report as rpt
    from repo_readiness.clauses import ClauseFileError, load
    from repo_readiness.detect.engine import scan
    from repo_readiness.detect.score import Outcome, score

    repo = Path(args.repo)
    if not repo.is_dir():
        return _usage_error("repository path %s is not a directory" % repo)
    try:
        ruleset = load(args.clauses)
    except ClauseFileError as e:
        for p in e.problems:
            print("error: %s" % p, file=sys.stderr)
        return EXIT_USAGE
    tier_ids = [t.id for t in ruleset.tiers]
    if args.min_tier and args.min_tier not in tier_ids:
        return _usage_error("--min-tier %r is not a tier of %s (tiers: %s)"
                            % (args.min_tier, ruleset.id, ", ".join(tier_ids)))
    if args.category and ruleset.categories and args.category not in ruleset.categories:
        return _usage_error("--category %r is not a category of %s (categories: %s)"
                            % (args.category, ruleset.id, ", ".join(ruleset.categories)))
    apps = {}
    for spec in args.app or []:
        app_id, sep, path = spec.partition("=")
        if not sep or not app_id or not path:
            return _usage_error("--app expects NAME=PATH, got %r" % spec)
        if app_id in apps:
            return _usage_error("--app %r given twice" % app_id)
        apps[app_id] = path.rstrip("/")
    try:
        as_of = datetime.date.fromisoformat(args.as_of) if args.as_of else datetime.datetime.now(datetime.timezone.utc).date()
    except ValueError:
        return _usage_error("--as-of expects YYYY-MM-DD, got %r" % args.as_of)

    sc = scan(ruleset, repo, category=args.category, apps=apps)
    outcomes = {(r.clause, r.target): Outcome(r.status) for r in sc.results}
    result = score(ruleset, outcomes, apps=list(apps), today=as_of)
    report = rpt.build(ruleset, sc, result, repo_path=repo.resolve(), repo_name=args.repo_name,
                       head=rpt.git_head(repo) if (repo / ".git").exists() else None,
                       category=args.category, apps=apps, as_of=as_of, min_tier=args.min_tier)
    text = rpt.summary(report, ruleset)
    rpt.write(report, text, Path(args.out))
    sys.stdout.write(text)
    if args.min_tier and not report["target"]["met"]:
        return EXIT_FAIL
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-readiness",
        description="按条款文件检测仓库就绪度、给出修复、复检并出接入结论。",
    )
    parser.add_argument("--version", action="version", version="repo-readiness %s" % __version__)
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    clauses = sub.add_parser("clauses", help="条款文件（尺子）相关命令")
    clauses_sub = clauses.add_subparsers(dest="clauses_command", metavar="<subcommand>")
    lint = clauses_sub.add_parser("lint", help="校验一份条款文件")
    lint.add_argument("file", help="条款文件路径（JSON）")
    lint.set_defaults(func=_clauses_lint)

    check = sub.add_parser("check", help="按尺子检测一个仓库（只读），写出 report.json 和 summary.md")
    check.add_argument("repo", help="被测仓库的本地路径")
    check.add_argument("--clauses", required=True, help="条款文件路径")
    check.add_argument("--out", required=True, help="输出目录（写 report.json、summary.md）")
    check.add_argument("--category", help="仓库类别，例如 plugin、frontend")
    check.add_argument("--app", action="append", metavar="NAME=PATH", help="monorepo 的应用及其路径前缀，可重复")
    check.add_argument("--repo-name", help="owner/name，写进报告")
    check.add_argument("--min-tier", help="达到这一档退出 0，否则退出 1")
    check.add_argument("--as-of", help="按这一天（YYYY-MM-DD）判断豁免与生效日期，默认今天（UTC）")
    check.set_defaults(func=_check)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)  # argparse exits 2 on bad usage
    func = getattr(args, "func", None)
    if func is None:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return func(args)
