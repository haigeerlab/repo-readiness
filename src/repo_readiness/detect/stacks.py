"""Which stack rulers apply: the repository's declaration wins; detection only fills in or is shown.

readiness.yml:
    stacks: [SH]                                   # repository level
    apps:
      web: { path: "apps/web", stacks: [FE] }      # per app; an app without stacks uses the repo's

Detection (a stack ruler's `detect`: any_of / all_of / none_of file globs over tracked files)
is used only when nothing is declared anywhere. When something is declared, every difference
between declared and detected stacks is listed as "to confirm" and does not affect the score.
"""

from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from repo_readiness.probes.ecosystem import _files
from repo_readiness.probes.runtime import ProbeContext

__all__ = ["detect", "resolve"]


def _matches(files: List[str], pattern: str) -> bool:
    return any(PurePosixPath(f).match(pattern) for f in files)


def detect(repo_root: Path, stacks) -> List[str]:
    files = _files(ProbeContext(repo_root=repo_root))
    found = []
    for st in stacks:
        d = st.detect or {}
        if not d:
            continue
        ok = True
        if d.get("any_of"):
            ok = ok and any(_matches(files, p) for p in d["any_of"])
        if d.get("all_of"):
            ok = ok and all(_matches(files, p) for p in d["all_of"])
        if d.get("none_of"):
            ok = ok and not any(_matches(files, p) for p in d["none_of"])
        if ok:
            found.append(st.stack)
    return found


def resolve(repo_root: Path, stacks, declared_repo: Optional[List[str]], declared_apps: Dict[str, Optional[List[str]]],
            apps: Dict[str, str]) -> Dict[str, Any]:
    """{declared, detected, used, source, to_confirm, apps} for the report and the engine."""
    detected = detect(repo_root, stacks)
    any_declared = bool(declared_repo) or any(v for v in declared_apps.values())
    if any_declared:
        used, source = list(declared_repo or []), "declared"
    elif detected:
        used, source = list(detected), "detected"
    else:
        used, source = [], "none"
    per_app = {a: list(declared_apps.get(a) or used) for a in apps}
    all_declared = set(declared_repo or []) | {s for v in declared_apps.values() for s in (v or [])}
    to_confirm = []
    if source == "declared":
        for code in sorted(set(detected) | all_declared):
            if code in detected and code not in all_declared:
                to_confirm.append({"stack": code, "issue": "detected but not declared"})
            elif code in all_declared and code not in detected:
                to_confirm.append({"stack": code, "issue": "declared but not detected"})
    return {"declared": sorted(all_declared), "detected": detected, "used": used, "source": source,
            "to_confirm": to_confirm, "apps": per_app}
