from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "h4"))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from facet_acceptance import (  # noqa: E402
    CLOSING,
    build_summary,
    check_case,
    closing_counts,
    content_markers,
    source_markers,
)

CASE_BOTH = {
    "id": "FAC-VAL-001",
    "kind": "both",
    "language": "es",
    "query": "¿Por qué son importantes las abejas para las cosechas y qué produce la fotosíntesis?",
    "parts": [
        {"query": "¿Por qué son importantes las abejas para las cosechas?", "expected_documents": ["AGN-001"]},
        {"query": "¿Qué produce la fotosíntesis?", "expected_documents": ["AGN-008"]},
    ],
    "expected": "both",
    "tags": ["multidocumento", "biologia"],
}

MAPPING = {"AGN-001": "d-bees", "AGN-008": "d-photo"}


def fixture(kind="both", parts_length=2, closing=1, content=None, sources=None,
            part_statuses=None, pool_docs=(("d-bees",), ("d-photo",)),
            cited=(("d-bees",), ("d-photo",)), outcome_status=None):
    """Hand-built message + trace fixture for one two-part turn.

    Pools and citations use the mapped ids directly (d-bees = mapped AGN-001,
    d-photo = mapped AGN-008). ``cited`` decides which documents each part
    cites; ``pool_docs`` decides what each part's retrieval pool holds.
    """
    parts = []
    for index in range(parts_length):
        pool = list(pool_docs[index]) if index < len(pool_docs) else []
        parts.append({"results": [{"chunk_id": f"ch-{index}-{n}", "document_id": doc}
                                  for n, doc in enumerate(pool)],
                      "query": f"parte {index}"})
    flat_cited = [doc for group in cited for doc in group]
    if sources is None:
        sources = [{"citation_id": f"C{i + 1}", "chunk_id": f"ch-{i}-0", "document_id": doc}
                   for i, doc in enumerate(flat_cited)]
    if content is None:
        markers = " ".join(f"[C{i + 1}]" for i in range(len(sources)))
        body = (markers + " " if markers else "") + (CLOSING if closing >= 1 else "Respuesta breve.")
        if closing == 2:
            body += " " + CLOSING
    else:
        body = content
    statuses = part_statuses if part_statuses is not None else ("completed", "completed")
    trace = {"parts": parts,
             "chat_outcome": {"status": outcome_status or ("completed" if kind != "none" else "abstained"),
                              "reason": "grounded" if kind != "none" else "no_evidence",
                              "parts": [{"status": statuses[i] if i < len(statuses) else "abstained",
                                         "reason": "ok", "citations": 1, "documents": 1}
                                        for i in range(parts_length)]}}
    # The bank case shape follows the kind: both parts expect documents in
    # `both`, only the first in `partial`, none in `none`.
    if kind == "both":
        case_parts = [{"query": "parte 1", "expected_documents": ["AGN-001"]},
                      {"query": "parte 2", "expected_documents": ["AGN-008"]}]
    elif kind == "partial":
        case_parts = [{"query": "parte 1", "expected_documents": ["AGN-001"]},
                      {"query": "parte 2", "expected_documents": []}]
    else:
        case_parts = [{"query": "parte 1", "expected_documents": []},
                      {"query": "parte 2", "expected_documents": []}]
    case = CASE_BOTH | {"kind": kind, "parts": case_parts}
    message = {"content": body, "sources": sources,
               "status": "completed" if kind != "none" else "abstained"}
    return case, message, trace, MAPPING


class PureHelperTests(unittest.TestCase):
    def test_closing_counts_literal_sentence(self) -> None:
        self.assertEqual(closing_counts(f"x {CLOSING} y"), 1)
        self.assertEqual(closing_counts(f"{CLOSING} {CLOSING}"), 2)
        self.assertEqual(closing_counts("sin cierre"), 0)
        self.assertEqual(closing_counts(None), 0)

    def test_markers_bidirectional(self) -> None:
        sources = [{"citation_id": "C1", "chunk_id": "a", "document_id": "d"}]
        self.assertEqual(content_markers("a [C1] b"), {"[C1]"})
        self.assertEqual(source_markers(sources), {"[C1]"})
        self.assertEqual(content_markers("a [C9]"), {"[C9]"})


class CheckCaseTests(unittest.TestCase):
    def test_correct_both_case_passes(self) -> None:
        case, message, trace, mapping = fixture()
        self.assertEqual(check_case(case, message, trace, mapping), [])

    def test_part_answers_without_its_documents(self) -> None:
        # Part 2's pool holds nothing of AGN-008, so it cites nothing expected.
        case, message, trace, mapping = fixture(pool_docs=(("d-bees",), ("d-bees",)),
                                                cited=(("d-bees",), ("d-bees",)))
        failures = check_case(case, message, trace, mapping)
        self.assertIn("part_missing_document", failures)
        self.assertIn("part_outside_document", failures)

    def test_part_missing_document_alone(self) -> None:
        # Part 2 retrieves AGN-008 but cites nothing: missing, not outside.
        sources = [{"citation_id": "C1", "chunk_id": "ch-0-0", "document_id": "d-bees"}]
        case, message, trace, mapping = fixture(pool_docs=(("d-bees",), ("d-photo",)),
                                                cited=(("d-bees",),), sources=sources,
                                                content="[C1] " + CLOSING)
        self.assertIn("part_missing_document", check_case(case, message, trace, mapping))

    def test_part_that_should_abstain_but_answers(self) -> None:
        # none case: both parts answer and cite -> improper + global status.
        case, message, trace, mapping = fixture(kind="none", outcome_status="completed")
        failures = check_case(case, message, trace, mapping)
        self.assertIn("improper_answer", failures)
        self.assertIn("global_status", failures)

    def test_partial_case_with_out_of_corpus_part_answers(self) -> None:
        # partial: part 2 is out of corpus but the turn answers it anyway.
        case, message, trace, mapping = fixture(kind="partial", outcome_status="completed")
        failures = check_case(case, message, trace, mapping)
        self.assertIn("improper_answer", failures)
        # A correct partial turn passes: part 1 answers, part 2 abstains.
        case, message, trace, mapping = fixture(kind="partial", part_statuses=("completed", "abstained"),
                                                pool_docs=(("d-bees",),), cited=(("d-bees",),),
                                                sources=[{"citation_id": "C1", "chunk_id": "ch-0-0",
                                                          "document_id": "d-bees"}],
                                                content="[C1] " + CLOSING)
        self.assertEqual(check_case(case, message, trace, mapping), [])

    def test_closing_repeated(self) -> None:
        case, message, trace, mapping = fixture(closing=2)
        self.assertIn("closing_repeated", check_case(case, message, trace, mapping))

    def test_closing_missing(self) -> None:
        case, message, trace, mapping = fixture(closing=0)
        self.assertIn("closing_missing", check_case(case, message, trace, mapping))

    def test_closing_present_in_none_case(self) -> None:
        case, message, trace, mapping = fixture(kind="none", closing=1)
        self.assertIn("closing_present", check_case(case, message, trace, mapping))

    def test_orphan_marker(self) -> None:
        # [C3] in the content without a matching source.
        case, message, trace, mapping = fixture(content="[C1] [C3] " + CLOSING)
        self.assertIn("orphan_marker", check_case(case, message, trace, mapping))

    def test_uncited_source(self) -> None:
        # Source C2 exists but the content never cites it.
        case, message, trace, mapping = fixture(content="[C1] " + CLOSING)
        self.assertIn("uncited_source", check_case(case, message, trace, mapping))

    def test_parts_with_length_one(self) -> None:
        # Trace holds a single part for a two-part case.
        case, message, trace, mapping = fixture(parts_length=1,
                                                cited=(("d-bees",), ("d-bees",)))
        failures = check_case(case, message, trace, mapping)
        self.assertIn("parts_length", failures)

    def test_document_ids_fallback_attributes_citations(self) -> None:
        # Without a retrieval pool, explicit document_ids on the outcome part
        # attribute the global sources to each part.
        case, message, trace, mapping = fixture(pool_docs=((), ()),
                                                sources=[{"citation_id": "C1", "chunk_id": "ch-x",
                                                          "document_id": "d-bees"},
                                                         {"citation_id": "C2", "chunk_id": "ch-y",
                                                          "document_id": "d-photo"}],
                                                content="[C1] [C2] " + CLOSING)
        trace["chat_outcome"]["parts"][0]["document_ids"] = ["d-bees"]
        trace["chat_outcome"]["parts"][1]["document_ids"] = ["d-photo"]
        self.assertEqual(check_case(case, message, trace, mapping), [])

    def test_part_unattributable(self) -> None:
        # No pool and no document_ids: the part's citations cannot be judged.
        case, message, trace, mapping = fixture(pool_docs=((), ()),
                                                sources=[{"citation_id": "C1", "chunk_id": "ch-x",
                                                          "document_id": "d-bees"}],
                                                content="[C1] " + CLOSING)
        failures = check_case(case, message, trace, mapping)
        self.assertIn("part_unattributable", failures)

    def test_none_case_with_empty_sources_passes(self) -> None:
        # Correct none turn: no sources, both parts abstain, no closing sentence.
        case, message, trace, mapping = fixture(kind="none", pool_docs=((), ()),
                                                cited=((), ()), closing=0,
                                                part_statuses=("abstained", "abstained"))
        self.assertEqual(check_case(case, message, trace, mapping), [])

    def test_partial_control_case_bees_part_abstains(self) -> None:
        # The over-specified original question is the partial control
        # (FAC-VAL-011): part 1 (bees in plant reproduction) is out of corpus
        # and abstains even though its pool holds the right document; part 2
        # (photosynthesis products) answers with AGN-008.
        case = {"id": "FAC-VAL-011", "kind": "partial", "language": "es",
                "query": "¿Qué hacen las abejas en la reproducción de las plantas y qué produce la fotosíntesis?",
                "parts": [{"query": "¿Qué hacen las abejas en la reproducción de las plantas?", "expected_documents": []},
                          {"query": "¿Qué produce la fotosíntesis?", "expected_documents": ["AGN-008"]}],
                "expected": "partial", "tags": ["parcial", "biologia", "fuera de corpus"]}
        _, message, trace, mapping = fixture(kind="partial", part_statuses=("abstained", "completed"),
                                             pool_docs=(("d-bees",), ("d-photo",)),
                                             cited=((), ("d-photo",)),
                                             sources=[{"citation_id": "C1", "chunk_id": "ch-1-0",
                                                       "document_id": "d-photo"}],
                                             content="[C1] " + CLOSING)
        self.assertEqual(check_case(case, message, trace, mapping), [])
        # If the corpus-limit part answers anyway, the case fails.
        case, message, trace, mapping = fixture(kind="partial", part_statuses=("completed", "completed"))
        self.assertIn("improper_answer", check_case(case, message, trace, mapping))


def summary_row(kind="both", passed=True, failures=(), chat_latency=None, case_id="FAC-VAL-001"):
    """One acceptance row with only the keys build_summary reads."""
    return {"id": case_id, "kind": kind, "language": "es", "domain": "biología", "tags": [],
            "status": "completed" if kind != "none" else "abstained", "parts": [], "chat_outcome": {},
            "chat_latency": chat_latency, "seconds": 1.0, "failures": list(failures), "passed": passed}


class BuildSummaryTests(unittest.TestCase):
    def test_summary_includes_latency_percentiles(self) -> None:
        rows = [summary_row(chat_latency={"total_ms": 27000}),
                summary_row(case_id="FAC-VAL-002", chat_latency={"total_ms": 11000})]
        summary = build_summary(rows, ["facet-validation-v1.jsonl"], "admin", date="2026-11-13")
        # Nearest-rank percentiles over chat_latency.total_ms, as reported.
        self.assertEqual(summary["latency"], {"n": 2, "p50": 11000, "p95": 27000})
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["by_kind"], {"both": {"passed": 2, "total": 2}})
        self.assertEqual(summary["date"], "2026-11-13")

    def test_summary_composes_from_rows_with_and_without_chat_latency(self) -> None:
        # A row whose trace failed to load carries no chat_latency: it still
        # counts for the totals and the failure counters, never for p50/p95.
        rows = [summary_row(chat_latency={"total_ms": 12000}),
                summary_row(case_id="FAC-VAL-011", kind="partial", passed=False,
                            failures=["part_missing_document"], chat_latency=None),
                summary_row(case_id="FAC-VAL-010", kind="none")]
        summary = build_summary(rows, ["bank.jsonl"], "admin", date="2026-11-13")
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["latency"], {"n": 1, "p50": 12000, "p95": 12000})
        self.assertEqual(summary["by_kind"], {"both": {"passed": 1, "total": 1},
                                              "partial": {"passed": 0, "total": 1},
                                              "none": {"passed": 1, "total": 1}})
        self.assertEqual(summary["failures"], {"part_missing_document": 1})
        self.assertEqual(summary["improper"], 0)

    def test_summary_counts_improper_and_empty_latency(self) -> None:
        rows = [summary_row(case_id="FAC-VAL-011", kind="partial", passed=False,
                            failures=["improper_answer"], chat_latency=None)]
        summary = build_summary(rows, ["bank.jsonl"], "admin", date="2026-11-13")
        self.assertEqual(summary["improper"], 1)
        self.assertEqual(summary["latency"], {"n": 0, "p50": None, "p95": None})


if __name__ == "__main__":
    unittest.main()
