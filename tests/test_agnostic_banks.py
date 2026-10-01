from __future__ import annotations

import collections
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BANKS = {split: ROOT / "evaluation" / "h3" / f"agnostic-{split}-v1.jsonl" for split in ("calibration", "validation")}
CATALOG = ROOT / "evaluation" / "h3" / "agnostic_corpus_catalog.json"
MINIMUMS = {"answerable": 10, "unanswerable": 5, "ambiguous": 3, "conversation": 6}


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class AgnosticBankContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.banks = {split: load(path) for split, path in BANKS.items()}
        self.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["documents"]

    def test_each_bank_covers_the_h0_minimums(self) -> None:
        for split, rows in self.banks.items():
            counts = collections.Counter(row["kind"] for row in rows)
            for kind, minimum in MINIMUMS.items():
                self.assertGreaterEqual(counts[kind], minimum, f"{split}: {kind}")

    def test_ids_are_unique_and_groups_do_not_leak(self) -> None:
        rows = [row for bank in self.banks.values() for row in bank]
        self.assertEqual(len({row["id"] for row in rows}), len(rows))
        groups = [{row["conversation_id"] for row in bank if row.get("conversation_id")} for bank in self.banks.values()]
        self.assertFalse(groups[0] & groups[1])

    def test_expected_documents_follow_the_kind(self) -> None:
        sources = {source["id"] for source in self.catalog}
        for row in (row for bank in self.banks.values() for row in bank):
            if row["kind"] in {"answerable", "conversation"}:
                self.assertTrue(row["expected_documents"], row["id"])
                self.assertLessEqual(set(row["expected_documents"]), sources, row["id"])
            else:
                self.assertEqual(row["expected_documents"], [], row["id"])
            if row["kind"] == "conversation":
                self.assertTrue(row.get("conversation_id"), row["id"])
                if row["turn"] > 1:
                    self.assertTrue(row.get("subject"), row["id"])

    def test_catalog_matches_local_sources_when_present(self) -> None:
        self.assertEqual(len({source["id"] for source in self.catalog}), len(self.catalog))
        corpus = ROOT / ".artifacts" / "agnostic-corpus"
        if not corpus.is_dir():
            self.skipTest("Corpus agnóstico no descargado")
        for source in self.catalog:
            data = (corpus / source["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), source["sha256"], source["id"])


if __name__ == "__main__":
    unittest.main()
