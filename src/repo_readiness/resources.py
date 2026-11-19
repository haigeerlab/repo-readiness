"""Locate files shipped with the tool (JSON schemas)."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from repo_readiness.schema import Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


@lru_cache(maxsize=None)
def schema_validator(name: str) -> Validator:
    """Validator for schemas/<name>.json, built once per process."""
    data = json.loads((SCHEMAS / ("%s.json" % name)).read_text(encoding="utf-8"))  # type: Any
    return Validator(data)
