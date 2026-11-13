"""Contrato del banco de preguntas de concepto (H7).

Comprueba que `evaluation/h3/concept-{calibration,validation}-v1.jsonl` son
JSONL válido, 12 casos cada uno, ids únicos, `expected_documents` dentro del
catálogo, y los mínimos de la spec H7:

- >= 6 casos multi-documento (``answerable`` o ``conversation`` cuyo
  ``expected_documents`` exige 2 o más fuentes): preguntas que solo se
  responden juntando evidencia de dos o más documentos.
- >= 2 ``answerable`` de un solo documento con datos graficables (uno sobre
  AGN-007 Revolución francesa y otro sobre AGN-003 diabetes o AGN-013 café),
  marcados con la etiqueta ``graficable``.
- >= 2 turnos de conversación formando un grupo completo de dos turnos cuyo
  seguimiento necesita la misma evidencia multi-documento.

La semántica (que cada pregunta sea respondible solo con los documentos que
declara) no es comprobable sin corpus: queda justificada con citas del texto
convertido en `docs/h7/concept-bank.md`.
"""
from __future__ import annotations

import collections
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANKS = {
    split: ROOT / "evaluation" / "h3" / f"concept-{split}-v1.jsonl"
    for split in ("calibration", "validation")
}
CATALOG = ROOT / "evaluation" / "h3" / "agnostic_corpus_catalog.json"
PREFIXES = {"calibration": "CON-CAL-", "validation": "CON-VAL-"}
KINDS = {"answerable", "conversation", "unanswerable", "ambiguous"}
LANGUAGES = {"es", "en"}
CASES_PER_BANK = 12
MULTIDOC_MINIMUM = 6
GRAPHABLE_MINIMUM = 2
CONVERSATION_MINIMUM = 2
REQUIRED_KEYS = {"id", "kind", "language", "query", "expected_documents", "expected_sections", "tags"}


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ConceptBankContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.banks = {split: load(path) for split, path in BANKS.items()}
        self.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["documents"]
        self.sources = {source["id"] for source in self.catalog}

    def test_each_bank_has_twelve_parseable_cases(self) -> None:
        for split, rows in self.banks.items():
            self.assertEqual(len(rows), CASES_PER_BANK, split)
            for row in rows:
                self.assertTrue(REQUIRED_KEYS <= set(row), row.get("id"))
                self.assertIsInstance(row["query"], str)
                self.assertTrue(row["query"].strip(), row.get("id"))
                self.assertIn(row["language"], LANGUAGES, row.get("id"))
                self.assertIsInstance(row["expected_documents"], list, row.get("id"))
                self.assertIsInstance(row["expected_sections"], list, row.get("id"))
                self.assertIsInstance(row["tags"], list, row.get("id"))
                self.assertTrue(row["id"].startswith(PREFIXES[split]), row.get("id"))

    def test_ids_are_unique_within_and_across_banks(self) -> None:
        rows = [row for bank in self.banks.values() for row in bank]
        self.assertEqual(len({row["id"] for row in rows}), len(rows))

    def test_kinds_follow_the_contract(self) -> None:
        for split, rows in self.banks.items():
            counts = collections.Counter(row["kind"] for row in rows)
            self.assertEqual(set(counts), KINDS, split)
            for row in rows:
                if row["kind"] in {"answerable", "conversation"}:
                    self.assertTrue(row["expected_documents"], row["id"])
                    self.assertLessEqual(set(row["expected_documents"]), self.sources, row["id"])
                else:
                    self.assertEqual(row["expected_documents"], [], row["id"])
                    self.assertEqual(row["expected_sections"], [], row["id"])

    def test_conversation_groups_are_complete_pairs(self) -> None:
        for split, rows in self.banks.items():
            groups: dict[str, list[dict]] = collections.defaultdict(list)
            for row in rows:
                if row["kind"] == "conversation":
                    self.assertTrue(row.get("conversation_id"), row["id"])
                    self.assertIsInstance(row.get("turn"), int, row["id"])
                    groups[row["conversation_id"]].append(row)
            self.assertTrue(groups, split)
            for conversation_id, turns in groups.items():
                turns.sort(key=lambda row: row["turn"])
                self.assertEqual([row["turn"] for row in turns], [1, 2], conversation_id)
                self.assertTrue(turns[0].get("subject") or turns[1].get("subject"), conversation_id)
                for row in turns[1:]:
                    self.assertTrue(row.get("subject"), row["id"])
            ids = {row["id"] for row in rows if row["kind"] == "conversation"}
            self.assertEqual(len(ids), sum(len(turns) for turns in groups.values()))

    def test_multidoc_evidence_minimum(self) -> None:
        for split, rows in self.banks.items():
            multi = [
                row
                for row in rows
                if row["kind"] in {"answerable", "conversation"}
                and len(row["expected_documents"]) >= 2
            ]
            self.assertGreaterEqual(len(multi), MULTIDOC_MINIMUM, split)

    def test_graphable_single_document_minimum(self) -> None:
        for split, rows in self.banks.items():
            graphable = [
                row
                for row in rows
                if row["kind"] == "answerable"
                and len(row["expected_documents"]) == 1
                and "graficable" in row["tags"]
            ]
            self.assertGreaterEqual(len(graphable), GRAPHABLE_MINIMUM, split)
            historical = [row for row in graphable if row["expected_documents"] == ["AGN-007"]]
            quantitative = [
                row
                for row in graphable
                if row["expected_documents"] in (["AGN-003"], ["AGN-013"])
            ]
            self.assertTrue(historical, split)
            self.assertTrue(quantitative, split)


if __name__ == "__main__":
    unittest.main()
