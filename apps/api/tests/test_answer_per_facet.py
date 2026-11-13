"""H8: answer per facet — dos sub-respuestas grounded y composición honesta.

Una pregunta de mode="explain" que el planificador parte en exactamente dos
facetas se responde con dos explicaciones independientes (retrieval, cobertura,
generación y verificación propias, citas renumeradas globalmente) y una
composición determinista que no afirma ninguna relación entre las partes.
"""
import asyncio
import json
from time import perf_counter

import httpx
import pytest
from sqlalchemy import select

from test_h1 import application, login, settings  # noqa: F401  (fixtures y constructor de Settings)
from test_h2 import headers
from test_h3 import reviewed, queue
from test_h4 import conversation
from bibliotecario.chat import (ABSTENTION, FACET_CLOSING, FACET_INTRO, FACET_MISSING,
                                FACET_SPLIT_HINT, compose_facets, plan_facets)
from bibliotecario.explain import validate_synthesis
from bibliotecario.indexing import finalize_index
from bibliotecario.models import (Chunk, Document, DocumentVersion, NormalizedRevision,
                                  RetrievalRun)
from bibliotecario.retrieval import corpus_signature
from bibliotecario.sufficiency import VERSION

QUESTION = "¿Cómo funciona el sistema y cómo se calibra?"
FACET_A = "funcionamiento del sistema"
FACET_B = "proceso de calibracion del sistema"

DOC_A = ("# Guia del sistema\n\nEl sistema tiene modulos independientes.\n\n"
         "## Arranque\n\nEl arranque admite modo seguro.\n").encode()
DOC_B = ("# Manual de calibracion\n\nLa calibracion usa el software integrado.\n\n"
         "## Registro\n\nEl mantenimiento exige registro firmado.\n").encode()

# Frases que la generación simulada deduce de cada pasaje (una por chunk).
SENTENCES = {"El sistema tiene modulos independientes.", "El arranque admite modo seguro.",
             "La calibracion usa el software integrado.", "El mantenimiento exige registro firmado."}


def enable_facets(app, monkeypatch):
    monkeypatch.setattr(app.state.settings, "answer_per_facet", True)


def mock_plan_parts(monkeypatch, facets=(), error=None, crash=False):
    calls = []

    async def plan_parts(clients, question, diagnostics=None):
        calls.append(question)
        if crash:
            raise RuntimeError("promesa rota de plan_parts")
        if error:
            diagnostics["error"] = error
            return []
        return list(facets)

    monkeypatch.setattr("bibliotecario.chat.plan_parts", plan_parts)
    return calls


def mock_facet_retrieval(monkeypatch, candidates_by_query, decisions=None, sleep=0.0):
    """One retrieval per facet query; records queries, sessions and overlap windows."""
    calls, windows, sessions_used = [], {}, []
    decisions = decisions or {}

    async def retrieve(db, settings, clients, query, **kwargs):
        calls.append(query)
        sessions_used.append(db)
        started = perf_counter()
        if sleep:
            await asyncio.sleep(sleep)
        windows[query] = (started, perf_counter())
        candidates = candidates_by_query.get(query, [])
        decision = decisions.get(query) or {"action": "answer", "reason": "calibrated_score"}
        return {"query": query, "results": list(candidates), "candidates": list(candidates),
                "decision": decision,
                "assessment": {"action": decision["action"], "version": VERSION,
                               "reason": "evidence_assessed" if decision["action"] == "answer" else "partial_evidence",
                               "coverage_complete": decision["action"] == "answer", "contradiction": False,
                               "support": [{"chunk_id": c["chunk_id"]} for c in candidates
                                           if decision["action"] == "answer"]},
                "stages": {"pools": [len(candidates)], "merged": len(candidates),
                           "post_rerank": len(candidates), "assessed": len(candidates),
                           "support": len(candidates) if decision["action"] == "answer" else 0,
                           "visible": len(candidates), "dropped_invisible": 0, "dropped_sample": []},
                "latency": {"embedding_ms": 1.0, "search_ms": 2.0, "fusion_ms": 0.5,
                            "reranking_ms": 3.0, "sufficiency_ms": 4.0},
                "scope": {"admin": kwargs["admin"], "document_id": None},
                "corpus_signature": corpus_signature(db)}

    monkeypatch.setattr("bibliotecario.chat.retrieve", retrieve)
    return calls, windows, sessions_used


def mock_facet_generation(monkeypatch, app, rejected=(), mutate=None):
    """Two explain generations (one per facet) plus the per-sentence audits."""
    prompts, audited = [], []

    async def stream(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        prompts.append((payload, kwargs.get("response_schema")))
        if mutate and len(prompts) == 1:
            mutate()
        sentences = []
        for source in payload["sources"]:
            text = " ".join(line.strip() for line in source["quote"].strip().splitlines()
                            if line.strip() and not line.lstrip().startswith("#"))
            if text in SENTENCES:
                sentences.append({"text": text, "citations": [source["citation_id"]]})
        yield json.dumps({"sections": [{"heading": "Parte", "sentences": sentences}]}, ensure_ascii=False)

    async def generate(messages, **kwargs):
        claim = json.loads(messages[1]["content"])["claims"][0]
        audited.append(claim)
        return json.dumps({"supported": claim["claim"] not in rejected})

    monkeypatch.setattr(app.state.clients, "stream_generate", stream)
    monkeypatch.setattr(app.state.clients, "generate", generate)
    return prompts, audited


def publish(application, content):
    app, client, sessions = application
    did, version = reviewed(application, content)
    lease, result, _ = queue(application, version)
    assert finalize_index(sessions, app.state.settings, lease, result)
    with sessions() as db:
        chunks = db.scalars(select(Chunk).where(Chunk.version_id == version["id"]).order_by(Chunk.number)).all()
        return did, [{"chunk_id": c.id, "document_id": did, "version_id": version["id"],
                      "revision_id": c.revision_id, "title": "Titulo", "content": c.content,
                      "provenance": list(c.provenance)} for c in chunks]


def explain_turn(client, cid, content=QUESTION, mode="explain"):
    response = client.post(f"/chat/conversations/{cid}/messages", json={"content": content, "mode": mode},
                           headers=headers(client))
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines()]


def stored_result(sessions, message):
    with sessions() as db:
        return db.get(RetrievalRun, message["retrieval_run_id"]).result


def add_document(sessions, title="Documento añadido"):
    """Corpus change that does not touch the turn's own sources."""
    with sessions() as db:
        doc = Document(title=title, created_at=0)
        db.add(doc)
        db.flush()
        version = DocumentVersion(document_id=doc.id, number=1, status="publicado", created_at=0,
                                  original_sha256="0" * 64,
                                  metadata_json={"title": title, "visibility": "usuarios"})
        db.add(version)
        db.flush()
        revision = NormalizedRevision(version_id=version.id, number=1, metadata_json={},
                                      storage_key=f"rev-{doc.id}", sha256="1" * 64, created_at=0)
        db.add(revision)
        db.flush()
        version.current_revision_id = revision.id
        doc.active_version_id = version.id
        db.add(Chunk(version_id=version.id, revision_id=revision.id, number=1,
                     content="Texto adicional del corpus.", search_content="Texto adicional del corpus.",
                     provenance=[], embedding=[0.1] * 768, model_signature="test"))
        db.commit()


def test_plan_facets_only_fires_with_exactly_two():
    class Clients:
        def __init__(self, raw):
            self.raw = raw

        async def generate(self, messages, **kwargs):
            return self.raw

    timing = {}
    assert asyncio.run(plan_facets(Clients('{"facets": []}'), QUESTION, timing)) == ("not_two", [])
    assert asyncio.run(plan_facets(Clients('{"facets": ["una sola consulta"]}'), QUESTION, timing)) == ("not_two", [])
    assert asyncio.run(plan_facets(Clients('{"facets": ["una consulta", "otra distinta"]}'),
                                   QUESTION, timing)) == ("two", ["una consulta", "otra distinta"])
    assert "plan_ms" in timing and timing["plan_ms"] >= 0


def test_plan_facets_reports_failure_and_never_raises():
    class Timeout:
        async def generate(self, messages, **kwargs):
            raise httpx.TimeoutException("lento")

    class Broken:
        async def generate(self, messages, **kwargs):
            raise RuntimeError("bug inesperado")

    plan, facets = asyncio.run(plan_facets(Timeout(), QUESTION, {}))
    assert plan == "plan_failed" and facets == []
    assert asyncio.run(plan_facets(Broken(), QUESTION, {})) == ("plan_failed", [])


def test_compose_facets_contract():
    both = compose_facets(["Bloque A", "Bloque B"], [])
    assert both == f"{FACET_INTRO}\n\nBloque A\n\n---\n\nBloque B\n\n{FACET_CLOSING}"
    assert both.count(FACET_CLOSING) == 1
    one = compose_facets(["Bloque A"], ["consulta sin evidencia"])
    assert one == (f"{FACET_INTRO}\n\nBloque A\n\n---\n\n"
                   f"No encuentro evidencia documental suficiente para la segunda parte: consulta sin evidencia."
                   f"\n\n{FACET_CLOSING}")
    none = compose_facets([], [])
    assert none == ABSTENTION + FACET_SPLIT_HINT
    assert FACET_CLOSING not in none


def test_flag_off_never_plans_and_keeps_the_explain_path_intact(application, monkeypatch):
    app, client, sessions = application
    login(client)
    plan_calls = mock_plan_parts(monkeypatch, crash=True)  # must never run
    _, candidates = publish(application, DOC_A)
    mock_facet_retrieval(monkeypatch, {QUESTION: candidates})
    mock_facet_generation(monkeypatch, app)
    message = explain_turn(client, conversation(client))[-1]["message"]
    assert plan_calls == []
    assert message["status"] == "completed"
    with sessions() as db:
        outcome = db.get(RetrievalRun, message["retrieval_run_id"]).result["chat_outcome"]
    # Byte-identical with the H6 explain contract: no facet keys at all.
    assert outcome == {"status": "completed", "reason": "grounded", "mode": "explain", "figure_hint": None}


def test_answer_mode_never_plans_and_stays_byte_identical(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    plan_calls = mock_plan_parts(monkeypatch, crash=True)
    _, candidates = publish(application, DOC_A)
    mock_facet_retrieval(monkeypatch, {QUESTION: candidates})

    async def stream(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        yield json.dumps({"evidence": [{"citation_id": s["citation_id"],
                                        "explanation": s["quote"].strip() + ", y así se explica."}
                                       for s in payload["sources"]]}, ensure_ascii=False)

    async def generate(messages, **kwargs):
        return json.dumps({"supported": True})

    monkeypatch.setattr(app.state.clients, "stream_generate", stream)
    monkeypatch.setattr(app.state.clients, "generate", generate)
    message = explain_turn(client, conversation(client), mode="answer")[-1]["message"]
    assert plan_calls == []
    assert message["status"] == "completed"
    assert message["content"].startswith("# Guia del sistema")  # quote restated with its heading
    assert ", y así se explica. [C1]" in message["content"]
    # Byte-identical answer contract: no mode key, no facet keys.
    assert stored_result(sessions, message)["chat_outcome"] == {"status": "completed", "reason": "grounded"}


def test_single_topic_question_keeps_the_normal_explain_path(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    plan_calls = mock_plan_parts(monkeypatch, [])
    _, candidates = publish(application, DOC_A)
    retrieval_calls, _, _ = mock_facet_retrieval(monkeypatch, {QUESTION: candidates})
    mock_facet_generation(monkeypatch, app)
    message = explain_turn(client, conversation(client))[-1]["message"]
    assert plan_calls == [QUESTION] and retrieval_calls == [QUESTION]
    assert message["status"] == "completed"
    assert FACET_INTRO not in message["content"] and message["content"].startswith("**Parte**")
    outcome = stored_result(sessions, message)["chat_outcome"]
    assert outcome["facet_plan"] == "not_two"
    assert "facet_concurrency" not in outcome and "parts" not in outcome
    assert "figure_hint" in outcome  # the normal explain contract still applies


def test_one_facet_keeps_the_normal_path_with_the_original_query(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    mock_plan_parts(monkeypatch, [FACET_A])
    _, candidates = publish(application, DOC_A)
    retrieval_calls, _, _ = mock_facet_retrieval(monkeypatch, {QUESTION: candidates})
    mock_facet_generation(monkeypatch, app)
    message = explain_turn(client, conversation(client))[-1]["message"]
    assert retrieval_calls == [QUESTION]  # the facet query is NOT searched
    assert stored_result(sessions, message)["chat_outcome"]["facet_plan"] == "not_two"


@pytest.mark.parametrize("kwargs", [{"error": "provider_timeout"}, {"error": "invalid_facets"}, {"crash": True}])
def test_plan_failure_degrades_to_the_normal_explain_path(application, monkeypatch, kwargs):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    mock_plan_parts(monkeypatch, **kwargs)
    _, candidates = publish(application, DOC_A)
    retrieval_calls, _, _ = mock_facet_retrieval(monkeypatch, {QUESTION: candidates})
    mock_facet_generation(monkeypatch, app)
    message = explain_turn(client, conversation(client))[-1]["message"]
    assert retrieval_calls == [QUESTION]
    assert message["status"] == "completed"
    assert stored_result(sessions, message)["chat_outcome"]["facet_plan"] == "plan_failed"


def test_two_facets_retrieve_concurrently_with_own_sessions(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    _, candidates_a = publish(application, DOC_A)
    _, candidates_b = publish(application, DOC_B)
    mock_plan_parts(monkeypatch, [FACET_A, FACET_B])
    calls, windows, sessions_used = mock_facet_retrieval(
        monkeypatch, {FACET_A: candidates_a, FACET_B: candidates_b}, sleep=0.05)
    mock_facet_generation(monkeypatch, app)
    message = explain_turn(client, conversation(client))[-1]["message"]
    assert sorted(calls) == [FACET_A, FACET_B]  # two retrievals, one per facet query
    assert sessions_used[0] is not sessions_used[1]  # own session each
    # Overlapped: the second retrieval starts before the first one finishes.
    assert windows[FACET_B][0] < windows[FACET_A][1] and windows[FACET_A][0] < windows[FACET_B][1]
    assert message["status"] == "completed"
    result = stored_result(sessions, message)
    assert result["chat_outcome"]["facet_concurrency"] == "concurrent"


def test_both_facets_answer_compose_with_global_citations(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    doc_a, candidates_a = publish(application, DOC_A)
    doc_b, candidates_b = publish(application, DOC_B)
    mock_plan_parts(monkeypatch, [FACET_A, FACET_B])
    mock_facet_retrieval(monkeypatch, {FACET_A: candidates_a, FACET_B: candidates_b})
    prompts, audited = mock_facet_generation(monkeypatch, app)
    message = explain_turn(client, conversation(client))[-1]["message"]
    assert message["status"] == "completed"
    block_a = "**Parte**\n\nEl sistema tiene modulos independientes. [C1] El arranque admite modo seguro. [C2]"
    block_b = "**Parte**\n\nLa calibracion usa el software integrado. [C3] El mantenimiento exige registro firmado. [C4]"
    expected = f"{FACET_INTRO}\n\n{block_a}\n\n---\n\n{block_b}\n\n{FACET_CLOSING}"
    assert message["content"] == expected  # intro + A + separador + B + cierre literal
    assert message["content"].count(FACET_CLOSING) == 1
    assert [s["citation_id"] for s in message["sources"]] == ["C1", "C2", "C3", "C4"]
    assert all(source["document_id"] == doc_a for source in message["sources"][:2])
    assert all(source["document_id"] == doc_b for source in message["sources"][2:])
    # The generation schema of each facet only admits its own markers.
    assert [schema["properties"]["sections"]["items"]["properties"]["sentences"]["items"]
            ["properties"]["citations"]["items"]["enum"] for _, schema in prompts] == [["C1", "C2"], ["C3", "C4"]]
    assert [payload["query"] for payload, _ in prompts] == [FACET_A, FACET_B]
    assert len(audited) == 4  # one audit per sentence, across both facets


def test_message_sources_are_unique_global_and_painted_by_the_web(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    doc_a, candidates_a = publish(application, DOC_A)
    doc_b, candidates_b = publish(application, DOC_B)
    mock_plan_parts(monkeypatch, [FACET_A, FACET_B])
    mock_facet_retrieval(monkeypatch, {FACET_A: candidates_a, FACET_B: candidates_b})
    mock_facet_generation(monkeypatch, app)
    message = explain_turn(client, conversation(client))[-1]["message"]
    ids = [source["citation_id"] for source in message["sources"]]
    assert len(ids) == len(set(ids))  # no repeated citation ids
    import re
    markers = sorted(set(re.findall(r"\[C(\d+)\]", message["content"])), key=int)
    assert markers == sorted(id[1:] for id in ids)  # every chip matches one source, and vice versa
    assert {source["document_id"] for source in message["sources"]} == {doc_a, doc_b}


def test_one_facet_abstains_publishes_partial_facets(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    _, candidates_a = publish(application, DOC_A)
    _, candidates_b = publish(application, DOC_B)
    mock_plan_parts(monkeypatch, [FACET_A, FACET_B])
    mock_facet_retrieval(monkeypatch, {FACET_A: candidates_a, FACET_B: candidates_b},
                         decisions={FACET_B: {"action": "abstain", "reason": "partial_evidence"}})
    prompts, _ = mock_facet_generation(monkeypatch, app)
    message = explain_turn(client, conversation(client))[-1]["message"]
    assert message["status"] == "completed"
    assert message["content"] == (f"{FACET_INTRO}\n\n"
                                  "**Parte**\n\nEl sistema tiene modulos independientes. [C1] "
                                  "El arranque admite modo seguro. [C2]\n\n---\n\n"
                                  f"No encuentro evidencia documental suficiente para la segunda parte: {FACET_B}."
                                  f"\n\n{FACET_CLOSING}")
    assert [s["citation_id"] for s in message["sources"]] == ["C1", "C2"]  # nothing from the abstaining facet
    result = stored_result(sessions, message)
    outcome = result["chat_outcome"]
    assert outcome["reason"] == "partial_facets" and outcome["status"] == "completed"
    assert [part["status"] for part in outcome["parts"]] == ["completed", "abstained"]
    assert outcome["parts"][1]["reason"] == "partial_evidence" and outcome["parts"][1]["citations"] == 0
    assert result["decision"] == {"action": "answer", "reason": "partial_facets"}
    assert [payload["query"] for payload, _ in prompts] == [FACET_A]  # no generation for the abstaining facet


def test_both_facets_abstain_publishes_facets_uncovered(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    _, candidates_a = publish(application, DOC_A)
    _, candidates_b = publish(application, DOC_B)
    mock_plan_parts(monkeypatch, [FACET_A, FACET_B])
    mock_facet_retrieval(monkeypatch, {FACET_A: candidates_a, FACET_B: candidates_b},
                         decisions={FACET_A: {"action": "abstain", "reason": "partial_evidence"},
                                    FACET_B: {"action": "abstain", "reason": "uncalibrated"}})
    prompts, _ = mock_facet_generation(monkeypatch, app)
    message = explain_turn(client, conversation(client))[-1]["message"]
    assert prompts == []  # no generation at all
    assert message["status"] == "abstained"
    assert message["content"] == ABSTENTION + FACET_SPLIT_HINT
    assert message["sources"] == []
    result = stored_result(sessions, message)
    outcome = result["chat_outcome"]
    assert outcome["status"] == "abstained" and outcome["reason"] == "facets_uncovered"
    assert [part["status"] for part in outcome["parts"]] == ["abstained", "abstained"]
    assert [part["reason"] for part in outcome["parts"]] == ["partial_evidence", "uncalibrated"]
    assert result["decision"] == {"action": "abstain", "reason": "facets_uncovered"}


def test_verifier_rejection_topples_only_that_facet_to_the_extract(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    _, candidates_a = publish(application, DOC_A)
    _, candidates_b = publish(application, DOC_B)
    mock_plan_parts(monkeypatch, [FACET_A, FACET_B])
    mock_facet_retrieval(monkeypatch, {FACET_A: candidates_a, FACET_B: candidates_b})
    _, audited = mock_facet_generation(
        monkeypatch, app, rejected={"El sistema tiene modulos independientes.",
                                    "El arranque admite modo seguro."})
    message = explain_turn(client, conversation(client))[-1]["message"]
    assert message["status"] == "completed"
    content = message["content"]
    assert content.startswith(FACET_INTRO + "\n\nExtractos literales de la documentación recuperada:")
    assert "La calibracion usa el software integrado. [C3]" in content  # facet B keeps its prose
    assert "**Parte**\n\nEl sistema tiene" not in content  # facet A never publishes rejected prose
    assert content.count(FACET_CLOSING) == 1
    result = stored_result(sessions, message)
    outcome = result["chat_outcome"]
    assert [part["reason"] for part in outcome["parts"]] == ["grounded_extract", "grounded"]
    assert outcome["fallbacks"] == [{"part": 0, "reason": "grounding_rejected",
                                     "detail": {"supported": False, "claims": 2, "rejected": [1, 2]}}]
    assert [s["citation_id"] for s in message["sources"]] == ["C1", "C2", "C3", "C4"]


def test_corpus_change_abstains_and_publishes_no_sources(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    _, candidates_a = publish(application, DOC_A)
    _, candidates_b = publish(application, DOC_B)
    mock_plan_parts(monkeypatch, [FACET_A, FACET_B])
    mock_facet_retrieval(monkeypatch, {FACET_A: candidates_a, FACET_B: candidates_b})
    mock_facet_generation(monkeypatch, app, mutate=lambda: add_document(sessions))
    message = explain_turn(client, conversation(client))[-1]["message"]
    assert message["status"] == "abstained"
    assert message["content"] == ABSTENTION  # the generic abstention stays untouched
    assert message["sources"] == []
    result = stored_result(sessions, message)
    assert result["chat_outcome"]["reason"] == "corpus_changed"


def test_preferences_and_original_question_reach_every_facet(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    _, candidates_a = publish(application, DOC_A)
    _, candidates_b = publish(application, DOC_B)
    mock_plan_parts(monkeypatch, [FACET_A, FACET_B])
    mock_facet_retrieval(monkeypatch, {FACET_A: candidates_a, FACET_B: candidates_b})
    prompts, _ = mock_facet_generation(monkeypatch, app)
    cid = conversation(client)
    assert client.patch(f"/chat/conversations/{cid}", json={"preferences": "Con ejemplos"},
                        headers=headers(client)).status_code == 200
    explain_turn(client, cid)
    assert len(prompts) == 2
    for (payload, _), facet_query in zip(prompts, [FACET_A, FACET_B]):
        assert payload["preferences"] == "Con ejemplos"
        assert payload["question"] == QUESTION  # the user's original wording, per facet
        assert payload["query"] == facet_query  # each facet searched with its own query


def test_trace_records_two_parts_with_facet_latencies(application, monkeypatch):
    app, client, sessions = application
    login(client)
    enable_facets(app, monkeypatch)
    _, candidates_a = publish(application, DOC_A)
    _, candidates_b = publish(application, DOC_B)
    plan_calls = mock_plan_parts(monkeypatch, [FACET_A, FACET_B])
    retrieval_calls, _, _ = mock_facet_retrieval(monkeypatch, {FACET_A: candidates_a, FACET_B: candidates_b})
    prompts, audited = mock_facet_generation(monkeypatch, app)
    message = explain_turn(client, conversation(client))[-1]["message"]
    result = stored_result(sessions, message)
    assert [part["query"] for part in result["parts"]] == [FACET_A, FACET_B]
    for part in result["parts"]:
        assert set(part) == {"query", "stages", "decision", "assessment", "candidates",
                             "results", "corpus_signature", "latency"}
        assert part["stages"]["assessed"] == len(part["candidates"]) == 2
        assert part["decision"]["action"] == "answer"
    assert result["decision"] == {"action": "answer", "reason": "facets_composed"}
    outcome = result["chat_outcome"]
    assert [part["citations"] for part in outcome["parts"]] == [2, 2]
    assert [part["documents"] for part in outcome["parts"]] == [1, 1]
    latency = result["chat_latency"]
    assert {"plan_ms", "facets_retrieval_ms", "facet0_generation_ms", "facet0_verification_ms",
            "facet1_generation_ms", "facet1_verification_ms", "rewrite_ms", "total_ms"} <= set(latency)
    assert "generation_ms" not in latency  # the facet route measures per facet
    # Model calls of the turn, counted by the doubles: one plan call, two
    # retrievals (one per facet), two generations and one audit per sentence
    # (two per facet). A real retrieval adds embed + rerank + intent +
    # assessment per facet; the doubles here replace the whole retrieval.
    assert len(plan_calls) == 1 and len(retrieval_calls) == 2
    assert len(prompts) == 2 and len(audited) == 4


def test_report_prints_the_three_compositions():
    """Evidence for report.md: the three composition paths with real explain markdown."""
    sources = [
        {"citation_id": "C1", "quote": "El sistema tiene modulos independientes.", "title": "Guia",
         "document_id": "d1", "locator": {"section_path": ["Guia"]}},
        {"citation_id": "C2", "quote": "La calibracion usa el software integrado.", "title": "Manual",
         "document_id": "d2", "locator": {"section_path": ["Manual"]}}]
    raw_a = json.dumps({"sections": [{"heading": "Sistema", "sentences": [
        {"text": "El sistema tiene modulos independientes.", "citations": ["C1"]}]}]}, ensure_ascii=False)
    raw_b = json.dumps({"sections": [{"heading": "Calibracion", "sentences": [
        {"text": "La calibracion usa el software integrado.", "citations": ["C2"]}]}]}, ensure_ascii=False)
    block_a, _, _ = validate_synthesis(raw_a, sources)
    block_b, _, _ = validate_synthesis(raw_b, sources)
    both = compose_facets([block_a, block_b], [])
    one = compose_facets([block_a], ["proceso de la fotosintesis"])
    none = compose_facets([], [])
    print("\n### ambos responden\n" + both)
    print("\n### una responde\n" + one)
    print("\n### ninguna responde\n" + none)
    assert both.count(FACET_CLOSING) == 1 and one.count(FACET_CLOSING) == 1
    assert FACET_CLOSING not in none and none == ABSTENTION + FACET_SPLIT_HINT
    assert FACET_MISSING.format(query="proceso de la fotosintesis") in one
