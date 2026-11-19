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
}  # type: Dict[str, Dict[str, Any]]

_VALIDATORS = {name: Validator(schema) for name, schema in CATALOG.items()}


def param_validator(name: str) -> Validator:
    return _VALIDATORS[name]
