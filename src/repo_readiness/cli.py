"""Command-line entry point. Subcommands are registered here as they land."""

import argparse
import sys
from typing import List, Optional

from repo_readiness import __version__
from repo_readiness.proc import EXIT_USAGE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-readiness",
        description="按条款文件检测仓库就绪度、给出修复、复检并出接入结论。",
    )
    parser.add_argument("--version", action="version", version="repo-readiness %s" % __version__)
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)  # argparse exits 2 on bad usage
    if args.command is None:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return EXIT_USAGE
