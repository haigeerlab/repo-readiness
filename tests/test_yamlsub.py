import unittest
from pathlib import Path

from repo_readiness.yamlsub import YamlSubsetError, load, loads

FIX = Path(__file__).resolve().parent / "fixtures" / "yaml"


class TemplateFixturesTest(unittest.TestCase):
    """The standard's own templates (copied verbatim) must parse exactly."""

    def test_interface_example(self):
        self.assertEqual(load(FIX / "interface.example.yml"), {
            "version": 1,
            "entries": {
                "check": {"run": "/bin/bash scripts/validate.sh", "timeout_minutes": 15, "report": "wrapped"},
                "suppressions": {"run": "python3 scripts/count_suppressions.py", "report": "native",
                                 "baseline": ".github/autopr/suppressions-baseline.json"},
                "verify": {"run": "/bin/bash scripts/verify-headless.sh", "report": "native",
                           "network": "required", "timeout_minutes": 20},
            },
        })

    def test_readiness_example(self):
        d = load(FIX / "readiness.example.v2.yml")
        self.assertEqual(
            [d[k] for k in ("standard", "repo", "category", "owner", "target_tier", "target_reason",
                            "assessed_at", "assessed_by", "apps")],
            ["2.0", "haigeerlab/<repo>", "plugin", "<通信名>", "standard", "<为什么是这一档，见标准 §3.1 末尾>",
             "2026-11-19", "<通信名>", {}])
        self.assertEqual(list(d), ["standard", "repo", "category", "owner", "target_tier", "target_reason",
                                   "assessed_at", "assessed_by", "apps", "general", "basic",
                                   "standard_tier", "high"])
        self.assertEqual(list(d["general"]), ["G%d" % i for i in range(1, 13)])
        self.assertEqual(d["general"]["G2"],
                         {"status": "gap", "plan": "向用户确认后补勾「合并前必须有 PR」，审批人数 0"})
        self.assertEqual(d["general"]["G12"], {"status": "gap"})
        self.assertEqual(d["basic"]["V1"],
                         {"status": "met", "evidence": "interface.yml 的 check → /bin/bash scripts/validate.sh"})
        self.assertEqual(d["basic"]["E1"], {"status": "na", "reason": "只用 Python 标准库和系统 bash，无第三方依赖"})
        self.assertEqual(list(d["standard_tier"]), ["P1", "E2", "K2", "K3", "Q1", "X1", "Q2", "S1"])
        self.assertEqual(list(d["high"]), ["Q3", "Q4", "K4", "R3", "P2", "P3"])


class ContractExampleTest(unittest.TestCase):
    def test_interface_contract_section_3(self):
        text = '''version: 1
entries:
  check:
    run: "bash scripts/validate.sh"     # one command, from repo root
    timeout_minutes: 15
    report: wrapped
    changed: "bash scripts/validate.sh --changed {base}"
apps:
  site:
    path: "apps/site/"
    entries:
      verify: { run: "pnpm --filter site run verify", report: native, timeout_minutes: 20 }
'''
        d = loads(text)
        self.assertEqual(d["entries"]["check"]["changed"], "bash scripts/validate.sh --changed {base}")
        self.assertEqual(d["apps"]["site"]["entries"]["verify"],
                         {"run": "pnpm --filter site run verify", "report": "native", "timeout_minutes": 20})


class ScalarAndStructureTest(unittest.TestCase):
    def test_scalar_types(self):
        d = loads("a: 1\nb: -2\nc: 1.5\nd: true\ne: False\nf: null\ng: ~\nh:\ni: 2026-11-19\nj: '2.0'\nk: 0x1f\n")
        self.assertEqual(d, {"a": 1, "b": -2, "c": 1.5, "d": True, "e": False, "f": None, "g": None,
                             "h": None, "i": "2026-11-19", "j": "2.0", "k": "0x1f"})

    def test_quoted_strings(self):
        d = loads('a: "x: y # not a comment"\nb: \'it\'\'s\'\nc: "tab\\tquote\\"\\u00e9"\n')
        self.assertEqual(d, {"a": "x: y # not a comment", "b": "it's", "c": 'tab\tquote"\u00e9'})

    def test_plain_hash_without_space_is_not_comment(self):
        self.assertEqual(loads("a: x#y\nb: x # c\n"), {"a": "x#y", "b": "x"})

    def test_sequences(self):
        d = loads("a:\n  - 1\n  - two\nb:\n- x\n- y\nc: [1, 'two', [3]]\n")
        self.assertEqual(d, {"a": [1, "two"], "b": ["x", "y"], "c": [1, "two", [3]]})

    def test_sequence_of_mappings(self):
        d = loads("steps:\n  - uses: actions/checkout@0123\n    with:\n      depth: 1\n  - run: make test\n")
        self.assertEqual(d, {"steps": [{"uses": "actions/checkout@0123", "with": {"depth": 1}},
                                       {"run": "make test"}]})

    def test_nested_flow(self):
        self.assertEqual(loads("a: {b: [1, {c: d}], e: {}}\n"), {"a": {"b": [1, {"c": "d"}], "e": {}}})

    def test_top_level_sequence_and_empty_document(self):
        self.assertEqual(loads("- a\n- b\n"), ["a", "b"])
        self.assertIsNone(loads("# only a comment\n\n"))

    def test_single_leading_document_marker_is_allowed(self):
        self.assertEqual(loads("---\na: 1\n"), {"a": 1})


class UnsupportedSyntaxTest(unittest.TestCase):
    """Anything outside the subset must fail loudly, never parse to something else."""

    def assertRejected(self, text, line, fragment):
        with self.assertRaises(YamlSubsetError) as cm:
            loads(text)
        self.assertEqual(cm.exception.line, line, str(cm.exception))
        self.assertIn(fragment, str(cm.exception))

    def test_anchor(self):
        self.assertRejected("a: &x 1\nb: 2\n", 1, "anchor")

    def test_alias(self):
        self.assertRejected("a: 1\nb: *x\n", 2, "alias")

    def test_tag(self):
        self.assertRejected("a: !!str 1\n", 1, "tag")

    def test_block_scalar(self):
        self.assertRejected("run: |\n  echo hi\n", 1, "block scalar")
        self.assertRejected("run: >-\n  echo hi\n", 1, "block scalar")

    def test_multiple_documents(self):
        self.assertRejected("a: 1\n---\nb: 2\n", 2, "multiple documents")

    def test_tab_indentation(self):
        self.assertRejected("a:\n\tb: 1\n", 2, "tab")

    def test_duplicate_key(self):
        self.assertRejected("a: 1\na: 2\n", 2, "duplicate key")

    def test_multiline_plain_scalar(self):
        self.assertRejected("a: one\n  two\n", 2, "indentation")

    def test_unterminated_flow(self):
        self.assertRejected("a: {b: 1\nc: 2\n", 1, "unterminated")

    def test_complex_key(self):
        self.assertRejected("? a\n: b\n", 1, "complex key")

    def test_mapping_inside_plain_value(self):
        self.assertRejected("a: b: c\n", 1, "': '")

    def test_unterminated_quote(self):
        self.assertRejected('a: "open\n', 1, "unterminated")


if __name__ == "__main__":
    unittest.main()
