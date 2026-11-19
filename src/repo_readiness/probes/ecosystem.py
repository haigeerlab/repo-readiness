"""Ecosystem probes for E1, driven by the adapters in repo_readiness/adapters/*.json.

ecosystem.has_dependencies   -> met if any tracked manifest declares third-party dependencies
ecosystem.lockfile_installed -> each such manifest has a lockfile (its directory or a parent, within
                                the app) and CI installs that ecosystem from the lock

Manifests are looked up among git-tracked files (so node_modules and scratch files never count);
without git, a filesystem walk that skips vendored directories is used.
"""

import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from repo_readiness.probes import runtime
from repo_readiness.probes.runtime import ProbeContext, ProbeResult
from repo_readiness.probes.workflow import _jobs, _load_workflows, _norm, _steps
from repo_readiness.proc import run

ADAPTER_DIR = Path(__file__).resolve().parent.parent / "adapters"
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
_PIN = re.compile(r"^[A-Za-z0-9_.\-\[\],]+\s*==\s*[^\s;]+")


def adapters() -> List[Dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(ADAPTER_DIR.glob("*.json"))]


def _files(ctx: ProbeContext) -> List[str]:
    """Repository-relative POSIX paths under the context's base, tracked by git when possible."""
    prefix = (ctx.base.rstrip("/") + "/") if ctx.base else ""
    if (ctx.repo_root / ".git").exists():
        r = run(["git", "-C", str(ctx.repo_root), "ls-files", "-z"], cwd=ctx.repo_root, timeout_s=60)
        if r.code == 0:
            return [p for p in r.stdout.split("\0") if p and p.startswith(prefix)]
    out = []
    for dirpath, dirnames, filenames in os.walk(str(ctx.base_dir)):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        rel_dir = Path(dirpath).relative_to(ctx.repo_root).as_posix()
        out.extend(fn if rel_dir == "." else "%s/%s" % (rel_dir, fn) for fn in filenames)
    return out


# --------------------------------------------------------------------------- dependency parsers

def _requirement_lines(text: str) -> List[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.split(" #")[0].strip()
        if line and not line.startswith("#") and not line.startswith("-"):
            lines.append(line)
    return lines


def _python_deps(path: Path) -> Tuple[bool, Optional[str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    name = path.name
    if name.startswith("requirements"):
        return bool(_requirement_lines(text)), None
    if name == "pyproject.toml":
        m = re.search(r"^\s*dependencies\s*=\s*\[(.*?)\]", text, re.M | re.S)
        return bool(m and re.search(r"[\"']", m.group(1))), None
    if name == "Pipfile":
        m = re.search(r"^\[(?:dev-)?packages\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
        return bool(m and any(ln.strip() and not ln.strip().startswith("#") for ln in m.group(1).splitlines())), None
    return False, None


def _package_json_deps(path: Path) -> Tuple[bool, Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return False, "%s is not valid JSON: %s" % (path.name, e)
    keys = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
    return isinstance(data, dict) and any(isinstance(data.get(k), dict) and data.get(k) for k in keys), None


_PARSERS = {"package_json": _package_json_deps, "python": _python_deps}


def _manifests_with_deps(ctx: ProbeContext, files: List[str]) -> Tuple[Dict[str, List[str]], List[str]]:
    """{adapter id: [manifest paths with deps]}, errors."""
    found, errors = {}, []  # type: Dict[str, List[str]], List[str]
    for ad in adapters():
        names = set(ad["manifests"])
        for rel in files:
            if PurePosixPath(rel).name not in names:
                continue
            has, err = _PARSERS[ad["dependency_parser"]](ctx.repo_root / rel)
            if err:
                errors.append("%s: %s" % (rel, err))
            elif has:
                found.setdefault(ad["id"], []).append(rel)
    return found, errors


@runtime.register("ecosystem.has_dependencies")
def has_dependencies(params: Dict, ctx: ProbeContext) -> ProbeResult:
    files = _files(ctx)
    found, errors = _manifests_with_deps(ctx, files)
    if errors:
        return ProbeResult(status="unknown", error="cannot read dependency manifest(s): " + "; ".join(errors))
    if not found:
        names = sorted({n for ad in adapters() for n in ad["manifests"]})
        return ProbeResult(status="gap", missing="no third-party dependencies (looked for %s)" % ", ".join(names))
    return ProbeResult(status="met", evidence=["third-party dependencies in %s"
                                               % ", ".join("%s (%s)" % (m, a) for a, ms in sorted(found.items()) for m in ms)])


# --------------------------------------------------------------------------- locks and CI

def _parents(rel: str, base: str) -> List[str]:
    """Directories from the manifest's own up to the base (POSIX, '' = repo root)."""
    out, d = [], PurePosixPath(rel).parent
    stop = PurePosixPath(base.rstrip("/")) if base else PurePosixPath(".")
    while True:
        out.append("" if str(d) == "." else str(d))
        if d == stop or str(d) == ".":
            break
        d = d.parent
    return out


def _unpinned(path: Path) -> List[str]:
    lines = _requirement_lines(path.read_text(encoding="utf-8", errors="replace"))
    return [ln for ln in lines if not (_PIN.match(ln) or "--hash" in ln)]


def _lock_for(ad: Dict, manifest: str, files: set, ctx: ProbeContext) -> Tuple[Optional[str], Optional[str]]:
    """(lockfile found, problem)."""
    if ad.get("pinned_requirements") and PurePosixPath(manifest).name.startswith("requirements"):
        loose = _unpinned(ctx.repo_root / manifest)
        if loose:
            return None, "%s: not pinned: %s" % (manifest, ", ".join(loose[:5]))
        return manifest, None
    for d in _parents(manifest, ctx.base):
        for lock in ad["lockfiles"]:
            cand = "%s/%s" % (d, lock) if d else lock
            if cand in files:
                return cand, None
        if ad.get("pinned_requirements"):
            for f in files:
                p = PurePosixPath(f)
                if str(p.parent) == (d or ".") and p.name.startswith("requirements") and p.suffix == ".txt" \
                        and not _unpinned(ctx.repo_root / f):
                    return f, None
    return None, "%s has third-party dependencies but no lockfile (%s) in its directory or a parent" % (
        manifest, ", ".join(ad["lockfiles"]))


def _ci_installs_any(ad: Dict, workflows) -> bool:
    commands = [_norm(c) for c in ad.get("install_commands", [])]
    actions = set(ad.get("install_actions", []))
    for _, wf in workflows:
        for job in _jobs(wf):
            for s in _steps(job):
                text = _norm(str(s.get("run", ""))) + " "
                if any(c and c in text for c in commands):
                    return True
                uses = s.get("uses")
                if isinstance(uses, str) and uses.split("@")[0] in actions:
                    return True
    return False


def _ci_installs(ad: Dict, workflows) -> Optional[str]:
    commands = [_norm(c) for c in ad["frozen_commands"]]
    for name, wf in workflows:
        for job in _jobs(wf):
            for s in _steps(job):
                run_text = _norm(str(s.get("run", "")))
                for c in commands:
                    if c and c in run_text:
                        return "%s: `%s`" % (name, c)
                uses = s.get("uses")
                if isinstance(uses, str):
                    with_ = s.get("with") if isinstance(s.get("with"), dict) else {}
                    for act in ad.get("frozen_actions", []):
                        if uses.split("@")[0] == act["uses"] and all(with_.get(k) == v for k, v in act["with"].items()):
                            return "%s: uses %s with %s" % (name, act["uses"], act["with"])
    return None


@runtime.register("ecosystem.lockfile_installed")
def lockfile_installed(params: Dict, ctx: ProbeContext) -> ProbeResult:
    files = _files(ctx)
    found, errors = _manifests_with_deps(ctx, files)
    if errors:
        return ProbeResult(status="unknown", error="cannot read dependency manifest(s): " + "; ".join(errors))
    if not found:
        return ProbeResult(status="met", evidence=["no third-party dependencies, nothing to lock"])
    workflows, wf_errors = _load_workflows(ctx.repo_root)
    if wf_errors:
        return ProbeResult(status="unknown", error="cannot read workflow(s): " + "; ".join(wf_errors))
    by_id = {ad["id"]: ad for ad in adapters()}
    fileset = set(files)
    evidence, missing = [], []
    for ad_id, manifests in sorted(found.items()):
        ad = by_id[ad_id]
        for m in manifests:
            lock, problem = _lock_for(ad, m, fileset, ctx)
            if problem:
                missing.append(problem)
            else:
                evidence.append("%s locked by %s" % (m, lock))
        how = _ci_installs(ad, workflows)
        if how:
            evidence.append("CI installs %s dependencies from the lock (%s)" % (ad_id, how))
        elif not workflows:
            evidence.append("no CI workflow, so nothing installs %s dependencies; the lockfile alone fixes the "
                            "versions (missing CI is G3's finding)" % ad_id)
        elif _ci_installs_any(ad, workflows):
            missing.append("CI installs %s dependencies without the lockfile (use one of: %s)"
                           % (ad_id, "; ".join(ad["frozen_commands"])))
        else:
            evidence.append("CI does not install %s dependencies at all, so the lockfile alone fixes the versions"
                            % ad_id)
    if missing:
        return ProbeResult(status="gap", evidence=evidence, missing="; ".join(missing))
    return ProbeResult(status="met", evidence=evidence)
