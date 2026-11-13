"""Emisión de figuras en modo explicar: pista determinista + segunda llamada.

La síntesis ya no pide figura dentro de su generación: medido, competía con el
contrato de frases (citas por frase, cifras por frase, auditoría por frase) y
el modelo dejaba de emitir la clave. `figure_hint` decide con reglas fijas y
conservadoras si los pasajes del turno tienen datos graficables; solo entonces
una segunda llamada corta devuelve UNA figura o un decline explícito.
`validate_figure` sigue siendo la única puerta y una figura nunca cambia el
destino del turno.

Los umbrales de la pista son contrato (docs/h6/figures-contract.md): están
fijados aquí y no se ajustan para que un caso pase.
"""
import json

import pytest

from test_explain import (SOURCES, SYNTHESIS, explain_turn, mock_retrieval, passage, publish,
                          section, sentence, stored_outcome)
from test_h1 import application, login  # noqa: F401
from test_h4 import conversation
from bibliotecario.explain import (EXPLAIN_SYSTEM, figure_call_schema, figure_hint, synthesis_schema,
                                   validate_synthesis)
from bibliotecario.models import Message
from bibliotecario.providers import ProviderError

DOC_TIMELINE = ("# Cronología\n\n"
                "La Revolución francesa estalló en 1789, el Terror llegó en 1793 "
                "y el Directorio cayó en 1799.\n").encode()
DOC_TABLE = ("# Titulo\n\nLa caja pesa 8 kg por palé.\n\n## Otra sección\n\n"
             "La distancia hasta el almacén es 30 km.\n").encode()

TIMELINE_SOURCES = [
    passage("C1", "En 1789 estalló la Revolución francesa."),
    passage("C2", "En 1793 comienza el Terror."),
    passage("C3", "En 1799 cae el Directorio."),
]
STEP_SOURCES = [passage("C1", "1. Corta el suministro.\n2. Abre el panel.\n3. Revisa los fusibles.")]
PASO_SOURCES = [passage("C1", "Paso 1: corta.\nPaso 2: abre.\nPaso 3: revisa.")]
BULLET_SOURCES = [passage("C1", "· Corta el suministro.\n· Abre el panel.\n· Revisa los fusibles.")]
TABLE_SOURCES = [passage("C1", "La caja pesa 8 kg."), passage("C2", "La distancia es 30 km.")]
BARS_SOURCES = [passage("C1", "El arábica tiene 1,2 % de cafeína y el robusta llega al 2,2 %.")]
PROSE_SOURCES = [passage("C1", "El manual describe la instalación."),
                 passage("C2", "Los sensores se calibran cada semana.")]


def marker_of(candidates, needle):
    for index, candidate in enumerate(candidates):
        if needle in candidate["content"]:
            return f"C{index + 1}"
    raise AssertionError(f"ningún pasaje contiene {needle!r}")


def mock_generation(monkeypatch, app, payload, rejected=(), figure=None):
    """Mock of the synthesis stream, the sentence audits and the figure call.

    Every request is recorded, so a test that must not see the second call
    asserts its absence: the recorded ("figure", max_tokens) entry is the
    failing double.
    """
    calls = []

    async def stream(messages, **kwargs):
        calls.append(("synthesis", sorted(kwargs["response_schema"]["properties"])))
        yield json.dumps(payload, ensure_ascii=False)

    async def generate(messages, max_tokens=128, **kwargs):
        body = json.loads(messages[1]["content"])
        if "claims" in body:
            calls.append(("audit", max_tokens))
            return json.dumps({"supported": body["claims"][0]["claim"] not in rejected})
        calls.append(("figure", max_tokens))
        if isinstance(figure, BaseException):
            raise figure
        return json.dumps(figure, ensure_ascii=False)

    monkeypatch.setattr(app.state.clients, "stream_generate", stream)
    monkeypatch.setattr(app.state.clients, "generate", generate)
    return calls


# --- Pista determinista -----------------------------------------------------


def test_figure_hint_timeline_needs_three_distinct_years():
    assert figure_hint(TIMELINE_SOURCES) == "timeline"
    assert figure_hint(TIMELINE_SOURCES[:2]) is None  # two years are not a chronology
    assert figure_hint([passage("C1", "En 1789 estalló la Revolución.")]) is None  # one stray year


def test_figure_hint_steps_needs_three_numbered_lines():
    assert figure_hint(STEP_SOURCES) == "steps"
    assert figure_hint(PASO_SOURCES) == "steps"
    assert figure_hint(BULLET_SOURCES) == "steps"
    assert figure_hint([passage("C1", "1. Corta.\n2. Abre.")]) is None  # two lines are prose
    # Decimal numbers and thousands groups at the margin are not list items,
    # and distinct units are no bars series either.
    assert figure_hint([passage("C1", "2.5 kg de harina\n30 km hasta el molo\n1.000 euros de caja")]) is None


def test_figure_hint_table_needs_two_sources_with_units():
    assert figure_hint(TABLE_SOURCES) == "table"
    assert figure_hint([TABLE_SOURCES[0]]) is None  # a single source is not a cross source table
    assert figure_hint([passage("C1", "Tiene 3 módulos."),
                        passage("C2", "Requiere 4 sensores.")]) is None  # units outside the catalogue


def test_figure_hint_bars_needs_two_figures_with_the_same_unit():
    assert figure_hint(BARS_SOURCES) == "bars"
    assert figure_hint([passage("C1", "Pesa 8 kg y mide 30 km.")]) is None  # distinct units, no series


def test_figure_hint_none_for_plain_prose_or_an_empty_turn():
    assert figure_hint(PROSE_SOURCES) is None
    assert figure_hint([]) is None


def test_figure_hint_does_not_fire_on_a_stray_year_or_an_isolated_figure():
    assert figure_hint([passage("C1", "La muestra pesa 7 kg y ya está evaluada.")]) is None
    assert figure_hint([passage("C1", "En 1789 estalló la Revolución."),
                        passage("C2", "El Terror fue breve.")]) is None
    assert figure_hint([passage("C1", "En 1789 pesaba 7 kg.")]) is None  # one year plus one figure


def test_figure_hint_is_pure_and_steps_come_first():
    sources = STEP_SOURCES + TIMELINE_SOURCES  # numbered lines and years in the same turn
    snapshot = json.dumps(sources, ensure_ascii=False)
    assert figure_hint(sources) == figure_hint(sources) == "steps"
    assert json.dumps(sources, ensure_ascii=False) == snapshot  # no mutation, no hidden state


# --- Contrato: la síntesis ya no pide figura --------------------------------


def test_synthesis_schema_no_longer_announces_the_figure():
    schema = synthesis_schema(SOURCES)
    assert set(schema["properties"]) == {"sections"}
    assert schema["additionalProperties"] is False  # no figure key can ride along
    assert '"figure"' not in EXPLAIN_SYSTEM  # the synthesis prompt no longer asks for one


def test_validate_synthesis_tolerates_and_ignores_a_stale_figure_key():
    stale = {"kind": "bars", "title": "Comparativa", "source_citations": ["C1"],
             "bars": {"unit": "kg", "series": [{"label": "Prueba", "value": 3, "citations": ["C1"]}]}}
    content, used, validation = validate_synthesis(json.dumps(SYNTHESIS | {"figure": stale},
                                                             ensure_ascii=False), SOURCES)
    assert content == ("**Composición del sistema**\n\nEl sistema tiene 3 módulos. [C1] "
                       "Requiere además 4 sensores. [C2]")
    assert "figure" not in json.dumps(validation)  # the stale figure is never read
    # Any value of the ignored key is dead weight now: a list no longer topples the text.
    content, _, _ = validate_synthesis(json.dumps(SYNTHESIS | {"figure": [stale, stale]},
                                                  ensure_ascii=False), SOURCES)
    assert content.startswith("**Composición del sistema**")
    # Any other extra root key is still an envelope violation.
    with pytest.raises(ValueError) as error:
        validate_synthesis(json.dumps(SYNTHESIS | {"figures": [stale]}, ensure_ascii=False), SOURCES)
    assert error.value.args[0] == "invalid_synthesis"


def test_figure_call_schema_is_decline_first():
    schema = figure_call_schema(["C1", "C2"])
    assert schema["required"] == ["decline"] and schema["additionalProperties"] is False
    assert schema["properties"]["decline"] == {"type": "boolean"}
    figure = schema["properties"]["figure"]
    assert figure["required"] == ["kind", "title", "source_citations"]
    assert figure["properties"]["source_citations"]["items"]["enum"] == ["C1", "C2"]
    for kind in ("table", "timeline", "bars", "steps"):
        assert kind in figure["properties"] and figure["properties"][kind]["additionalProperties"] is False


# --- El turno explain: segunda llamada, validación y descarte ----------------


def test_no_second_call_without_a_hint(application, monkeypatch):
    app, client, sessions = application
    login(client)
    candidates = publish(application)  # módulos y sensores: nothing plottable
    mock_retrieval(monkeypatch, candidates, answer=True)
    calls = mock_generation(monkeypatch, app, SYNTHESIS)
    message = explain_turn(client, conversation(client), "explain")[-1]["message"]
    assert message["status"] == "completed" and message["figures"] == []
    # The failing double: any figure-shaped request would be recorded here.
    assert [kind for kind, _ in calls] == ["synthesis", "audit", "audit"]
    print("LLAMADAS_SIN_PISTA=3 (síntesis 1 + auditorías 2); LLAMADAS_FIGURA=0")
    assert stored_outcome(sessions, message) == {"status": "completed", "reason": "grounded",
                                                 "mode": "explain", "figure_hint": None}


def test_timeline_figure_is_requested_published_and_saved(application, monkeypatch):
    app, client, sessions = application
    login(client)
    candidates = publish(application, DOC_TIMELINE)
    mock_retrieval(monkeypatch, candidates, answer=True)
    marker = marker_of(candidates, "1789")
    synthesis = {"sections": [section("Revolución francesa", [
        sentence("La Revolución francesa estalló en 1789.", [marker]),
        sentence("El Terror llegó en 1793.", [marker])])]}
    expected = {"kind": "timeline", "title": "Revolución francesa", "source_citations": [marker],
                "timeline": {"events": [{"when": "1789", "label": "Estalla la Revolución", "citations": [marker]},
                                        {"when": "1793", "label": "Comienza el Terror", "citations": [marker]}]}}
    calls = mock_generation(monkeypatch, app, synthesis,
                            figure={"decline": False, "figure": expected})
    events = explain_turn(client, conversation(client), "explain")
    message = events[-1]["message"]
    assert message["status"] == "completed"
    assert message["content"].startswith("**Revolución francesa**")  # the text is untouched
    print("FIGURA_ACEPTADA=" + json.dumps(message["figures"][0], ensure_ascii=False))
    assert message["figures"] == [expected]  # the done event carries the cleaned figure
    with sessions() as db:
        assert db.get(Message, message["id"]).figures == [expected]  # saved with the message
    assert stored_outcome(sessions, message) == {"status": "completed", "reason": "grounded",
                                                 "mode": "explain", "figure_hint": "timeline",
                                                 "figure": {"present": True, "kind": "timeline"}}
    # Cost: one synthesis, one audit per sentence, exactly one figure call with moderate tokens.
    assert [kind for kind, _ in calls] == ["synthesis", "audit", "audit", "figure"]
    assert calls[-1][1] == 2000
    print("LLAMADAS_CON_PISTA=4 (síntesis 1 + auditorías 2 + figura 1); LLAMADAS_FIGURA=1; MAX_TOKENS=2000")


def test_decline_true_wins_over_a_present_figure(application, monkeypatch):
    app, client, sessions = application
    login(client)
    candidates = publish(application, DOC_TIMELINE)
    mock_retrieval(monkeypatch, candidates, answer=True)
    marker = marker_of(candidates, "1789")
    synthesis = {"sections": [section("Revolución francesa", [
        sentence("La Revolución francesa estalló en 1789.", [marker])])]}
    mock_generation(monkeypatch, app, synthesis, figure={
        "decline": True, "figure": {"kind": "timeline", "title": "Revolución",
                                    "source_citations": [marker],
                                    "timeline": {"events": [{"when": "1789", "label": "Estalla",
                                                             "citations": [marker]}]}}})
    message = explain_turn(client, conversation(client), "explain")[-1]["message"]
    assert message["status"] == "completed" and message["content"].startswith("**Revolución francesa**")
    assert message["figures"] == []
    outcome = stored_outcome(sessions, message)
    assert outcome["figure_hint"] == "timeline" and outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "declined"


def test_second_call_without_a_figure_is_a_decline(application, monkeypatch):
    app, client, sessions = application
    login(client)
    candidates = publish(application, DOC_TIMELINE)
    mock_retrieval(monkeypatch, candidates, answer=True)
    marker = marker_of(candidates, "1789")
    synthesis = {"sections": [section("Revolución francesa", [
        sentence("La Revolución francesa estalló en 1789.", [marker])])]}
    mock_generation(monkeypatch, app, synthesis, figure={"decline": False})
    message = explain_turn(client, conversation(client), "explain")[-1]["message"]
    assert message["status"] == "completed" and message["figures"] == []
    outcome = stored_outcome(sessions, message)
    assert outcome["figure_hint"] == "timeline" and outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "declined"


def test_failed_figure_call_sheds_only_the_figure_slot(application, monkeypatch):
    app, client, sessions = application
    login(client)
    candidates = publish(application, DOC_TIMELINE)
    mock_retrieval(monkeypatch, candidates, answer=True)
    marker = marker_of(candidates, "1789")
    synthesis = {"sections": [section("Revolución francesa", [
        sentence("La Revolución francesa estalló en 1789.", [marker])])]}
    mock_generation(monkeypatch, app, synthesis, figure=ProviderError("invalid_generation"))
    message = explain_turn(client, conversation(client), "explain")[-1]["message"]
    assert message["status"] == "completed"  # the figure never changes the turn's fate
    assert message["content"].startswith("**Revolución francesa**")
    assert message["figures"] == []
    outcome = stored_outcome(sessions, message)
    assert outcome["figure_hint"] == "timeline" and outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "figure_call_failed"


def test_figure_number_outside_its_citations_is_dropped(application, monkeypatch):
    app, client, sessions = application
    login(client)
    candidates = publish(application, DOC_TIMELINE)
    mock_retrieval(monkeypatch, candidates, answer=True)
    marker = marker_of(candidates, "1789")
    synthesis = {"sections": [section("Revolución francesa", [
        sentence("La Revolución francesa estalló en 1789.", [marker])])]}
    mock_generation(monkeypatch, app, synthesis, figure={
        "decline": False, "figure": {"kind": "timeline", "title": "Revolución",
                                     "source_citations": [marker],
                                     "timeline": {"events": [{"when": "1810",
                                                              "label": "Año sin respaldo",
                                                              "citations": [marker]}]}}})
    message = explain_turn(client, conversation(client), "explain")[-1]["message"]
    assert message["status"] == "completed"
    assert message["content"].startswith("**Revolución francesa**")  # the text is intact
    assert message["figures"] == []
    outcome = stored_outcome(sessions, message)
    print("DESCARTE=" + json.dumps(outcome, ensure_ascii=False))
    assert outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "unsupported_number"


def test_figure_with_unknown_citation_is_dropped(application, monkeypatch):
    app, client, sessions = application
    login(client)
    candidates = publish(application, DOC_TIMELINE)
    mock_retrieval(monkeypatch, candidates, answer=True)
    marker = marker_of(candidates, "1789")
    synthesis = {"sections": [section("Revolución francesa", [
        sentence("La Revolución francesa estalló en 1789.", [marker])])]}
    mock_generation(monkeypatch, app, synthesis, figure={
        "decline": False, "figure": {"kind": "timeline", "title": "Revolución",
                                     "source_citations": [marker],
                                     "timeline": {"events": [{"when": "1789", "label": "Estalla",
                                                              "citations": ["C9"]}]}}})
    message = explain_turn(client, conversation(client), "explain")[-1]["message"]
    assert message["status"] == "completed" and message["figures"] == []
    outcome = stored_outcome(sessions, message)
    assert outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "citation_unknown"


def test_text_fallback_skips_the_second_call(application, monkeypatch):
    app, client, sessions = application
    login(client)
    candidates = publish(application, DOC_TIMELINE)
    mock_retrieval(monkeypatch, candidates, answer=True)
    marker = marker_of(candidates, "1789")
    synthesis = {"sections": [section("Composición", [
        sentence("El despliegue necesita 7 componentes.", [marker])])]}
    calls = mock_generation(monkeypatch, app, synthesis)  # the double: no figure entry allowed
    message = explain_turn(client, conversation(client), "explain")[-1]["message"]
    assert message["status"] == "completed" and message["content"].startswith("Extractos literales")
    # The text was never grounded, so no audit ran and no figure was asked.
    assert [kind for kind, _ in calls] == ["synthesis"]
    outcome = stored_outcome(sessions, message)
    assert outcome["fallback"]["reason"] == "unsupported_number"
    assert outcome["figure_hint"] == "timeline"
    assert outcome["figure"] == {"present": False, "kind": None}
    assert outcome["figure_rejected"] == "text_fallback"
    assert message["figures"] == []


def test_answer_mode_keeps_previous_contract_without_hints(application, monkeypatch):
    app, client, sessions = application
    login(client)
    candidates = publish(application, DOC_TIMELINE)
    mock_retrieval(monkeypatch, candidates, answer=True)
    evidence = {"evidence": [{"citation_id": f"C{i + 1}", "explanation": c["content"].strip()}
                             for i, c in enumerate(candidates)]}
    calls = mock_generation(monkeypatch, app, evidence)
    message = explain_turn(client, conversation(client), "answer")[-1]["message"]
    assert message["status"] == "completed" and message["figures"] == []
    assert calls[0] == ("synthesis", ["evidence"])  # the answer schema stays closed
    assert "figure" not in [kind for kind, _ in calls]  # answer never asks for a figure
    # Byte-identical outcome: no mode and no figure_hint for answer turns.
    assert stored_outcome(sessions, message) == {"status": "completed", "reason": "grounded"}
