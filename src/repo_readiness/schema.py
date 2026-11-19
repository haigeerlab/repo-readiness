"""A small, strict JSON Schema (2020-12) validator for the schemas this tool uses.

Only the keywords listed in _ASSERTIONS / _APPLICATORS / _ANNOTATIONS are
understood. A schema using anything else is rejected up front with
SchemaError: silently ignoring an unknown keyword would let an invalid
document "pass", which is exactly what a readiness gate must never do.

Deliberate choices:
- ``format`` is an assertion here, and only ``date`` and ``date-time`` exist.
- ``$ref`` only resolves local JSON pointers (``#``, ``#/$defs/...``).
- JSON equality for ``const`` / ``enum`` keeps true/false distinct from 1/0.
"""

import datetime
import re
from typing import Any, Dict, List, NamedTuple

__all__ = ["SchemaError", "ValidationError", "Validator", "validate"]

_ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "default", "examples",
                "deprecated", "readOnly", "writeOnly"}
_ASSERTIONS = {"type", "enum", "const", "required", "minimum", "maximum", "exclusiveMinimum",
               "exclusiveMaximum", "minLength", "maxLength", "pattern", "format", "minItems",
               "maxItems", "uniqueItems"}
_APPLICATORS = {"properties", "additionalProperties", "items", "allOf", "anyOf", "oneOf", "not",
                "if", "then", "else", "$ref", "$defs"}
_KNOWN = _ANNOTATIONS | _ASSERTIONS | _APPLICATORS
_TYPES = {"null", "boolean", "integer", "number", "string", "array", "object"}
_DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


class SchemaError(ValueError):
    """The schema itself uses something this validator does not support."""


class ValidationError(NamedTuple):
    path: str
    message: str

    def __str__(self) -> str:
        return "%s: %s" % (self.path, self.message)


def validate(instance: Any, schema: Any) -> List[ValidationError]:
    return Validator(schema).errors(instance)


# --------------------------------------------------------------------------- helpers

def _json_type(x: Any) -> str:
    if x is None:
        return "null"
    if isinstance(x, bool):
        return "boolean"
    if isinstance(x, int):
        return "integer"
    if isinstance(x, float):
        return "number"
    if isinstance(x, str):
        return "string"
    if isinstance(x, list):
        return "array"
    if isinstance(x, dict):
        return "object"
    return type(x).__name__


def _is_type(x: Any, t: str) -> bool:
    jt = _json_type(x)
    if t == "number":
        return jt in ("integer", "number")
    if t == "integer":
        return jt == "integer" or (jt == "number" and float(x).is_integer())
    return jt == t


def _json_equal(a: Any, b: Any) -> bool:
    ta, tb = _json_type(a), _json_type(b)
    if {ta, tb} <= {"integer", "number"}:
        return a == b
    if ta != tb:
        return False
    if ta == "array":
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    if ta == "object":
        return a.keys() == b.keys() and all(_json_equal(a[k], b[k]) for k in a)
    return a == b


def _format_ok(fmt: str, x: Any) -> bool:
    if not isinstance(x, str):
        return True
    try:
        if fmt == "date":
            if not _DATE.match(x):
                return False
            datetime.date.fromisoformat(x)
            return True
        if not _DATE_TIME.match(x):
            return False
        datetime.datetime.fromisoformat(x[:19])
        return True
    except ValueError:
        return False


def _child(path: str, key: Any) -> str:
    return "%s[%d]" % (path, key) if isinstance(key, int) else "%s.%s" % (path, key)


# --------------------------------------------------------------------------- validator

class Validator:
    def __init__(self, schema: Any):
        self.root = schema
        self._check(schema, "#")

    # ---- schema checking (up front, so unsupported schemas never run)

    def _check(self, s: Any, where: str) -> None:
        if isinstance(s, bool):
            return
        if not isinstance(s, dict):
            raise SchemaError("%s: a schema must be an object or a boolean" % where)
        unknown = sorted(set(s) - _KNOWN)
        if unknown:
            raise SchemaError("%s: unsupported keyword(s): %s" % (where, ", ".join(unknown)))
        t = s.get("type")
        for name in ([t] if isinstance(t, str) else (t or [])):
            if name not in _TYPES:
                raise SchemaError("%s: unknown type %r" % (where, name))
        if "format" in s and s["format"] not in ("date", "date-time"):
            raise SchemaError("%s: unsupported format %r" % (where, s["format"]))
        if "pattern" in s:
            try:
                re.compile(s["pattern"])
            except re.error as e:
                raise SchemaError("%s: bad pattern: %s" % (where, e))
        for kw in ("properties", "$defs"):
            for name, sub in s.get(kw, {}).items():
                self._check(sub, "%s/%s/%s" % (where, kw, name))
        for kw in ("additionalProperties", "items", "not", "if", "then", "else"):
            if kw in s:
                if kw == "items" and isinstance(s[kw], list):
                    raise SchemaError("%s: tuple-form 'items' is not supported" % where)
                self._check(s[kw], "%s/%s" % (where, kw))
        for kw in ("allOf", "anyOf", "oneOf"):
            if kw in s:
                if not isinstance(s[kw], list) or not s[kw]:
                    raise SchemaError("%s: %s must be a non-empty array" % (where, kw))
                for n, sub in enumerate(s[kw]):
                    self._check(sub, "%s/%s/%d" % (where, kw, n))
        if "$ref" in s:
            self._resolve(s["$ref"])

    def _resolve(self, ref: str) -> Any:
        if not isinstance(ref, str) or not ref.startswith("#"):
            raise SchemaError("only local $ref is supported: %r" % (ref,))
        node = self.root
        for part in [p for p in ref[1:].split("/") if p]:
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or part not in node:
                raise SchemaError("unresolvable $ref %r" % ref)
            node = node[part]
        return node

    # ---- instance validation

    def errors(self, instance: Any) -> List[ValidationError]:
        out = []  # type: List[ValidationError]
        self._validate(instance, self.root, "$", out)
        return out

    def is_valid(self, instance: Any) -> bool:
        return not self.errors(instance)

    def _ok(self, x: Any, s: Any, path: str) -> bool:
        tmp = []  # type: List[ValidationError]
        self._validate(x, s, path, tmp)
        return not tmp

    def _validate(self, x: Any, s: Any, path: str, out: List[ValidationError]) -> None:
        if s is True:
            return
        if s is False:
            out.append(ValidationError(path, "no value is allowed here"))
            return
        if "$ref" in s:
            self._validate(x, self._resolve(s["$ref"]), path, out)

        if "type" in s:
            types = [s["type"]] if isinstance(s["type"], str) else s["type"]
            if not any(_is_type(x, t) for t in types):
                out.append(ValidationError(path, "expected %s, got %s" % (" or ".join(types), _json_type(x))))
                return
        if "const" in s and not _json_equal(x, s["const"]):
            out.append(ValidationError(path, "must equal %r" % (s["const"],)))
        if "enum" in s and not any(_json_equal(x, e) for e in s["enum"]):
            out.append(ValidationError(path, "must be one of %r" % (s["enum"],)))
        self._numbers(x, s, path, out)
        self._strings(x, s, path, out)
        self._arrays(x, s, path, out)
        self._objects(x, s, path, out)

        for sub in s.get("allOf", []):
            self._validate(x, sub, path, out)
        if "anyOf" in s and not any(self._ok(x, sub, path) for sub in s["anyOf"]):
            out.append(ValidationError(path, "does not match any of the allowed shapes (anyOf)"))
        if "oneOf" in s:
            n = sum(1 for sub in s["oneOf"] if self._ok(x, sub, path))
            if n != 1:
                out.append(ValidationError(path, "must match exactly one shape (oneOf), matched %d" % n))
        if "not" in s and self._ok(x, s["not"], path):
            out.append(ValidationError(path, "matches a forbidden shape (not)"))
        if "if" in s:
            branch = "then" if self._ok(x, s["if"], path) else "else"
            if branch in s:
                self._validate(x, s[branch], path, out)

    def _numbers(self, x: Any, s: Dict[str, Any], path: str, out: List[ValidationError]) -> None:
        if _json_type(x) not in ("integer", "number"):
            return
        if "minimum" in s and x < s["minimum"]:
            out.append(ValidationError(path, "must be >= %s" % s["minimum"]))
        if "maximum" in s and x > s["maximum"]:
            out.append(ValidationError(path, "must be <= %s" % s["maximum"]))
        if "exclusiveMinimum" in s and x <= s["exclusiveMinimum"]:
            out.append(ValidationError(path, "must be > %s" % s["exclusiveMinimum"]))
        if "exclusiveMaximum" in s and x >= s["exclusiveMaximum"]:
            out.append(ValidationError(path, "must be < %s" % s["exclusiveMaximum"]))

    def _strings(self, x: Any, s: Dict[str, Any], path: str, out: List[ValidationError]) -> None:
        if not isinstance(x, str):
            return
        if "minLength" in s and len(x) < s["minLength"]:
            out.append(ValidationError(path, "must be at least %d characters" % s["minLength"]))
        if "maxLength" in s and len(x) > s["maxLength"]:
            out.append(ValidationError(path, "must be at most %d characters" % s["maxLength"]))
        if "pattern" in s and not re.search(s["pattern"], x):
            out.append(ValidationError(path, "does not match pattern %r" % s["pattern"]))
        if "format" in s and not _format_ok(s["format"], x):
            out.append(ValidationError(path, "is not a valid %s" % s["format"]))

    def _arrays(self, x: Any, s: Dict[str, Any], path: str, out: List[ValidationError]) -> None:
        if not isinstance(x, list):
            return
        if "minItems" in s and len(x) < s["minItems"]:
            out.append(ValidationError(path, "must have at least %d items" % s["minItems"]))
        if "maxItems" in s and len(x) > s["maxItems"]:
            out.append(ValidationError(path, "must have at most %d items" % s["maxItems"]))
        if s.get("uniqueItems"):
            for i in range(len(x)):
                if any(_json_equal(x[i], x[j]) for j in range(i)):
                    out.append(ValidationError(path, "items must be unique"))
                    break
        if "items" in s:
            for i, item in enumerate(x):
                self._validate(item, s["items"], _child(path, i), out)

    def _objects(self, x: Any, s: Dict[str, Any], path: str, out: List[ValidationError]) -> None:
        if not isinstance(x, dict):
            return
        for name in s.get("required", []):
            if name not in x:
                out.append(ValidationError(path, "missing required property %r" % name))
        props = s.get("properties", {})
        for name, value in x.items():
            if name in props:
                self._validate(value, props[name], _child(path, name), out)
            elif "additionalProperties" in s:
                extra = s["additionalProperties"]
                if extra is False:
                    out.append(ValidationError(path, "unexpected property %r" % name))
                else:
                    self._validate(value, extra, _child(path, name), out)
