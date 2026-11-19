"""Probe declarations: every name a clause file may `use`, with its parameter schema.

Declaring a probe here is what makes `clauses lint` accept it; the runtime
implementation is registered separately. Keeping the two apart lets a ruler
be written (and linted) before every probe is implemented, while the engine
still refuses to run a declared-but-unimplemented probe.
"""

from typing import Any, Dict

from repo_readiness.schema import Validator

_STR = {"type": "string", "minLength": 1}


def _params(required, **props) -> Dict[str, Any]:
    return {"type": "object", "required": list(required), "additionalProperties": False, "properties": props}


CATALOG = {
    # Files in the repository under test (paths are relative to its root).
    "fs.exists": _params(["path"], path=_STR),
    "fs.glob": _params(["pattern"], pattern=_STR, min={"type": "integer", "minimum": 0}),
    "fs.contains": _params(["path", "pattern"], path=_STR, pattern=_STR),
    # The owner's self-assessment in readiness.yml, keyed by clause id.
    "declare": _params([], key=_STR),
    # Hand the clause (and the evidence gathered so far) to an agent for a judgment.
    "judge": _params([], question=_STR),

    # ---- Declared for the v2.0 basic tier; implemented in later tasks (T9-T15).
    # GitHub settings and history, read-only (GET) through the platform adapter.
    "github.repo": _params(["owner", "default_branch"], owner=_STR, default_branch=_STR),
    "github.effective_branch_rules": _params(
        ["branch", "require"], branch=_STR,
        require={"type": "array", "minItems": 1, "uniqueItems": True,
                 "items": {"enum": ["no_force_push", "no_deletion", "pull_request_required"]}}),
    "github.main_ci_green": _params(["branch", "max_age_hours"], branch=_STR,
                                    max_age_hours={"type": "integer", "minimum": 1}),
    "github.secret_scanning": _params([]),
    "github.workflow_permissions": _params([]),
    # Static analysis of .github/workflows/*.yml (no execution).
    "workflow.pr_runs_check": _params([], entry=_STR),
    "workflow.no_dangerous_triggers": _params([]),
    "workflow.actions_pinned": _params([]),
    # Structured config files in the repository.
    "config.parses": _params(["path", "format"], path=_STR, format={"enum": ["yaml", "json"]}),
    "risk.template_paths_kept": _params(["path"], path=_STR),
    # The local mailbox: is the declared owner a registered agent? (local runs only)
    "registry.owner_registered": _params(["path", "key"], path=_STR, key=_STR),
    # Interface entries from interface.yml, run per the interface contract (opt-in).
    "entry.run": _params(["entry"], entry={"enum": ["check", "setup", "verify", "suppressions", "smoke"]},
                         mode={"enum": ["full", "changed"]}),
    # Ecosystem adapters (data-driven, language-neutral core).
    "ecosystem.has_dependencies": _params([]),
    "ecosystem.lockfile_installed": _params([]),
}  # type: Dict[str, Dict[str, Any]]

_VALIDATORS = {name: Validator(schema) for name, schema in CATALOG.items()}


def param_validator(name: str) -> Validator:
    return _VALIDATORS[name]
