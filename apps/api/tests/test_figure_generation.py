"""Generación de una figura en el modo explicar: una, validada, nunca decisiva.

La figura viaja en la misma generación que la síntesis (cero llamadas extra al
modelo). Se valida solo cuando el texto se ha mantenido y nunca cambia el
destino del turno: una figura inválida se descarta con su motivo en
chat_outcome.figure_rejected y la respuesta sigue completed con el texto.

Decisión de contrato fijada aquí (ver docs/h6/figures-contract.md): el sobre de
la síntesis admite `figure` solo como objeto; `figure: []`, una lista con dos
figuras o una segunda figura bajo otra clave raíz violan el esquema completo y
caen a extracto como `invalid_synthesis`, no como motivo de figura. Los fallos
de contenido de una figura-objeto (cita desconocida, campo extra, cifra fuera
de sus citas, límites) sí son `figure_rejected` y no tocan el texto.
"""
import json

import pytest

from test_explain import (SOURCES, explain_turn, mock_retrieval, mock_synthesis, publish,
                          section, sentence, stored_outcome)
from test_h1 import application, login  # noqa: F401
from test_h4 import conversation
from bibliotecario.explain import synthesis_schema, validate_synthesis
from bibliotecario.models import Message

FIGURE = {"kind": "bars", "title": "Composición del sistema",
          "source_citations": ["C1"],
          "bars": {"unit": "módulos", "series": [{"label": "Sistema", "value": 3, "citations": ["C1"]}]}}

CLEAN_FIGURE = {"kind": "bars", "title": "Composición del sistema",
                "source_citations": ["C1"],
                "bars": {"unit": "módulos", "series": [{"label": "Sistema", "value": 3.0, "citations": ["C1"]}]}}

SYNTHESIS = {"sections": [section("Composición del sistema", [
    sentence("El sistema tiene 3 módulos.", ["C1"]),
    sentence("Requiere además 4 sensores.", ["C2"])])]}


def with_figure(figure):
    return SYNTHESIS | {"figure": figure}


def explain(application, monkeypatch, payload, rejected=()):
    """One explain turn against the indexed DOC, with the generation mocked."""
    app, client, sessions = application
    login(client)
    mock_retrieval(monkeypatch, publish(application), answer=True)
    mock_synthesis(monkeypatch, app, payload, rejected=rejected)
    message = explain_turn(client, conversation(client), "explain")[-1]["message"]
    return message, stored_outcome(sessions, message)


def test_synthesis_schema_admits_one_optional_figure_object():
    schema = synthesis_schema([{"citation_id": "C1"}, {"citation_id": "C2"}])
    assert schema["required"] == ["sections"] and schema["additionalProperties"] is False
    figure = schema["properties"]["figure"]
    assert figure["type"] == "object" and figure["additionalProperties"] is False
    assert figure["required"] == ["kind", "title", "source_citations"]
    assert figure["properties"]["kind"]["enum"] == ["table", "timeline", "bars", "steps"]
    assert figure["properties"]["source_citations"]["items"]["enum"] == ["C1", "C2"]
    for kind in ("table", "timeline", "bars", "steps"):
        assert figure["properties"][kind]["additionalProperties"] is False
    assert figure["properties"]["bars"]["required"] == ["unit", "series"]
    assert figure["properties"]["steps"]["required"] == ["items"]


def test_validate_synthesis_requires_the_figure_to_be_an_object():
    content, used, _ = validate_synthesis(json.dumps(with_figure(FIGURE), ensure_ascii=False), SOURCES)
    assert content.startswith("**Composición del sistema**") and len(used) == 2
    # Two figures or none as a list violate the whole synthesis envelope.
    for bad in ([FIGURE, FIGURE], []):
        with pytest.raises(ValueError) as error:
            validate_synthesis(json.dumps(SYNTHESIS | {"figure": bad}), SOURCES)
        assert error.value.args[0] == "invalid_synthesis"
    # A second figure cannot ride under another root key either.
    with pytest.raises(ValueError) as error:
        validate_synthesis(json.dumps(SYNTHESIS | {"figures": [FIGURE]}), SOURCES)
    assert error.value.args[0] == "invalid_synthesis"


def test_valid_figure_is_published_saved_and_returned_in_done(application, monkeypatch):
    app, client, sessions = application
    login(client)
    cid = conversation(client)
    mock_retrieval(monkeypatch, publish(application), answer=True)
    mock_synthesis(monkeypatch, app, with_figure(FIGURE))
    events = explain_turn(client, cid, "explain")
    message = events[-1]["message"]
    assert message["status"] == "completed"
    assert message["content"].startswith("**Composición del sistema**")  # the text is untouched
    print("FIGURA_ACEPTADA=" + json.dumps(message["figures"][0], ensure_ascii=False))
    assert message["figures"] == [CLEAN_FIGURE]  # the done event carries the figure
    outcome = stored_outcome(sessions, message)
    assert outcome["mode"] == "explain" and outcome["figure"] == {"present": True, "kind": "bars"}
    assert "figure_rejected" not in outcome
    with sessions() as db:
        assert db.get(Message, message["id"]).figures == [CLEAN_FIGURE]
    detail = client.get(f"/chat/conversations/{cid}").json()["messages"][-1]
    assert detail["figures"] == [CLEAN_FIGURE]  # message_json round-trips it


def test_steps_figure_supports_a_procedure(application, monkeypatch):
    steps = {"kind": "steps", "title": "Revisión del sistema", "source_citations": ["C1"],
             "steps": {"items": [{"label": "Inspeccionar los 3 módulos", "detail": "Uno por uno",
                                  "citations": ["C1"]}]}}
    message, outcome = explain(application, monkeypatch, with_figure(steps))
    assert message["figures"] == [{"kind": "steps", "title": "Revisión del sistema",
                                   "source_citations": ["C1"],
                                   "steps": {"items": [{"label": "Inspeccionar los 3 módulos",
                                                        "detail": "Uno por uno", "citations": ["C1"]}]}}]
    assert outcome["figure"] == {"present": True, "kind": "steps"}
    assert "figure_rejected" not in outcome


def test_figure_number_outside_its_citations_is_dropped(application, monkeypatch):
    invented = {"kind": "bars", "title": "Componentes del despliegue", "source_citations": ["C1"],
                "bars": {"unit": "componentes",
                         "series": [{"label": "Despliegue completo", "value": 7, "citations": ["C1"]}]}}
    message, outcome = explain(application, monkeypatch, with_figure(invented))
    assert message["status"] == "completed"  # the figure never topples the turn
    assert message["content"].startswith("**Composición del sistema**")  # the text is intact
    assert message["figures"] == []
    print("DESCARTE=" + json.dumps(outcome, ensure_ascii=False))
    assert outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "unsupported_number"


def test_numbers_are_judged_against_the_datums_citations_not_the_turn(application, monkeypatch):
    # 4 exists in the turn (C2: "Requiere 4 sensores.") but this datum cites only C1.
    mixed = {"kind": "bars", "title": "Comparativa de piezas", "source_citations": ["C1"],
             "bars": {"unit": "piezas",
                      "series": [{"label": "Modulos del sistema", "value": 3, "citations": ["C1"]},
                                 {"label": "Sensores requeridos", "value": 4, "citations": ["C1"]}]}}
    message, outcome = explain(application, monkeypatch, with_figure(mixed))
    assert message["figures"] == []
    assert outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "unsupported_number"


def test_figure_with_unknown_citation_is_dropped(application, monkeypatch):
    unknown = {"kind": "timeline", "title": "Cronología del sistema", "source_citations": ["C1"],
               "timeline": {"events": [{"when": "El día 3", "label": "Módulos listos", "citations": ["C9"]}]}}
    message, outcome = explain(application, monkeypatch, with_figure(unknown))
    assert message["status"] == "completed"
    assert message["content"].startswith("**Composición del sistema**")
    assert message["figures"] == []
    assert outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "citation_unknown"


def test_figure_with_extra_field_is_dropped(application, monkeypatch):
    message, outcome = explain(application, monkeypatch, with_figure(FIGURE | {"html": "<b>3</b>"}))
    assert message["status"] == "completed"
    assert message["content"].startswith("**Composición del sistema**")
    assert message["figures"] == []
    assert outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "extra_field"


def test_figure_over_the_row_limit_is_dropped_not_truncated(application, monkeypatch):
    big = {"kind": "table", "title": "Piezas del sistema", "source_citations": ["C1"],
           "table": {"columns": ["Elemento", "Piezas"], "rows": [["Sistema", "3 módulos"]] * 13}}
    message, outcome = explain(application, monkeypatch, with_figure(big))
    assert message["status"] == "completed"
    assert outcome["figure_rejected"] == "too_large"
    assert outcome["figure"] == {"present": False, "kind": None}
    assert message["figures"] == []  # dropped whole: nothing is truncated or repaired


def test_answer_mode_keeps_rejecting_the_figure_key(application, monkeypatch):
    app, client, sessions = application
    login(client)
    mock_retrieval(monkeypatch, publish(application), answer=True)
    schemas = []

    async def stream(messages, **kwargs):
        schemas.append(kwargs.get("response_schema"))
        yield json.dumps({"evidence": [
            {"citation_id": "C1", "explanation": "El sistema tiene 3 módulos."},
            {"citation_id": "C2", "explanation": "Requiere 4 sensores."}],
            "figure": FIGURE}, ensure_ascii=False)

    async def generate(messages, **kwargs):
        return json.dumps({"supported": True})

    monkeypatch.setattr(app.state.clients, "stream_generate", stream)
    monkeypatch.setattr(app.state.clients, "generate", generate)
    message = explain_turn(client, conversation(client), "answer")[-1]["message"]
    assert set(schemas[0]["properties"]) == {"evidence"}  # the answer schema stays closed
    assert message["status"] == "abstained"  # invalid_answer abstains, as any extra field
    assert message["content"].startswith("No encuentro evidencia")
    assert message["figures"] == []
    outcome = stored_outcome(sessions, message)
    assert outcome == {"status": "abstained", "reason": "invalid_answer"}
    assert "figure" not in outcome and "figure_rejected" not in outcome and "mode" not in outcome


def test_extract_fallback_drops_a_valid_figure(application, monkeypatch):
    payload = {"sections": [section("Composición", [
        sentence("El despliegue necesita 7 componentes.", ["C1", "C2"])])],
        "figure": FIGURE}
    message, outcome = explain(application, monkeypatch, payload)
    assert message["content"].startswith("Extractos literales")
    assert outcome["fallback"]["reason"] == "unsupported_number"
    assert outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "text_fallback"  # the extract supports no figure
    assert message["figures"] == []


def test_figure_validation_runs_after_the_text_has_held(application, monkeypatch):
    bad_figure = FIGURE | {"html": "<b>3</b>"}  # its own reason would be extra_field
    payload = {"sections": [section("Composición", [
        sentence("El despliegue necesita 7 componentes.", ["C1", "C2"])])],
        "figure": bad_figure}
    message, outcome = explain(application, monkeypatch, payload)
    assert message["content"].startswith("Extractos literales")
    assert outcome["fallback"]["reason"] == "unsupported_number"  # the text is judged first
    assert outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "text_fallback"  # not the figure's extra_field
    assert message["figures"] == []


def test_figure_list_is_an_invalid_synthesis_not_a_figure_reason(application, monkeypatch):
    message, outcome = explain(application, monkeypatch, SYNTHESIS | {"figure": [FIGURE, FIGURE]})
    assert message["content"].startswith("Extractos literales")
    assert outcome["fallback"]["reason"] == "invalid_synthesis"  # schema violation of the envelope
    assert outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "text_fallback"
    assert message["figures"] == []


def test_turn_without_figure_keeps_the_previous_outcome_shape(application, monkeypatch):
    message, outcome = explain(application, monkeypatch, SYNTHESIS)
    assert message["status"] == "completed" and message["figures"] == []
    # The figure slot is documented only when the model produced a figure.
    assert outcome == {"status": "completed", "reason": "grounded", "mode": "explain"}
    assert "figure" not in outcome and "figure_rejected" not in outcome
