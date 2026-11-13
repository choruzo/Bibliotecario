"""H7: multi-query retrieval for questions that need evidence from several documents."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from test_h1 import settings  # noqa: F401  (Settings builder for fixed values)
from bibliotecario.facets import DECOMPOSE_MAX_TOKENS, DECOMPOSE_PROMPT, PLAN_PROMPT, Facets, decompose, plan_parts
from bibliotecario.models import Chunk, DocumentVersion
from bibliotecario.providers import ProviderError
from bibliotecario.retrieval import retrieve
from bibliotecario.sufficiency import policy_signature

QUESTION = "¿Cómo se relacionan las abejas y la fotosíntesis?"
FACET_A = "cómo pican las abejas"
FACET_F = "proceso de la fotosíntesis"
FACETS_JSON = json.dumps({"facets": [FACET_A, FACET_F]}, ensure_ascii=False)
GOLDEN_MAIN = "0e6d0d3cada37dd828f42e1c1f95ea2050bd9cc62be245e81672a87963574468"

CONTENT = {"a1": "Las abejas polinizan flores.", "a2": "Las abejas viven en colmenas.",
           "a3": "Las abejas obreras trabajan.", "f1": "La fotosíntesis convierte la luz.",
           "f2": "La fotosíntesis produce oxígeno."}


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class FakeDB:
    """Just enough session for retrieve(): chunk/version lookups, an always-empty
    policy store (uncalibrated decision) and a visibility re-check that keeps
    every registered chunk. Context expansion is replaced by a spy."""

    def __init__(self, chunks, versions):
        self.chunks, self.versions = chunks, versions

    def rollback(self):
        pass

    def execute(self, *args, **kwargs):
        return FakeResult([])

    def scalar(self, *args, **kwargs):
        return None

    def scalars(self, stmt):
        if "evidence_policies" in str(stmt):
            return FakeResult([])
        return FakeResult(list(self.chunks))

    def get(self, model, id):
        return (self.chunks if model is Chunk else self.versions).get(id)


class Clients:
    """Provider doubles recording every call in order; generate dispatches on schema."""

    def __init__(self, facets=FACETS_JSON, fail=None, latency=0.0):
        self.facets_raw, self.fail, self.latency = facets, fail, latency
        self.calls, self.embed_calls, self.rerank_calls = [], [], []

    async def embedding_tokens(self, content):
        self.calls.append(("tokens", content))
        return 10

    async def embed(self, texts, query=False):
        await asyncio.sleep(self.latency)
        self.calls.append(("embed", list(texts), query))
        self.embed_calls.append((list(texts), query))
        return [[float(i), 1.0, 0.0] for i, _ in enumerate(texts)]

    async def generate(self, messages, **kwargs):
        await asyncio.sleep(self.latency)
        schema = kwargs["response_schema"]
        if "facets" in schema["properties"]:
            self.calls.append(("decompose", messages[1]["content"], kwargs.get("max_tokens")))
            if self.fail:
                raise self.fail
            return self.facets_raw
        if "clear" in schema["properties"]:
            self.calls.append(("intent", json.loads(messages[1]["content"])["question"]))
            return '{"clear": true}'
        payload = json.loads(messages[1]["content"])
        self.calls.append(("assess", payload["question"], [s["chunk_id"] for s in payload["sources"]]))
        return json.dumps({"action": "answer", "coverage_complete": True, "contradiction": False,
                           "support": [{"chunk_id": payload["sources"][0]["chunk_id"]}]})

    async def rerank(self, query, documents):
        await asyncio.sleep(self.latency)
        self.calls.append(("rerank", query, list(documents)))
        self.rerank_calls.append((query, list(documents)))
        # The second aspect outranks the first: the reorder must be observable.
        rows = [{"index": i, "relevance_score": (0.9 if "fotosíntesis" in doc else 0.5) - i * 0.001}
                for i, doc in enumerate(documents)]
        return sorted(rows, key=lambda row: -row["relevance_score"])


def row(channel, cid, rank, score):
    return {"channel": channel, "id": cid, "score": score, "rank": rank}


POOL_ROWS = {
    QUESTION: ([row("vector", "a1", 1, 0.9), row("vector", "a2", 2, 0.8)], [row("text", "a2", 1, 0.7)]),
    FACET_A: ([row("vector", "a1", 1, 0.9), row("vector", "a3", 2, 0.8)], [row("text", "a3", 1, 0.7)]),
    FACET_F: ([row("vector", "f1", 1, 0.9), row("vector", "f2", 2, 0.8)], [row("text", "a1", 1, 0.7)]),
}


def fake_pools(monkeypatch, rows=None):
    calls = []

    def candidate_pools(db, vector, query, signature, document_id, admin):
        calls.append((query, vector[0]))
        return (rows or POOL_ROWS)[query]

    monkeypatch.setattr("bibliotecario.retrieval.candidate_pools", candidate_pools)
    return calls


def fake_db():
    chunks = {cid: SimpleNamespace(id=cid, version_id=f"v-{cid}", revision_id=f"rev-{cid}", number=1,
                                   content=CONTENT[cid], search_content=CONTENT[cid],
                                   provenance=[{"section_path": ["Guía"]}]) for cid in CONTENT}
    versions = {f"v-{cid}": SimpleNamespace(id=f"v-{cid}", document_id=f"doc-{cid[0]}", number=1,
                                            metadata_json={"title": f"Título {cid}"}) for cid in CONTENT}
    return FakeDB(chunks, versions)


def spy_expand(monkeypatch):
    calls = []
    monkeypatch.setattr("bibliotecario.retrieval.expand_context",
                        lambda db, candidates:
                        calls.append([c["chunk_id"] for c in candidates]) or list(candidates))
    return calls


def run(settings_obj, clients, monkeypatch):
    pools = fake_pools(monkeypatch)
    expanded = spy_expand(monkeypatch)
    result = asyncio.run(retrieve(fake_db(), settings_obj, clients, QUESTION))
    return result, pools, expanded


def test_facets_schema_is_closed_and_bounded():
    schema = Facets.model_json_schema()
    assert schema["additionalProperties"] is False and schema["required"] == ["facets"]
    facets = schema["properties"]["facets"]
    assert facets["maxItems"] == 2 and facets["type"] == "array"
    assert facets["items"] == {"type": "string", "minLength": 3, "maxLength": 120}
    for raw in ['{"facets": ["ab"]}', '{"facets": ["%s"]}' % ("a" * 121),
                '{"facets": ["una", "dos", "tres"]}', '{"facets": [], "extra": 1}',
                '{"facets": [123]}', '{}']:
        with pytest.raises(ValueError):
            Facets.model_validate_json(raw)
    assert Facets.model_validate_json('{"facets": []}').facets == []


def test_decompose_asks_for_selfcontained_facets_with_the_closed_schema():
    recorded = []

    class Generate:
        async def generate(self, messages, **kwargs):
            recorded.append((messages, kwargs))
            return '{"facets": ["cómo pican las abejas", "proceso de la fotosíntesis"]}'

    assert asyncio.run(decompose(Generate(), "¿Pican las abejas y cómo funciona la fotosíntesis?")) == \
        ["cómo pican las abejas", "proceso de la fotosíntesis"]
    messages, kwargs = recorded[0]
    assert messages[0]["content"] == DECOMPOSE_PROMPT and messages[1]["content"].startswith("¿Pican")
    assert kwargs["max_tokens"] == DECOMPOSE_MAX_TOKENS
    assert kwargs["response_schema"] == Facets.model_json_schema()


def test_decompose_single_topic_returns_empty():
    class Generate:
        async def generate(self, messages, **kwargs):
            return '{"facets": []}'

    assert asyncio.run(decompose(Generate(), "¿Cuántos días vive una abeja reina?")) == []


def test_decompose_deduplicates_drops_question_repeats_and_caps_at_two():
    class Generate:
        def __init__(self, raw):
            self.raw = raw

        async def generate(self, messages, **kwargs):
            return self.raw

    def facets(raw):
        return asyncio.run(decompose(Generate(raw), QUESTION))

    # Whitespace is collapsed; case/accent variants of the same facet deduplicate.
    raw = json.dumps({"facets": ["  cómo pican las abejas  ", "Cómo PICAN las abejas"]}, ensure_ascii=False)
    assert facets(raw) == [FACET_A]
    # A facet repeating the original question, or containing it, is dropped: the
    # question already gets its own pool.
    raw = json.dumps({"facets": [QUESTION, "proceso de la fotosíntesis"]}, ensure_ascii=False)
    assert facets(raw) == [FACET_F]
    raw = json.dumps({"facets": [f"{QUESTION} explicado", "proceso de la fotosíntesis"]}, ensure_ascii=False)
    assert facets(raw) == [FACET_F]
    # Two cleaned facets are the maximum the schema admits.
    raw = json.dumps({"facets": ["cómo pican las abejas", "proceso de la fotosíntesis"]}, ensure_ascii=False)
    assert facets(raw) == [FACET_A, FACET_F]


def test_plan_parts_uses_its_own_prompt_with_the_closed_schema():
    """plan_parts is decompose's sibling, not a flag on it: own prompt, same schema."""
    recorded = []

    class Generate:
        async def generate(self, messages, **kwargs):
            recorded.append((messages, kwargs))
            return '{"facets": ["cómo pican las abejas", "proceso de la fotosíntesis"]}'

    assert asyncio.run(plan_parts(Generate(), "¿Pican las abejas y cómo funciona la fotosíntesis?")) == \
        ["cómo pican las abejas", "proceso de la fotosíntesis"]
    messages, kwargs = recorded[0]
    assert messages[0]["content"] == PLAN_PROMPT and messages[1]["content"].startswith("¿Pican")
    assert kwargs["max_tokens"] == DECOMPOSE_MAX_TOKENS
    assert kwargs["response_schema"] == Facets.model_json_schema()
    # The two contracts live in the two prompts, verbatim: decompose drops a
    # facet that repeats the question (multi-query retrieves the original
    # anyway); plan_parts keeps literal fragments (H8 never retrieves it) and
    # must not invent topics for a single-topic question.
    assert "No repitas la pregunta original como facet" in DECOMPOSE_PROMPT
    assert "no la descartes ni la parafrasees por aparecer en la pregunta" in PLAN_PROMPT
    assert 'Si la pregunta tiene un solo tema, devuelve {"facets": []}' in PLAN_PROMPT


def test_plan_parts_keeps_a_question_fragment_that_decompose_drops():
    """The golden pair: one doubled answer, one part equal to a literal chunk
    of the question. decompose discards it (multi-query already retrieves the
    original); plan_parts conserves it (the facet route needs both answers)."""
    raw = json.dumps({"facets": [QUESTION, FACET_F]}, ensure_ascii=False)

    class Generate:
        async def generate(self, messages, **kwargs):
            return raw

    assert asyncio.run(decompose(Generate(), QUESTION)) == [FACET_F]
    assert asyncio.run(plan_parts(Generate(), QUESTION)) == [QUESTION, FACET_F]


def test_plan_parts_deduplicates_between_parts_and_caps_at_two():
    class Generate:
        def __init__(self, raw):
            self.raw = raw

        async def generate(self, messages, **kwargs):
            return self.raw

    def parts(raw):
        return asyncio.run(plan_parts(Generate(raw), QUESTION))

    # Whitespace is collapsed; case/accent variants deduplicate between parts.
    raw = json.dumps({"facets": ["  cómo pican las abejas  ", "Cómo PICAN las abejas"]}, ensure_ascii=False)
    assert parts(raw) == [FACET_A]
    raw = json.dumps({"facets": ["cómo pican las abejas", "proceso de la fotosíntesis"]}, ensure_ascii=False)
    assert parts(raw) == [FACET_A, FACET_F]
    # Only duplicates BETWEEN the parts are dropped: a part contained in the
    # question itself is a valid sub-question here, unlike in decompose.
    raw = json.dumps({"facets": ["las abejas y la fotosíntesis", "las abejas"]}, ensure_ascii=False)
    assert parts(raw) == ["las abejas y la fotosíntesis", "las abejas"]


def test_plan_parts_single_topic_returns_empty():
    class Generate:
        async def generate(self, messages, **kwargs):
            return '{"facets": []}'

    assert asyncio.run(plan_parts(Generate(), "¿Cuántos días vive una abeja reina?")) == []


def test_plan_parts_never_raises_and_reports_a_fixed_error_code():
    class Generate:
        def __init__(self, raw, fail):
            self.raw, self.fail = raw, fail

        async def generate(self, messages, **kwargs):
            if self.fail:
                raise self.fail
            return self.raw

    for clients, expected in [
            (Generate(None, ProviderError("incomplete_generation")), "incomplete_generation"),
            (Generate(None, httpx.TimeoutException("slow")), "provider_timeout"),
            (Generate(None, httpx.ConnectError("down")), "provider_error"),
            (Generate("no soy json", None), "invalid_facets"),
            (Generate(json.dumps({"facets": ["ab"]}), None), "invalid_facets"),
            (Generate(json.dumps({"facets": ["a" * 121]}), None), "invalid_facets")]:
        diagnostics = {}
        assert asyncio.run(plan_parts(clients, QUESTION, diagnostics)) == []
        assert diagnostics["error"] == expected
    # Without a diagnostics dict the degradation is silent, never an exception.
    assert asyncio.run(plan_parts(Generate(None, ProviderError("invalid_generation")), QUESTION)) == []


def test_decompose_never_raises_and_reports_a_fixed_error_code():
    class Generate:
        def __init__(self, raw, fail):
            self.raw, self.fail = raw, fail

        async def generate(self, messages, **kwargs):
            if self.fail:
                raise self.fail
            return self.raw

    for clients, expected in [
            (Generate(None, ProviderError("incomplete_generation")), "incomplete_generation"),
            (Generate(None, httpx.TimeoutException("slow")), "provider_timeout"),
            (Generate(None, httpx.ConnectError("down")), "provider_error"),
            (Generate("no soy json", None), "invalid_facets"),
            (Generate(json.dumps({"facets": ["ab"]}), None), "invalid_facets"),
            (Generate(json.dumps({"facets": ["a" * 121]}), None), "invalid_facets")]:
        diagnostics = {}
        assert asyncio.run(decompose(clients, QUESTION, diagnostics)) == []
        assert diagnostics["error"] == expected
    # Without a diagnostics dict the degradation is silent, never an exception.
    assert asyncio.run(decompose(Generate(None, ProviderError("invalid_generation")), QUESTION)) == []


def test_flag_off_never_decomposes_and_keeps_today_single_query_path(monkeypatch, tmp_path):
    def forbidden(clients, question, diagnostics=None):
        raise AssertionError("decompose must not run while the flag is off")

    monkeypatch.setattr("bibliotecario.retrieval.decompose", forbidden)
    clients = Clients()
    result, pools, _ = run(settings(tmp_path), clients, monkeypatch)
    assert clients.embed_calls == [([QUESTION], True)]
    assert [query for query, _ in pools] == [QUESTION]
    assert len(clients.rerank_calls) == 1 and clients.rerank_calls[0][0] == QUESTION
    assert [c["chunk_id"] for c in result["candidates"]] == ["a2", "a1"]
    assert result["retrieval"] == {"facets": [], "facet_error": None, "merged": 2, "pools": [2]}


def test_policy_signature_stays_main_until_the_flag_turns_on(tmp_path):
    off = settings(tmp_path)
    assert off.multi_query is False
    assert policy_signature(off) == GOLDEN_MAIN
    assert policy_signature(settings(tmp_path, multi_query=True)) != GOLDEN_MAIN


def test_two_facets_embed_once_pool_three_queries_and_rerank_once(monkeypatch, tmp_path):
    clients = Clients()
    result, pools, expanded = run(settings(tmp_path, multi_query=True), clients, monkeypatch)
    # One single embed call covering the original question and both facets.
    assert clients.embed_calls == [([QUESTION, FACET_A, FACET_F], True)]
    # One candidate pool per query, each with its own vector, in order.
    assert [query for query, _ in pools] == [QUESTION, FACET_A, FACET_F]
    assert [vector for _, vector in pools] == [0.0, 1.0, 2.0]
    assert result["retrieval"] == {"facets": [FACET_A, FACET_F], "facet_error": None,
                                   "merged": 5, "pools": [2, 2, 3]}
    # Union without duplicates, reranked once with the composite query.
    assert len({c["chunk_id"] for c in result["candidates"]}) == 5
    assert len(clients.rerank_calls) == 1
    assert clients.rerank_calls[0][0] == f"{QUESTION} {FACET_A} {FACET_F}"
    assert [c["chunk_id"] for c in result["candidates"]] == ["f1", "f2", "a2", "a3", "a1"]
    assert len(expanded) == 1  # exactly one expand_context over the whole union


def test_chunk_present_in_two_pools_is_counted_once_with_channels_of_both(monkeypatch, tmp_path):
    result, _, _ = run(settings(tmp_path, multi_query=True), Clients(), monkeypatch)
    shared = [c for c in result["candidates"] if c["chunk_id"] == "a1"]
    assert len(shared) == 1
    channels = shared[0]["channels"]
    assert set(channels) == {"q0:vector", "q1:vector", "q2:text"}
    assert all("rank" in detail and "score" in detail for detail in channels.values())
    assert shared[0]["rrf_score"] == pytest.approx(1 / 61)


def test_assess_receives_the_union_ordered_with_the_original_question(monkeypatch, tmp_path):
    clients = Clients()
    result, _, _ = run(settings(tmp_path, multi_query=True), clients, monkeypatch)
    assess_calls = [call for call in clients.calls if call[0] == "assess"]
    assert assess_calls == [("assess", QUESTION, ["f1", "f2", "a2", "a3", "a1"])]
    # The rerank winner (second aspect) leads the assessed evidence and becomes
    # the only supported passage: results stay the support passages, as today.
    assert [c["chunk_id"] for c in result["results"]] == ["f1"]
    assert result["assessment"]["action"] == "answer"
    assert result["decision"]["reason"] == "uncalibrated"


def test_assess_internal_cap_of_60_still_applies_over_the_larger_union(monkeypatch, tmp_path):
    rows, chunks, versions = {}, {}, {}
    for index in range(30):
        for prefix, query in (("a", QUESTION), ("b", FACET_A), ("f", FACET_F)):
            cid = f"{prefix}{index}"
            rows.setdefault(query, ([], []))[0].append(row("vector", cid, index + 1, 0.9))
            chunks[cid] = SimpleNamespace(id=cid, version_id=f"v-{cid}", revision_id=f"rev-{cid}", number=1,
                                          content=f"contenido {cid}", search_content=f"contenido {cid}",
                                          provenance=[])
            versions[f"v-{cid}"] = SimpleNamespace(id=f"v-{cid}", document_id=f"doc-{prefix}", number=1,
                                                   metadata_json={"title": f"Título {cid}"})
    clients = Clients()
    pools = fake_pools(monkeypatch, rows)
    monkeypatch.setattr("bibliotecario.retrieval.expand_context", lambda db, candidates: list(candidates))
    result = asyncio.run(retrieve(FakeDB(chunks, versions),
                                  settings(tmp_path, multi_query=True), clients, QUESTION))
    assert len(pools) == 3 and result["retrieval"]["merged"] == 90
    assess_calls = [call for call in clients.calls if call[0] == "assess"]
    assert len(assess_calls[0][2]) == 60  # assess keeps its own cap
    assert len(clients.rerank_calls) == 1 and len(clients.rerank_calls[0][1]) == 90


def test_decompose_failure_degrades_to_today_path_and_records_the_error(monkeypatch, tmp_path):
    clients = Clients(fail=ProviderError("incomplete_generation"))
    degraded, pools, _ = run(settings(tmp_path, multi_query=True), clients, monkeypatch)
    assert degraded["retrieval"]["facet_error"] == "incomplete_generation"
    assert degraded["retrieval"]["facets"] == []
    assert clients.embed_calls == [([QUESTION], True)]
    assert [query for query, _ in pools] == [QUESTION]
    assert len(clients.rerank_calls) == 1 and clients.rerank_calls[0][0] == QUESTION
    baseline, _, _ = run(settings(tmp_path), Clients(), monkeypatch)
    assert [c["chunk_id"] for c in degraded["candidates"]] == [c["chunk_id"] for c in baseline["candidates"]]
    assert [c["rrf_score"] for c in degraded["candidates"]] == [c["rrf_score"] for c in baseline["candidates"]]
    assert [c["channels"] for c in degraded["candidates"]] == [c["channels"] for c in baseline["candidates"]]
    assert degraded["results"] == baseline["results"] and degraded["decision"] == baseline["decision"]


def test_a_crashing_decompose_still_degrades_instead_of_failing_the_turn(monkeypatch, tmp_path):
    async def broken(clients, question, diagnostics=None):
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr("bibliotecario.retrieval.decompose", broken)
    clients = Clients()
    result, pools, _ = run(settings(tmp_path, multi_query=True), clients, monkeypatch)
    assert result["retrieval"]["facet_error"] == "facets_crashed"
    assert result["retrieval"]["facets"] == []
    assert clients.embed_calls == [([QUESTION], True)]
    assert [query for query, _ in pools] == [QUESTION]
    assert len(clients.rerank_calls) == 1 and clients.rerank_calls[0][0] == QUESTION


def test_result_diagnostics_carry_no_passage_text_or_secrets(monkeypatch, tmp_path):
    result, _, _ = run(settings(tmp_path, multi_query=True), Clients(), monkeypatch)
    assert set(result["retrieval"]) == {"facets", "facet_error", "merged", "pools"}
    diagnostics = json.dumps(result["retrieval"], ensure_ascii=False)
    for passage in CONTENT.values():
        assert passage not in diagnostics
    assert result["retrieval"]["facets"] == [FACET_A, FACET_F]
    # The same holds for the stored run shape: no content or search_content keys leak.
    stored = json.dumps(result["retrieval"] | {"query": result["query"]}, ensure_ascii=False)
    assert "polinizan" not in stored and "colmenas" not in stored


def test_cost_report_with_simulated_provider_latency(monkeypatch, tmp_path):
    """Prints the per-phase cost table for the report and asserts the structure."""
    off_clients, on_clients = Clients(latency=0.02), Clients(latency=0.02)
    off, _, _ = run(settings(tmp_path), off_clients, monkeypatch)
    on, on_pools, _ = run(settings(tmp_path, multi_query=True), on_clients, monkeypatch)
    assert "decompose_ms" not in off["latency"]
    assert on["latency"]["decompose_ms"] >= 20
    assert len(on_clients.embed_calls) == 1 and len(on_clients.embed_calls[0][0]) == 3
    assert len(off_clients.embed_calls) == 1 and len(off_clients.embed_calls[0][0]) == 1
    assert len(on_clients.rerank_calls) == 1 and len(off_clients.rerank_calls) == 1
    assert len(on_pools) == 3
    print("\nCOST off:", json.dumps(off["latency"], sort_keys=True))
    print("COST on: ", json.dumps(on["latency"], sort_keys=True))
    print("CALLS on: ", [call[0] for call in on_clients.calls])
    print("CALLS off:", [call[0] for call in off_clients.calls])
