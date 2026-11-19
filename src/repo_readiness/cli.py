"""Command-line entry point. Subcommands are registered here as they land."""

import argparse
import sys
from typing import List, Optional

from repo_readiness import __version__
from repo_readiness.proc import EXIT_OK, EXIT_USAGE


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
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)  # argparse exits 2 on bad usage
    func = getattr(args, "func", None)
    if func is None:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return func(args)
