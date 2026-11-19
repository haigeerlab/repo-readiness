"""Command-line entry point. Subcommands are registered here as they land."""

import argparse
import sys
from typing import List, Optional

from repo_readiness import __version__
from repo_readiness.proc import EXIT_ENV_NOT_READY, EXIT_FAIL, EXIT_OK, EXIT_USAGE


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


def _github_client(args: argparse.Namespace):
    from repo_readiness.platform.github import GitHub, LiveTransport, RecordingTransport, ReplayTransport
    if args.github_replay:
        return GitHub(ReplayTransport(args.github_replay))
    mode = args.github or ("live" if args.repo_name else "off")
    if mode == "off":
        return None
    transport = LiveTransport()
    if args.github_record:
        transport = RecordingTransport(transport, args.github_record)
    return GitHub(transport)


def _relative_path_ok(p: str) -> bool:
    from pathlib import PurePosixPath
    pure = PurePosixPath(p)
    return bool(p.strip()) and not pure.is_absolute() and ".." not in pure.parts


def _check(args: argparse.Namespace) -> int:
    import datetime
    import json
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
    from repo_readiness.detect.declarations import load_declarations
    if not _relative_path_ok(args.declaration):
        return _usage_error("--declaration must be a path relative to the repository root")
    decls = load_declarations(repo, args.declaration)
    category = args.category or (decls.category if not decls.error else None)
    if category and ruleset.categories and category not in ruleset.categories:
        return _usage_error("category %r (%s) is not a category of %s (categories: %s)"
                            % (category, "--category" if args.category else decls.path, ruleset.id,
                               ", ".join(ruleset.categories)))
    registry = risk_templates = None
    if args.registry:
        try:
            names = json.loads(Path(args.registry).read_text(encoding="utf-8"))
            names = names.get("agents", names) if isinstance(names, dict) else names
            registry = frozenset(n if isinstance(n, str) else n.get("name") for n in names)
        except (OSError, ValueError, AttributeError, TypeError) as e:
            return _usage_error("--registry: cannot read a JSON list of agent names: %s" % e)
    if args.risk_templates:
        from repo_readiness.yamlsub import YamlSubsetError, load as load_yaml
        try:
            risk_templates = load_yaml(args.risk_templates)
        except (OSError, YamlSubsetError, UnicodeDecodeError) as e:
            return _usage_error("--risk-templates: %s" % e)
    app_specs = list(args.app or [])
    if not app_specs and not decls.error:
        for app_id, spec in decls.apps().items():
            if isinstance(spec, dict) and isinstance(spec.get("path"), str):
                extra = [g for g in spec.get("paths") or [] if isinstance(g, str)]
                app_specs.append("%s=%s" % (app_id, ",".join([spec["path"]] + extra)))
    apps = {}  # app id -> root directory (where app-scoped probes look)
    app_paths = {}  # app id -> globs mapping files to the app (root/** first)
    for spec in app_specs:
        app_id, sep, rest = spec.partition("=")
        parts = rest.split(",") if rest else []
        if not sep or not app_id or not parts:
            return _usage_error("--app expects NAME=ROOT[,GLOB...], got %r" % spec)
        if app_id in apps:
            return _usage_error("--app %r given twice" % app_id)
        for part in parts:
            if not _relative_path_ok(part):
                return _usage_error("--app %r: %r must be a non-empty path relative to the repository root, "
                                    "without '..'" % (app_id, part))
        root = parts[0].rstrip("/")
        apps[app_id] = root
        app_paths[app_id] = [root + "/**"] + parts[1:]
    try:
        now = _now(args.now)
    except ValueError:
        return _usage_error("--now expects YYYY-MM-DDTHH:MM:SSZ, got %r" % args.now)
    try:
        as_of = datetime.date.fromisoformat(args.as_of) if args.as_of else now.date()
    except ValueError:
        return _usage_error("--as-of expects YYYY-MM-DD, got %r" % args.as_of)

    github = _github_client(args)
    sc = scan(ruleset, repo, category=category, apps=apps, github=github, repo_name=args.repo_name, now=now,
              declarations=decls, registry=registry, risk_templates=risk_templates)
    if decls.error:
        sc.errors.append({"clause": "*", "target": "repo", "message": decls.error})
    outcomes = {(r.clause, r.target): Outcome(r.status, waiver_until=datetime.date.fromisoformat(r.waiver_until)
                                              if r.waiver_until else None) for r in sc.results}
    result = score(ruleset, outcomes, apps=list(apps), today=as_of)
    report = rpt.build(ruleset, sc, result, repo_path=repo.resolve(), repo_name=args.repo_name,
                       head=rpt.git_head(repo) if (repo / ".git").exists() else None,
                       category=category, apps=apps, app_paths=app_paths, as_of=as_of,
                       min_tier=args.min_tier)
    text = rpt.summary(report, ruleset)
    rpt.write(report, text, Path(args.out))
    sys.stdout.write(text)
    if sc.env_errors:
        for msg in sc.env_errors:
            print("environment not ready: %s" % msg, file=sys.stderr)
        print("results that depend on it are unknown; fix the environment and re-run", file=sys.stderr)
        return EXIT_ENV_NOT_READY
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
    check.add_argument("--app", action="append", metavar="NAME=ROOT[,GLOB...]",
                       help="monorepo 的应用：ROOT 是应用目录（应用级探针在此查找），其后可加通配符，"
                            "与 ROOT/** 一起把文件对应到应用；可重复")
    check.add_argument("--repo-name", help="owner/name，写进报告")
    check.add_argument("--declaration", default=".github/autopr/readiness.yml",
                       help="仓库自评文件（相对仓库根），默认 .github/autopr/readiness.yml；类别与应用在未给参数时取自它")
    check.add_argument("--registry", metavar="FILE", help="本机信箱已登记的通信名（JSON 数组），用于核对 owner")
    check.add_argument("--risk-templates", metavar="FILE", help="风险分档的类别模板（YAML），用于核对 R1")
    check.add_argument("--min-tier", help="达到这一档退出 0，否则退出 1")
    check.add_argument("--github", choices=["live", "off"],
                       help="是否只读访问 GitHub（经 gh api，仅 GET）；给了 --repo-name 时默认 live，否则 off")
    check.add_argument("--github-record", metavar="DIR", help="把 GitHub 返回录制到 DIR（用于测试夹具）")
    check.add_argument("--github-replay", metavar="DIR", help="只用 DIR 里录制的 GitHub 返回，不联网")
    check.add_argument("--now", help="检测时刻（UTC，YYYY-MM-DDTHH:MM:SSZ），用于按小时滚动的时间窗口；默认当前时间")
    check.add_argument("--as-of", help="按这一天（YYYY-MM-DD）判断豁免与生效日期，默认今天（UTC）")
    check.set_defaults(func=_check)

    conc = sub.add_parser("conclude", help="从一份完整的检测报告签发接入结论")
    conc.add_argument("report", help="report.json 路径")
    conc.add_argument("--default-branch", required=True, help="被测仓库的默认分支名")
    conc.add_argument("--repo-name", help="owner/name；报告里没有时必须给")
    conc.add_argument("--out", required=True, help="写出的结论文件路径")
    conc.add_argument("--now", help="签发时间（UTC，YYYY-MM-DDTHH:MM:SSZ），默认当前时间；用于复现")
    conc.set_defaults(func=_conclude)

    cgroup = sub.add_parser("conclusion", help="接入结论相关命令")
    csub = cgroup.add_subparsers(dest="conclusion_command", metavar="<subcommand>")
    ver = csub.add_parser("verify", help="核对结论与报告是否一致、是否过期")
    ver.add_argument("conclusion", help="结论文件路径")
    ver.add_argument("--report", required=True, help="结论所依据的 report.json")
    ver.add_argument("--now", help="按这一时刻判断是否过期（UTC，YYYY-MM-DDTHH:MM:SSZ）")
    ver.set_defaults(func=_conclusion_verify)
    return parser


def _now(arg: Optional[str]):
    import datetime

    from repo_readiness.conclusion import parse_ts
    return parse_ts(arg) if arg else datetime.datetime.now(datetime.timezone.utc)


def _conclude(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    from repo_readiness.conclusion import ConclusionError, conclude
    try:
        now = _now(args.now)
    except ValueError:
        return _usage_error("--now expects YYYY-MM-DDTHH:MM:SSZ, got %r" % args.now)
    try:
        raw = Path(args.report).read_bytes()
    except OSError as e:
        return _usage_error("cannot read report: %s" % e)
    try:
        c = conclude(raw, default_branch=args.default_branch, now=now, repo_name=args.repo_name)
    except ConclusionError as e:
        for p in e.problems:
            print("error: %s" % p, file=sys.stderr)
        print("no conclusion issued", file=sys.stderr)
        return EXIT_FAIL
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("conclusion: %s @ %s · %s（%s）· valid until %s" % (
        c["repo"], c["head"][:7], c["tier"]["name"], c["trust_cap"], c["valid_until"]))
    return EXIT_OK


def _conclusion_verify(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    from repo_readiness.conclusion import verify
    try:
        now = _now(args.now)
    except ValueError:
        return _usage_error("--now expects YYYY-MM-DDTHH:MM:SSZ, got %r" % args.now)
    try:
        conclusion = json.loads(Path(args.conclusion).read_text(encoding="utf-8"))
        raw = Path(args.report).read_bytes()
    except (OSError, ValueError) as e:
        return _usage_error("cannot read input: %s" % e)
    problems = verify(conclusion, raw, now=now)
    for p in problems:
        print("error: %s" % p, file=sys.stderr)
    if problems:
        return EXIT_FAIL
    print("ok: conclusion matches report and is valid until %s" % conclusion["valid_until"])
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)  # argparse exits 2 on bad usage
    func = getattr(args, "func", None)
    if func is None:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    return func(args)
