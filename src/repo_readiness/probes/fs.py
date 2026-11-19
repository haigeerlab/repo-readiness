"""File probes: exists, glob, contains. Read-only, and never outside the repository."""

import re
from pathlib import Path, PurePosixPath
from typing import Dict, Optional, Tuple

from repo_readiness.probes import runtime
from repo_readiness.probes.runtime import ProbeContext, ProbeResult

MAX_BYTES = 2 * 1024 * 1024  # files larger than this are not scanned by fs.contains


def _resolve(rel: str, ctx: ProbeContext) -> Tuple[Optional[Path], Optional[str]]:
    """Map a ruler path to a real path inside the repository, or explain why not."""
    pure = PurePosixPath(rel)
    if pure.is_absolute() or ".." in pure.parts:
        return None, "path %r must be relative and must not contain '..'" % rel
    root = ctx.repo_root.resolve()
    candidate = ctx.base_dir / pure
    try:
        real = candidate.resolve()
    except OSError as e:
        return None, "cannot resolve %r: %s" % (rel, e)
    if real != root and root not in real.parents:
        return None, "path %r resolves outside the repository" % rel
    return candidate, None


def _shown(path: Path, ctx: ProbeContext) -> str:
    return path.relative_to(ctx.repo_root).as_posix()


@runtime.register("fs.exists")
def exists(params: Dict, ctx: ProbeContext) -> ProbeResult:
    p, err = _resolve(params["path"], ctx)
    if err:
        return ProbeResult(status="unknown", error=err)
    if p.exists():
        return ProbeResult(status="met", evidence=["found %s" % _shown(p, ctx)])
    return ProbeResult(status="gap", missing="%s not found" % _shown(p, ctx))


@runtime.register("fs.glob")
def glob(params: Dict, ctx: ProbeContext) -> ProbeResult:
    pattern = params["pattern"]
    _, err = _resolve(pattern.replace("*", "x"), ctx)
    if err:
        return ProbeResult(status="unknown", error=err)
    want = params.get("min", 1)
    root = ctx.repo_root.resolve()
    hits = []
    for p in sorted(ctx.base_dir.glob(pattern)):
        rel = p.relative_to(ctx.repo_root)
        if ".git" in rel.parts or not p.is_file():
            continue
        try:
            real = p.resolve()
        except OSError:
            continue
        if root not in real.parents:
            continue
        hits.append(rel.as_posix())
    where = (ctx.base + "/" if ctx.base else "") + pattern
    if len(hits) >= want:
        shown = ", ".join(hits[:3]) + (" …" if len(hits) > 3 else "")
        return ProbeResult(status="met", evidence=["%d file(s) match %s: %s" % (len(hits), where, shown)])
    return ProbeResult(status="gap", missing="%d file(s) match %s, need %d" % (len(hits), where, want))


@runtime.register("fs.contains")
def contains(params: Dict, ctx: ProbeContext) -> ProbeResult:
    p, err = _resolve(params["path"], ctx)
    if err:
        return ProbeResult(status="unknown", error=err)
    try:
        rx = re.compile(params["pattern"])
    except re.error as e:
        return ProbeResult(status="unknown", error="bad pattern %r: %s" % (params["pattern"], e))
    shown = _shown(p, ctx)
    if not p.is_file():
        return ProbeResult(status="gap", missing="%s not found" % shown)
    if p.stat().st_size > MAX_BYTES:
        return ProbeResult(status="unknown", error="%s is larger than %d bytes" % (shown, MAX_BYTES))
    text = p.read_text(encoding="utf-8", errors="replace")
    for n, line in enumerate(text.splitlines(), start=1):
        if rx.search(line):
            return ProbeResult(status="met", evidence=["%s:%d matches %r" % (shown, n, params["pattern"])])
    return ProbeResult(status="gap", missing="%s has no line matching %r" % (shown, params["pattern"]))
