from __future__ import annotations

import collections
import unicodedata
import unittest
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "evaluation" / "h3" / "facet-validation-v1.jsonl"
CATALOG = ROOT / "evaluation" / "h3" / "agnostic_corpus_catalog.json"
MINIMUMS = {"both": 8, "partial": 2, "none": 1}


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def plain(text: str) -> str:
    """Accent-, case- and punctuation-folded key for the concatenation check."""
    folded = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return " ".join("".join(c for c in folded if c.isalnum() or c.isspace()).split())


class FacetBankContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = load(BANK)
        self.catalog = {source["id"] for source in json.loads(
            CATALOG.read_text(encoding="utf-8"))["documents"]}

    def test_bank_has_eleven_cases_with_unique_ids(self) -> None:
        self.assertEqual(len(self.cases), 11)
        self.assertEqual(len({case["id"] for case in self.cases}), 11)
        for case in self.cases:
            self.assertEqual(case["language"], "es", case["id"])
            self.assertEqual(case["kind"], case["expected"], case["id"])
            self.assertTrue(case.get("tags"), case["id"])

    def test_minimums_by_kind(self) -> None:
        counts = collections.Counter(case["kind"] for case in self.cases)
        for kind, minimum in MINIMUMS.items():
            self.assertGreaterEqual(counts[kind], minimum, kind)
        self.assertEqual(counts["both"], 8)
        self.assertEqual(counts["partial"], 2)
        self.assertEqual(counts["none"], 1)

    def test_every_case_has_two_parts(self) -> None:
        for case in self.cases:
            self.assertEqual(len(case["parts"]), 2, case["id"])
            for part in case["parts"]:
                self.assertTrue(part["query"].strip(), case["id"])
                self.assertIsInstance(part["expected_documents"], list, case["id"])

    def test_expected_documents_follow_the_kind(self) -> None:
        for case in self.cases:
            for part in case["parts"]:
                self.assertLessEqual(set(part["expected_documents"]), self.catalog, case["id"])
            if case["kind"] == "both":
                for part in case["parts"]:
                    self.assertTrue(part["expected_documents"], case["id"])
                self.assertEqual(len({p for part in case["parts"] for p in part["expected_documents"]}), 2,
                                 f"las dos partes de un caso both citan documentos distintos: {case['id']}")
            elif case["kind"] == "partial":
                empty = [part for part in case["parts"] if not part["expected_documents"]]
                full = [part for part in case["parts"] if part["expected_documents"]]
                self.assertEqual(len(empty), 1, case["id"])
                self.assertEqual(len(full), 1, case["id"])
            else:
                self.assertTrue(all(not part["expected_documents"] for part in case["parts"]), case["id"])

    def test_query_is_a_reasonable_concatenation_of_the_parts(self) -> None:
        for case in self.cases:
            composed = plain(case["query"])
            self.assertTrue(composed, case["id"])
            for part in case["parts"]:
                self.assertIn(plain(part["query"]), composed,
                              f"la parte no está en la pregunta compuesta: {case['id']}")

    def test_first_case_is_the_product_question(self) -> None:
        # FAC-VAL-001 asks two facts the corpus asserts (pollination of crops,
        # photosynthesis products), verified against the converted corpus.
        first = self.cases[0]
        self.assertEqual(first["id"], "FAC-VAL-001")
        self.assertEqual(first["kind"], "both")
        folded = plain(first["query"])
        self.assertIn("abejas", folded)
        self.assertIn("cosechas", folded)
        self.assertIn("fotosintesis", folded)
        self.assertNotIn("reproduccion", folded)

    def test_over_specified_original_is_the_partial_control(self) -> None:
        # The pre-fix FAC-VAL-001 question stays as FAC-VAL-011: the corpus only
        # mentions pollination, it never asserts the bees' role in plant
        # reproduction, so the bees part must abstain while the photosynthesis
        # part answers — the documented corpus limit, measured as `partial`.
        control = next(case for case in self.cases if case["id"] == "FAC-VAL-011")
        self.assertEqual(control["kind"], "partial")
        folded = plain(control["query"])
        self.assertIn("abejas", folded)
        self.assertIn("reproduccion", folded)
        self.assertIn("fotosintesis", folded)
        bees, photosynthesis = control["parts"]
        self.assertEqual(bees["expected_documents"], [])
        self.assertEqual(photosynthesis["expected_documents"], ["AGN-008"])


if __name__ == "__main__":
    unittest.main()
