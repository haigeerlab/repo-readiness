"""entry.run: run an interface.yml entry per the interface contract (V1, V2). Opt-in (--exec-entries).

This is the only probe that executes code from the repository under test, so it:
- runs only when ctx.exec_entries is on; otherwise the clause is "not evaluated", not an error;
- runs the committed HEAD in a throwaway `git clone --shared` in a temp dir (the source checkout,
  including its .git, is never written; uncommitted changes are not part of the run);
- passes a scrubbed environment (a few basics + AUTOPR_*), so tokens such as GH_TOKEN never reach it;
- closes stdin and enforces timeout_minutes;
- afterwards requires HEAD and tracked files to be unchanged (untracked build outputs are fine).

Exit codes (interface contract): 0 met, 1 gap (the code is at fault), 3 or timeout -> environment
not ready, anything else -> the entry itself is broken (unknown, reported as a probe error).
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from repo_readiness.probes import runtime
from repo_readiness.probes.runtime import ProbeContext, ProbeResult
from repo_readiness.proc import run
from repo_readiness.resources import schema_validator
from repo_readiness.yamlsub import YamlSubsetError, load

INTERFACE = ".github/autopr/interface.yml"
_SAFE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "LOGNAME", "SHELL", "TERM")
_GIT_TIMEOUT = 60


def _git(repo: Path, *args: str) -> Optional[str]:
    r = run(["git", "-C", str(repo)] + list(args), cwd=repo, timeout_s=_GIT_TIMEOUT)
    return r.stdout.strip() if r.code == 0 else None


def _tail(text: str, n: int = 5) -> List[str]:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-n:]


@runtime.register("entry.run")
def run_entry(params: Dict, ctx: ProbeContext) -> ProbeResult:
    entry, mode = params["entry"], params.get("mode", "full")
    if not ctx.exec_entries:
        reason = "entry execution is off for this run; pass --exec-entries to run interface.yml entries"
        return ProbeResult(status="unknown", error=reason, skipped=[reason])

    iface_path = ctx.repo_root / INTERFACE
    if not iface_path.is_file():
        return ProbeResult(status="gap", missing="%s not found, so there is no %s entry to run" % (INTERFACE, entry))
    try:
        iface = load(iface_path)
    except (YamlSubsetError, UnicodeDecodeError) as e:
        return ProbeResult(status="gap", missing="%s does not parse: %s" % (INTERFACE, e))
    spec = ((iface or {}).get("entries") or {}).get(entry) if isinstance(iface, dict) else None
    if not isinstance(spec, dict) or not isinstance(spec.get("run"), str):
        return ProbeResult(status="gap", missing="%s registers no %s entry" % (INTERFACE, entry))
    key = "run" if mode == "full" else "changed"
    command = spec.get(key)
    if not isinstance(command, str) or not command.strip():
        return ProbeResult(status="gap", missing="%s entry %s has no %r command" % (INTERFACE, entry, key))

    head = _git(ctx.repo_root, "rev-parse", "--verify", "HEAD")
    if not head:
        return ProbeResult(status="unknown", error="%s is not a git checkout with a commit to run" % ctx.repo_root)
    base = _git(ctx.repo_root, "rev-parse", "--verify", "HEAD~1") or head
    command = command.replace("{base}", base)
    try:
        timeout_s = float(spec.get("timeout_minutes", 15)) * 60
    except (TypeError, ValueError):
        return ProbeResult(status="gap", missing="%s entry %s: timeout_minutes is not a number" % (INTERFACE, entry))
    native = spec.get("report") == "native"

    with tempfile.TemporaryDirectory(prefix="repo-readiness-entry-") as tmp:
        tmp = Path(tmp)
        work = tmp / "work"
        clone = run(["git", "clone", "-q", "--shared", "--no-checkout", str(ctx.repo_root), str(work)],
                    cwd=tmp, timeout_s=_GIT_TIMEOUT)
        if clone.code != 0 or _git(work, "checkout", "-q", "--detach", head) is None:
            return ProbeResult(status="unknown", error="could not make a throwaway clone at %s: %s"
                               % (head[:7], clone.stderr.strip()[:300]))
        report_path, evidence_dir = tmp / "report.json", tmp / "evidence"
        evidence_dir.mkdir()
        env = {k: os.environ[k] for k in _SAFE_ENV if k in os.environ}
        env.update({"AUTOPR": "1", "AUTOPR_ENTRY": entry, "AUTOPR_REPORT": str(report_path), "AUTOPR_HEAD": head,
                    "AUTOPR_BASE": base, "AUTOPR_EVIDENCE_DIR": str(evidence_dir)})
        r = run(["/bin/sh", "-c", command], cwd=work, timeout_s=timeout_s, env=env)
        ev = ["ran %s %s `%s` at %s in a throwaway clone: %s" % (
            entry, mode, command, head[:7], "timeout" if r.timed_out else "exit %d" % r.code)]
        tail = _tail(r.stdout + "\n" + r.stderr)
        if tail:
            ev.append("output (last lines): " + " | ".join(tail))
        if r.timed_out:
            return ProbeResult(status="unknown", env_error=True, evidence=ev,
                               error="%s: timeout after %.0fs (environment not ready)" % (entry, timeout_s))
        if _git(work, "rev-parse", "HEAD") != head:
            return ProbeResult(status="unknown", evidence=ev, error="%s moved HEAD (entries must not commit or "
                                                                    "switch branches)" % entry)
        changed = _git(work, "status", "--porcelain", "--untracked-files=no")
        if changed:
            return ProbeResult(status="unknown", evidence=ev, error="%s modified tracked files: %s"
                               % (entry, ", ".join(ln[3:] for ln in changed.splitlines()[:5])))
        if r.code == 1:
            return ProbeResult(status="gap", evidence=ev, missing="%s: exit 1 (checks failed)" % entry)
        if r.code == 3:
            return ProbeResult(status="unknown", env_error=True, evidence=ev,
                               error="%s: exit 3 (environment not ready)" % entry)
        if r.code != 0:
            return ProbeResult(status="unknown", evidence=ev, error="%s: exit %d (the entry or its configuration "
                                                                    "is broken; not counted against the code)" % (entry, r.code))
        if native:
            problem = _check_native_report(report_path, head)
            if problem:
                return ProbeResult(status="unknown", evidence=ev, error=problem)
            ev.append("native report matches autopr.entry-report/v1")
        return ProbeResult(status="met", evidence=ev)


def _check_native_report(path: Path, head: str) -> Optional[str]:
    import json
    if not path.is_file():
        return "entry declares report: native but wrote no report to AUTOPR_REPORT"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return "entry report is not JSON: %s" % e
    errors = schema_validator("vendor/entry-report.v1").errors(data)
    if errors:
        return "entry report does not match entry-report v1: %s" % "; ".join(str(e) for e in errors[:3])
    if data.get("head") != head:
        return "entry report head %s does not match the commit that was run (%s)" % (data.get("head"), head)
    return None
