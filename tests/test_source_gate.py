from pathlib import Path
import unittest

from tools.valis_rebuild.errors import BuildError
from tools.valis_rebuild.source_gate import lint_all, lint_release_baseline, require_buildable


ROOT = Path(__file__).resolve().parents[1]


class SourceGateTests(unittest.TestCase):
    def test_reviewed_source_tree_is_buildable(self):
        report = lint_all(ROOT)
        self.assertEqual(report["status"], "OK")
        self.assertTrue(report["source_manifest"]["buildable"])

    def test_buildable_gate_returns_manifest(self):
        report = require_buildable(ROOT)
        self.assertEqual(report["status"], "OK")

    def test_final_component_contract_is_complete(self):
        report = lint_release_baseline(ROOT)
        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["logo_png_inputs"], 6)
        self.assertEqual(report["logo_source_groups"], 3)
        self.assertEqual(report["logo_encoded_source_bytes"], 8163)


if __name__ == "__main__":
    unittest.main()
