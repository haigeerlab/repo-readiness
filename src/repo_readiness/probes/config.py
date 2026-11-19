"""Config-file probes (G7, R1) and the self-assessment probe `declare`."""

import json
from typing import Dict, List

from repo_readiness.probes import runtime
from repo_readiness.probes.fs import _resolve, _shown
from repo_readiness.probes.runtime import ProbeContext, ProbeResult
from repo_readiness.yamlsub import YamlSubsetError, load


def _parse(path, fmt: str):
    if fmt == "json":
        return json.loads(path.read_text(encoding="utf-8"))
    return load(path)


@runtime.register("config.parses")
def parses(params: Dict, ctx: ProbeContext) -> ProbeResult:
    p, err = _resolve(params["path"], ctx)
    if err:
        return ProbeResult(status="unknown", error=err)
    shown = _shown(p, ctx)
    if not p.is_file():
        return ProbeResult(status="gap", missing="%s not found" % shown)
    try:
        _parse(p, params["format"])
    except (YamlSubsetError, ValueError, UnicodeDecodeError) as e:
        return ProbeResult(status="gap", missing="%s does not parse as %s: %s" % (shown, params["format"], e))
    return ProbeResult(status="met", evidence=["%s parses as %s" % (shown, params["format"])])


@runtime.register("registry.owner_registered")
def owner_registered(params: Dict, ctx: ProbeContext) -> ProbeResult:
    """The declared owner is a registered agent in the local mailbox (names supplied with --registry)."""
    p, err = _resolve(params["path"], ctx)
    if err:
        return ProbeResult(status="unknown", error=err)
    if not p.is_file():
        return ProbeResult(status="gap", missing="%s not found" % _shown(p, ctx))
    try:
        data = load(p)
    except (YamlSubsetError, UnicodeDecodeError) as e:
        return ProbeResult(status="gap", missing="%s does not parse: %s" % (_shown(p, ctx), e))
    owner = data.get(params["key"]) if isinstance(data, dict) else None
    if not isinstance(owner, str) or not owner.strip():
        return ProbeResult(status="gap", missing="%s has no %s" % (_shown(p, ctx), params["key"]))
    if ctx.registry is None:
        why = ("owner registry not provided for this run; pass --registry FILE "
               "(a local-only check: CI carries over the last local result)")
        return ProbeResult(status="unknown", error=why, skipped=[why])
    if owner in ctx.registry:
        return ProbeResult(status="met", evidence=["owner %s is registered in the mailbox" % owner])
    return ProbeResult(status="gap", missing="owner %s is not registered in the mailbox" % owner)


def _globs(section: Dict, tier: str) -> List[str]:
    v = section.get("%s_paths" % tier) if isinstance(section, dict) else None
    return [g for g in v if isinstance(g, str)] if isinstance(v, list) else []


@runtime.register("risk.template_paths_kept")
def template_paths_kept(params: Dict, ctx: ProbeContext) -> ProbeResult:
    """R1 (automatic part): the repo's risk-tiers.yml extends a category and does not lower a template T4 path.

    Only exact glob matches are detected (an overlapping but different glob is not).
    """
    p, err = _resolve(params["path"], ctx)
    if err:
        return ProbeResult(status="unknown", error=err)
    shown = _shown(p, ctx)
    if not p.is_file():
        return ProbeResult(status="gap", missing="%s not found" % shown)
    try:
        repo = load(p)
    except (YamlSubsetError, UnicodeDecodeError) as e:
        return ProbeResult(status="gap", missing="%s does not parse: %s" % (shown, e))
    if not isinstance(repo, dict):
        return ProbeResult(status="gap", missing="%s is not a mapping" % shown)
    if ctx.risk_templates is None:
        why = "category risk templates not provided; pass --risk-templates FILE"
        return ProbeResult(status="unknown", error=why, skipped=[why])
    cats = ctx.risk_templates.get("categories") or {}
    ext = repo.get("extends")
    if not isinstance(ext, str) or ext not in cats:
        return ProbeResult(status="gap", missing="%s extends %r, not one of the template categories (%s)"
                           % (shown, ext, ", ".join(sorted(cats))))
    t4 = set(_globs(ctx.risk_templates.get("common") or {}, "T4") + _globs(cats[ext], "T4"))
    lowered = ["%s as %s" % (g, tier) for tier in ("T0", "T1", "T2", "T3") for g in _globs(repo, tier) if g in t4]
    ev = ["%s extends %s; template T4 paths: %d" % (shown, ext, len(t4))]
    if lowered:
        return ProbeResult(status="gap", evidence=ev, missing="template T4 path(s) lowered: " + ", ".join(lowered))
    return ProbeResult(status="met", evidence=ev)


@runtime.register("declare")
def declare(params: Dict, ctx: ProbeContext) -> ProbeResult:
    decls = ctx.declarations
    if decls is None:
        return ProbeResult(status="unknown", error="self-assessment not loaded for this run")
    if decls.error:
        return ProbeResult(status="unknown", error=decls.error)
    key = params.get("key")
    if not key:
        return ProbeResult(status="unknown", error="declare probe needs a key")
    if not decls.exists:
        return ProbeResult(status="gap", missing="%s not found, so %s has no self-assessment" % (decls.path, key))
    entry = decls.entries.get(key)
    if entry is None:
        return ProbeResult(status="gap", missing="%s has no self-assessment for %s" % (decls.path, key))
    if entry.problems:
        return ProbeResult(status="gap", missing="%s: %s" % (key, "; ".join(entry.problems)))
    if entry.status == "met":
        if not entry.evidence:
            return ProbeResult(status="gap", missing="%s self-assessed met without evidence" % key)
        return ProbeResult(status="met", evidence=["self-assessed met: %s" % entry.evidence])
    if entry.status == "gap":
        return ProbeResult(status="gap", missing="self-assessed gap; plan: %s" % (entry.plan or "(none)"))
    return ProbeResult(status="gap", missing="declared %s (resolved by the n/a and waiver rules)" % entry.status)


@runtime.register("judge")
def judge(params: Dict, ctx: ProbeContext) -> ProbeResult:
    """Not a check: marks the clause as waiting for an agent judgment (see detect/judge.py)."""
    return ProbeResult(status="unknown", judge_question=params.get("question", ""))
