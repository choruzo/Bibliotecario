import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from test_h1 import application, login  # noqa: F401
from test_h2 import headers
from bibliotecario.chat import contextual_query
from bibliotecario.language import TRANSLATION_PROMPT, detect_language
from bibliotecario.models import RetrievalRun
from bibliotecario.providers import ProviderError
from bibliotecario.query import REWRITE_PROMPT
from bibliotecario.retrieval import corpus_signature


DETECTION_CASES = [
    # Spanish, including a title/acronym in English that must not flip the result.
    ("¿Cuánto vive una abeja reina?", "es"),
    ("¿Cómo configuro SSH en el switch Cisco?", "es"),
    ("¿Qué dice BERT sobre attention?", "es"),
    ("¿Cuándo empezó la Revolución francesa?", "es"),
    ("¿Dónde está el baño?", "es"),
    ("¿Cuántos parámetros tiene BERT-large?", "es"),
    # English.
    ("How long does a queen bee live?", "en"),
    ("What is the capital of Spain according to the Constitution?", "en"),
    ("Where is the bathroom?", "en"),
    # French.
    ("Combien de temps vit une abeille reine ?", "fr"),
    ("Quel est le prix du café en France ?", "fr"),
    ("Où sont les toilettes ?", "fr"),
    # German.
    ("Wie lange lebt eine Bienenkönigin?", "de"),
    ("Welche Schritte beschreibt die Anleitung?", "de"),
    ("Wo ist der Bahnhof?", "de"),
    # Italian.
    ("Quanto vive un'ape regina?", "it"),
    ("Come si configura la rete locale?", "it"),
    ("Dove si trova il museo?", "it"),
    # Portuguese.
    ("Quanto tempo vive uma abelha rainha?", "pt"),
    ("Como configuro a rede local?", "pt"),
    ("Onde fica a estação?", "pt"),
]


@pytest.mark.parametrize("text,expected", DETECTION_CASES)
def test_detection_of_short_questions(text, expected):
    assert detect_language(text) == expected


def test_detection_defaults_to_spanish_when_there_is_no_signal():
    assert detect_language("") == "es"
    assert detect_language("help") == "es"
    assert detect_language("??") == "es"


class Clients:
    def __init__(self, answer="", error=None, delay=0):
        self.settings = SimpleNamespace(sufficiency_reasoning_effort="low", translate_first_turn=True,
                                        translation_timeout_seconds=5)
        self.answer, self.error, self.delay, self.calls = answer, error, delay, []

    async def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.answer


def test_spanish_first_turn_is_not_translated():
    clients = Clients()
    diagnostics = {}
    question = "me puedes explicar los pasos para la instalacion del cisco"
    assert asyncio.run(contextual_query(clients, question, "", [], diagnostics=diagnostics)) \
        == "los pasos para la instalación del cisco"
    assert clients.calls == []
    assert diagnostics["language"] == "es" and diagnostics["translation"] == "skipped"


def test_follow_up_is_reformulated_but_never_translated():
    clients = Clients(answer="¿Qué rama de Git debo borrar?")
    diagnostics = {}
    question = "¿Y qué rama debo borrar?"
    recent = [{"role": "user", "content": "Git"}]
    assert asyncio.run(contextual_query(clients, question, "", recent, diagnostics=diagnostics)) \
        == "¿Qué rama de Git debo borrar?"
    assert len(clients.calls) == 1
    assert clients.calls[0][0][0]["content"] == REWRITE_PROMPT
    assert "translation" not in diagnostics and "translation_ms" not in diagnostics


def test_non_spanish_first_turn_is_translated_with_one_call():
    clients = Clients(answer="¿Cuánto vive una abeja reina?")
    diagnostics = {}
    assert asyncio.run(contextual_query(clients, "How long does a queen bee live?", "", [],
                                         diagnostics=diagnostics)) == "¿Cuánto vive una abeja reina?"
    assert len(clients.calls) == 1
    assert clients.calls[0][0][0]["content"] == TRANSLATION_PROMPT
    assert clients.calls[0][0][1]["content"] == "How long does a queen bee live?"
    assert diagnostics["language"] == "en"
    assert diagnostics["translation"] == "applied"
    assert diagnostics["translation_ms"] >= 0


def test_translation_can_be_disabled_by_settings():
    clients = Clients(error=AssertionError("translation must not be called"))
    clients.settings.translate_first_turn = False
    diagnostics = {}
    question = "How long does a queen bee live?"
    assert asyncio.run(contextual_query(clients, question, "", [], diagnostics=diagnostics)) == question
    assert clients.calls == []
    assert diagnostics["translation"] == "skipped"


def test_provider_failure_falls_back_to_the_original_with_a_diagnostic():
    clients = Clients(error=ProviderError("incomplete_generation"))
    diagnostics = {}
    question = "How long does a queen bee live?"
    assert asyncio.run(contextual_query(clients, question, "", [], diagnostics=diagnostics)) == question
    assert diagnostics["translation"] == "failed"
    assert "translation_failed" in diagnostics
    assert diagnostics["translation_error"] == "ProviderError"


def test_translation_timeout_falls_back_to_the_original():
    clients = Clients(answer="¿Tarde?", delay=0.2)
    clients.settings.translation_timeout_seconds = 0.01
    diagnostics = {}
    question = "How long does a queen bee live?"
    assert asyncio.run(contextual_query(clients, question, "", [], diagnostics=diagnostics)) == question
    assert diagnostics["translation"] == "failed"
    assert diagnostics["translation_failed"] == "translation_timeout"


def test_translated_query_reaches_retrieval_and_is_traced(application, monkeypatch):
    app, client, sessions = application
    login(client)
    translated = "¿Cuánto vive una abeja reina?"
    queries = []

    async def fake_post(base, path, body, key):
        return {"choices": [{"message": {"content": translated}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8}}

    async def fake_retrieve(db, settings, clients, query, **kwargs):
        queries.append(query)
        return {"query": query, "results": [], "candidates": [],
                "decision": {"action": "abstain", "reason": "no_evidence"},
                "latency": {}, "corpus_signature": corpus_signature(db)}

    monkeypatch.setattr(app.state.clients, "post", fake_post)
    monkeypatch.setattr("bibliotecario.chat.retrieve", fake_retrieve)
    cid = client.post("/chat/conversations", json={}, headers=headers(client)).json()["id"]
    response = client.post(f"/chat/conversations/{cid}/messages",
                           json={"content": "How long does a queen bee live?"}, headers=headers(client))
    assert response.status_code == 200, response.text
    message = [json.loads(line) for line in response.text.splitlines()][-1]["message"]

    # The retrieval query is the Spanish translation; the stored user message is not.
    assert queries == [translated]
    assert message["status"] == "abstained"
    with sessions() as db:
        run = db.get(RetrievalRun, message["retrieval_run_id"])
        assert run.query == translated
        assert run.result["translation"]["language"] == "en"
        assert run.result["translation"]["translation"] == "applied"
        assert run.result["latency"]["translation_ms"] >= 0
        assert run.result["llm"]["phases"]["translation"]["calls"] == 1
        stored = db.scalars(select(RetrievalRun).where(RetrievalRun.id == run.id)).one()
        assert stored.result["question"] == "How long does a queen bee live?"
