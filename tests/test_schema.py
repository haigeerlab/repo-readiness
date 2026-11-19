import copy
import json
import unittest
from pathlib import Path

from repo_readiness.schema import SchemaError, Validator, validate

FIX = Path(__file__).resolve().parent / "fixtures" / "schema"
SHA = "a" * 40
ENTRY_REPORT = json.loads((FIX / "entry-report.schema.json").read_text(encoding="utf-8"))

WRAPPED_CHECK = {
    "schema": "autopr.entry-report/v1", "entry": "check", "repo": "haigeerlab/agent-relay", "head": SHA,
    "status": "pass", "exit_code": 0, "started_at": "2026-11-19T10:00:00Z", "duration_s": 12.5,
    "producer": "wrapped",
}
VERIFY_PASS = dict(WRAPPED_CHECK, entry="verify", producer="native",
                   scenarios=[{"id": "login", "status": "pass", "artifacts": ["login.png"]}],
                   artifacts=[{"path": "login.png", "kind": "screenshot", "sha256": "b" * 64}])


def paths(errors):
    return sorted(e.path for e in errors)


class EntryReportSchemaTest(unittest.TestCase):
    """The standard's entry-report schema exercises if/then, $ref, pattern, enum, const."""

    def setUp(self):
        self.v = Validator(ENTRY_REPORT)

    def test_valid_reports(self):
        self.assertEqual(self.v.errors(WRAPPED_CHECK), [])
        self.assertEqual(self.v.errors(VERIFY_PASS), [])

    def test_status_must_match_exit_code(self):
        bad = dict(WRAPPED_CHECK, exit_code=1)
        self.assertEqual(paths(self.v.errors(bad)), ["$.exit_code"])

    def test_error_status_rejects_exit_zero(self):
        bad = dict(WRAPPED_CHECK, status="error", exit_code=0)
        self.assertEqual(paths(self.v.errors(bad)), ["$.exit_code"])

    def test_verify_pass_needs_evidence(self):
        bad = {k: v for k, v in VERIFY_PASS.items() if k != "scenarios"}
        self.assertIn("$", paths(self.v.errors(bad)))
        empty = dict(VERIFY_PASS, artifacts=[])
        self.assertEqual(paths(self.v.errors(empty)), ["$.artifacts"])

    def test_sha_pattern_via_ref(self):
        self.assertEqual(paths(self.v.errors(dict(WRAPPED_CHECK, head="ABC"))), ["$.head"])

    def test_additional_property_rejected(self):
        self.assertEqual(paths(self.v.errors(dict(WRAPPED_CHECK, extra=1))), ["$"])

    def test_lookahead_pattern_on_artifact_path(self):
        bad = copy.deepcopy(VERIFY_PASS)
        bad["artifacts"][0]["path"] = "../secret.png"
        self.assertEqual(paths(self.v.errors(bad)), ["$.artifacts[0].path"])

    def test_date_time_format_is_checked(self):
        self.assertEqual(paths(self.v.errors(dict(WRAPPED_CHECK, started_at="yesterday"))), ["$.started_at"])

    def test_bool_is_not_an_integer(self):
        errs = self.v.errors(dict(WRAPPED_CHECK, exit_code=True))
        # Two independent violations: wrong type, and (status=pass) exit_code must equal 0.
        self.assertEqual(paths(errs), ["$.exit_code", "$.exit_code"])
        self.assertTrue(any("expected integer" in e.message for e in errs))


class KeywordTest(unittest.TestCase):
    def test_type_and_bounds(self):
        s = {"type": "object", "properties": {
            "n": {"type": "number", "minimum": 0, "maximum": 1},
            "s": {"type": "string", "minLength": 2, "maxLength": 3},
            "a": {"type": "array", "minItems": 1, "maxItems": 2, "uniqueItems": True},
        }}
        self.assertEqual(validate({"n": 0.5, "s": "ab", "a": [1]}, s), [])
        self.assertEqual(paths(validate({"n": 2, "s": "a", "a": [1, 1, 1]}, s)), ["$.a", "$.a", "$.n", "$.s"])

    def test_one_of_and_any_of(self):
        s = {"oneOf": [{"type": "integer"}, {"type": "number"}]}
        self.assertEqual(validate(1.5, s), [])
        self.assertEqual(len(validate(1, s)), 1)  # matches both -> not exactly one
        self.assertEqual(validate("x", {"anyOf": [{"type": "integer"}, {"type": "string"}]}), [])
        self.assertEqual(len(validate(None, {"anyOf": [{"type": "integer"}, {"type": "string"}]})), 1)

    def test_if_then_else(self):
        s = {"if": {"const": 1}, "then": {"type": "integer"}, "else": {"type": "string"}}
        self.assertEqual(validate(1, s), [])
        self.assertEqual(validate("x", s), [])
        self.assertEqual(len(validate(2, s)), 1)

    def test_const_and_enum_distinguish_bool_from_int(self):
        self.assertEqual(len(validate(True, {"const": 1})), 1)
        self.assertEqual(len(validate(1, {"enum": [True]})), 1)
        self.assertEqual(validate({"a": [1]}, {"const": {"a": [1]}}), [])

    def test_additional_properties_schema_and_pattern_is_unanchored_search(self):
        s = {"type": "object", "additionalProperties": {"type": "string", "pattern": "b"}}
        self.assertEqual(validate({"x": "abc"}, s), [])
        self.assertEqual(paths(validate({"x": "ac"}, s)), ["$.x"])

    def test_date_format(self):
        self.assertEqual(validate("2026-11-19", {"format": "date"}), [])
        self.assertEqual(len(validate("2026-13-40", {"format": "date"})), 1)

    def test_error_carries_message(self):
        (e,) = validate("x", {"type": "integer"})
        self.assertIn("integer", e.message)


class SchemaRejectionTest(unittest.TestCase):
    """A schema we do not fully understand must not 'pass' silently."""

    def test_unknown_keyword(self):
        with self.assertRaises(SchemaError) as cm:
            Validator({"type": "object", "patternProperties": {"^x": {}}})
        self.assertIn("patternProperties", str(cm.exception))

    def test_unknown_keyword_nested(self):
        with self.assertRaises(SchemaError):
            Validator({"properties": {"a": {"dependentRequired": {}}}})

    def test_property_named_like_a_keyword_is_fine(self):
        Validator({"properties": {"pattern": {"type": "string"}, "if": {"type": "string"}}})

    def test_remote_ref_rejected(self):
        with self.assertRaises(SchemaError):
            Validator({"$ref": "https://example.com/s.json"})

    def test_dangling_ref_rejected(self):
        with self.assertRaises(SchemaError):
            Validator({"$ref": "#/$defs/missing"})

    def test_unknown_format_rejected(self):
        with self.assertRaises(SchemaError):
            Validator({"format": "email"})


if __name__ == "__main__":
    unittest.main()
