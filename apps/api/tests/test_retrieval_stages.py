"""H7: per-stage trace of retrieve — where the candidates disappear.

Instrumentation only: every trace carries `stages` (flag on or off) whose
counters square with the pools, the union, the rerank output, the assessed
evidence and the visibility control of the same run, without changing any
decision, order or content.
"""
import asyncio
import json

import pytest

from test_h1 import settings  # noqa: F401  (Settings builder for fixed values)
from test_multi_query import (CONTENT, QUESTION, Clients, FakeDB, FakeResult, fake_db,
                              fake_pools, run)
from bibliotecario.retrieval import retrieve, stage_counts

STAGE_KEYS = {"pools", "merged", "post_rerank", "assessed", "support",
              "visible", "dropped_invisible", "dropped_sample"}


# --- helper puro: invariantes y muestra truncada ---------------------------


def test_stage_counts_from_sixtyfive_to_zero():
    dropped = [f"chunk-{i:02d}" for i in range(65)]
    stages = stage_counts([30, 30, 30], 65, 65, 65, 0, 0, dropped)
    assert stages == {"pools": [30, 30, 30], "merged": 65, "post_rerank": 65, "assessed": 65,
                      "support": 0, "visible": 0, "dropped_invisible": 65,
                      "dropped_sample": dropped[:5]}


def test_stage_counts_from_sixtyfive_to_sixtyfive():
    stages = stage_counts([30, 30, 30], 65, 65, 65, 10, 65, [])
    assert stages == {"pools": [30, 30, 30], "merged": 65, "post_rerank": 65, "assessed": 65,
                      "support": 10, "visible": 65, "dropped_invisible": 0, "dropped_sample": []}


def test_stage_counts_from_thirty_to_twentyeight_with_two_sample_ids():
    stages = stage_counts([30], 30, 30, 30, 3, 28, ["c-07", "c-19"])
    assert stages == {"pools": [30], "merged": 30, "post_rerank": 30, "assessed": 30,
                      "support": 3, "visible": 28, "dropped_invisible": 2,
                      "dropped_sample": ["c-07", "c-19"]}


def test_stage_counts_truncates_the_sample_to_five_ids():
    dropped = [f"c-{i:02d}" for i in range(12)]
    stages = stage_counts([12], 12, 12, 12, 0, 0, dropped)
    assert stages["dropped_invisible"] == 12 and stages["dropped_sample"] == dropped[:5]


@pytest.mark.parametrize("args", [
    ([30, 30, 30], 65, 65, 65, 0, 66, []),    # visible > assessed
    ([30, 30, 30], 65, 65, 65, 66, 65, []),   # support > assessed
    ([30, 30, 30], 65, 65, 65, 0, 60, []),    # dropped ids missing for the difference
    ([30, 30, 30], 65, 65, 65, 0, 65, ["a"]), # nothing dropped but ids recorded
    ([30, 30, 30], 65, 65, 65, -1, 65, []),   # negative support
])
def test_stage_counts_rejects_broken_invariants(args):
    with pytest.raises(ValueError):
        stage_counts(*args)


# --- trazas de retrieve: los contadores cuadran con el mismo resultado -----


class DroppingVisibilityDB(FakeDB):
    """Same session double, but the post-assessment visibility control keeps
    only a subset of the registered chunks."""

    def __init__(self, chunks, versions, visible_ids):
        super().__init__(chunks, versions)
        self.visible_ids = visible_ids

    def scalars(self, stmt):
        if "evidence_policies" in str(stmt):
            return FakeResult([])
        return FakeResult([cid for cid in self.chunks if cid in self.visible_ids])


def test_trace_with_flag_off_records_stages_matching_the_result(monkeypatch, tmp_path):
    result, _, _ = run(settings(tmp_path), Clients(), monkeypatch)
    stages = result["stages"]
    assert set(stages) == STAGE_KEYS
    assert stages["pools"] == result["retrieval"]["pools"] == [2]
    assert stages["merged"] == result["retrieval"]["merged"] == 2
    assert stages["post_rerank"] == stages["assessed"] == 2
    assert stages["support"] == len(result["assessment"]["support"]) == 1
    assert stages["visible"] == len(result["candidates"]) == 2
    assert stages["dropped_invisible"] == stages["assessed"] - stages["visible"] == 0
    assert stages["dropped_sample"] == []
    # Nothing changed: same candidates, same decision, same results as the
    # expectations the multi-query suite already fixes for this path.
    assert [c["chunk_id"] for c in result["candidates"]] == ["a2", "a1"]
    assert result["decision"]["reason"] == "uncalibrated"


def test_trace_with_flag_on_records_stages_matching_the_result(monkeypatch, tmp_path):
    result, _, _ = run(settings(tmp_path, multi_query=True), Clients(), monkeypatch)
    stages = result["stages"]
    assert set(stages) == STAGE_KEYS
    assert stages["pools"] == result["retrieval"]["pools"] == [2, 2, 3]
    assert stages["merged"] == result["retrieval"]["merged"] == 5
    assert stages["post_rerank"] == stages["assessed"] == 5
    assert stages["support"] == len(result["assessment"]["support"]) == 1
    assert stages["visible"] == len(result["candidates"]) == 5
    assert stages["dropped_invisible"] == stages["assessed"] - stages["visible"] == 0
    assert stages["dropped_sample"] == []
    assert [c["chunk_id"] for c in result["candidates"]] == ["f1", "f2", "a2", "a3", "a1"]
    assert [c["chunk_id"] for c in result["results"]] == ["f1"]
    assert result["decision"]["reason"] == "uncalibrated"


def test_trace_records_what_the_visibility_control_drops(monkeypatch, tmp_path):
    fake_pools(monkeypatch)
    monkeypatch.setattr("bibliotecario.retrieval.expand_context",
                        lambda db, candidates: list(candidates))
    base = fake_db()
    result = asyncio.run(retrieve(DroppingVisibilityDB(base.chunks, base.versions, {"a2"}),
                                  settings(tmp_path), Clients(), QUESTION))
    stages = result["stages"]
    assert stages["assessed"] == 2 and stages["visible"] == 1
    assert stages["dropped_invisible"] == stages["assessed"] - stages["visible"] == 1
    assert stages["dropped_sample"] == ["a1"]
    assert stages["visible"] == len(result["candidates"]) == 1
    assert [c["chunk_id"] for c in result["candidates"]] == ["a2"]


def test_trace_records_the_union_drops_in_order_with_flag_on(monkeypatch, tmp_path):
    fake_pools(monkeypatch)
    monkeypatch.setattr("bibliotecario.retrieval.expand_context",
                        lambda db, candidates: list(candidates))
    base = fake_db()
    result = asyncio.run(retrieve(DroppingVisibilityDB(base.chunks, base.versions, {"f1", "f2"}),
                                  settings(tmp_path, multi_query=True), Clients(), QUESTION))
    stages = result["stages"]
    assert stages["pools"] == [2, 2, 3] and stages["merged"] == 5
    assert stages["assessed"] == 5 and stages["visible"] == 2
    assert stages["dropped_invisible"] == 3
    assert stages["dropped_sample"] == ["a2", "a3", "a1"]  # candidate order, not set order
    assert len(result["candidates"]) == 2 and len(result["results"]) == 1


def test_trace_distinguishes_an_abstention_from_an_emptied_support(monkeypatch, tmp_path):
    # The support chunk itself is withdrawn between assess and the visibility
    # control: the evaluator said answer with one source, but the stored run
    # ends with empty results. The trace shows exactly where they went — the
    # 65->0 phenomenon of the H7 acceptance, at trace scale.
    fake_pools(monkeypatch)
    monkeypatch.setattr("bibliotecario.retrieval.expand_context",
                        lambda db, candidates: list(candidates))
    base = fake_db()
    result = asyncio.run(retrieve(DroppingVisibilityDB(base.chunks, base.versions, {"a1"}),
                                  settings(tmp_path), Clients(), QUESTION))
    stages = result["stages"]
    assert result["assessment"]["action"] == "answer" and stages["support"] == 1
    assert stages["assessed"] == 2 and stages["visible"] == 1
    assert stages["dropped_invisible"] == 1 and stages["dropped_sample"] == ["a2"]
    assert [c["chunk_id"] for c in result["candidates"]] == ["a1"]
    assert result["results"] == []


def test_trace_of_an_empty_turn_keeps_every_counter_at_zero(monkeypatch, tmp_path):
    fake_pools(monkeypatch, {QUESTION: ([], [])})
    monkeypatch.setattr("bibliotecario.retrieval.expand_context",
                        lambda db, candidates: list(candidates))
    result = asyncio.run(retrieve(fake_db(), settings(tmp_path), Clients(), QUESTION))
    assert result["stages"] == {"pools": [0], "merged": 0, "post_rerank": 0, "assessed": 0,
                                "support": 0, "visible": 0, "dropped_invisible": 0,
                                "dropped_sample": []}
    assert result["assessment"]["reason"] == "no_evidence"
    assert result["candidates"] == [] and result["results"] == []


def test_stages_carry_no_passage_text_titles_or_secrets(monkeypatch, tmp_path):
    result, _, _ = run(settings(tmp_path, multi_query=True), Clients(), monkeypatch)
    trace = json.dumps(result["stages"])
    assert set(result["stages"]) == STAGE_KEYS
    for passage in CONTENT.values():
        assert passage not in trace
    assert "Título" not in trace
    # The only strings in the trace are chunk identifiers.
    assert all(isinstance(stage, (int, list)) for stage in result["stages"].values())
    assert all(cid in CONTENT for cid in result["stages"]["dropped_sample"])
