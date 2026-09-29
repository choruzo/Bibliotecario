from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "h0"
sys.path.insert(0, str(SCRIPTS))

from catalog_corpus import check_catalog
from generate_variants import blocks_from_markdown
from validate_h0 import load_questions, validate


class H0ContractTests(unittest.TestCase):
    def test_catalog_matches_private_sources(self) -> None:
        self.assertEqual(check_catalog(), [])

    def test_full_h0_contract(self) -> None:
        self.assertEqual(validate(), [])

    def test_question_bank_has_exact_seed_size(self) -> None:
        self.assertEqual(len(load_questions()), 24)

    def test_markdown_blocks_preserve_core_structures(self) -> None:
        source = "# Título\n\n- uno\n\n| A | B |\n|---|---|\n| x | y |\n\n```sh\necho ok\n```\n"
        blocks = blocks_from_markdown(source)
        self.assertEqual([block.kind for block in blocks], ["heading", "list_item", "table", "code"])
        self.assertEqual(blocks[2].rows, [["A", "B"], ["x", "y"]])


if __name__ == "__main__":
    unittest.main()
