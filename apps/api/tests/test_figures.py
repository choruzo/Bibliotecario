"""Declarative figure contract: closed payloads, bounded sizes, cited numbers.

`message_json` figures tests use bare Message objects: no database is needed
to prove that a None column renders as [] and a saved figure round-trips.
"""
import pytest
from pydantic import ValidationError

from bibliotecario.chat import message_json, numbers
from bibliotecario.figures import Figure, TablePayload, validate_figure
from bibliotecario.models import Message
from bibliotecario.textnums import numbers as extracted_numbers

SOURCES = {"C1", "C2", "C3"}

TABLE = {
    "kind": "table",
    "title": "Ciclo de desarrollo de las castas",
    "source_citations": ["C1"],
    "table": {
        "columns": ["Casta", "Dias de desarrollo"],
        "rows": [["Reina", "16 dias"]],
    },
}
TIMELINE = {
    "kind": "timeline",
    "title": "Cronologia del traslado",
    "source_citations": ["C1"],
    "timeline": {
        "events": [{"when": "12 de mayo", "label": "Llegada de la colmena", "citations": ["C1"]}],
    },
}
BARS = {
    "kind": "bars",
    "title": "Cuadros por colmena",
    "source_citations": ["C1"],
    "bars": {
        "unit": "cuadros",
        "series": [{"label": "Camara de cria", "value": 5, "citations": ["C1"]}],
    },
}
STEPS = {
    "kind": "steps",
    "title": "Alimentacion de una colonia",
    "source_citations": ["C2"],
    "steps": {
        "items": [{"label": "Colocar el alimentador", "detail": "Anadir 1 litro", "citations": ["C2"]}],
    },
}
ALLOWED = {"C1": {16.0, 12.0, 5.0}, "C2": {1.0}, "C3": {24.0}}


def allowed(pairs):
    return {citation: set(values) for citation, values in pairs}


def valid(payload):
    figure, reason = validate_figure(payload, SOURCES, ALLOWED)
    assert reason is None, reason
    return figure


def rejected(payload, sources=SOURCES, numbers_by_citation=ALLOWED):
    figure, reason = validate_figure(payload, sources, numbers_by_citation)
    assert figure is None
    return reason


def test_table_minimum_payload_is_valid():
    figure = valid(TABLE)
    assert figure["kind"] == "table"
    assert figure["table"]["rows"] == [["Reina", "16 dias"]]


def test_timeline_minimum_payload_is_valid():
    figure = valid(TIMELINE)
    assert figure["timeline"]["events"] == [
        {"when": "12 de mayo", "label": "Llegada de la colmena", "citations": ["C1"]}]


def test_bars_minimum_payload_is_valid():
    figure = valid(BARS)
    assert figure["bars"] == {"unit": "cuadros",
                              "series": [{"label": "Camara de cria", "value": 5.0, "citations": ["C1"]}]}


def test_steps_minimum_payload_is_valid():
    figure = valid(STEPS)
    assert figure["steps"]["items"] == [
        {"label": "Colocar el alimentador", "detail": "Anadir 1 litro", "citations": ["C2"]}]


def test_clean_figure_has_only_the_kind_payload_key():
    for payload in (TABLE, TIMELINE, BARS, STEPS):
        figure = valid(payload)
        assert set(figure) == {"kind", "title", "source_citations", payload["kind"]}
        assert None not in figure.values()


def test_unknown_kind_is_rejected():
    assert rejected(TABLE | {"kind": "chart"}) == "unknown_kind"
    assert rejected(TABLE | {"kind": ["table"]}) == "unknown_kind"


def test_root_extra_field_is_rejected():
    assert rejected(TABLE | {"html": "<table>"}) == "extra_field"


def test_nested_extra_field_is_rejected():
    payload = {
        "kind": "timeline",
        "title": "Cronologia",
        "source_citations": ["C1"],
        "timeline": {"events": [{"when": "12 de mayo", "label": "Llegada", "citations": ["C1"],
                                 "timestamp": 1715162400}]},
    }
    assert rejected(payload) == "extra_field"


def test_href_and_url_are_rejected_as_extra_fields():
    assert rejected(TABLE | {"href": "javascript:alert(1)"}) == "extra_field"
    assert rejected(BARS | {"url": "https://example.test"}) == "extra_field"


def test_missing_payload_key_is_rejected():
    payload = {"kind": "table", "title": "T", "source_citations": ["C1"]}
    assert rejected(payload) == "missing_payload"


def test_payload_key_mismatching_kind_is_rejected():
    payload = dict(TABLE, bars=BARS["bars"])
    assert rejected(payload) == "extra_field"


def test_more_than_six_columns_is_rejected():
    payload = {"kind": "table", "title": "T", "source_citations": ["C1"],
               "table": {"columns": [f"Col {n}" for n in range(7)],
                         "rows": [["1", "2", "3", "4", "5", "6", "7"]]}}
    assert rejected(payload) == "too_large"


def test_more_than_twelve_rows_is_rejected():
    payload = {"kind": "table", "title": "T", "source_citations": ["C1"],
               "table": {"columns": ["Casta", "Dias"],
                         "rows": [["Reina", "16 dias"]] * 13}}
    assert rejected(payload) == "too_large"


def test_241_character_cell_is_rejected():
    payload = {"kind": "table", "title": "T", "source_citations": ["C1"],
               "table": {"columns": ["Casta", "Dias"],
                         "rows": [["Reina", "x" * 241]]}}
    assert rejected(payload) == "too_large"


def test_control_character_is_rejected():
    payload = {"kind": "table", "title": "T", "source_citations": ["C1"],
               "table": {"columns": ["Casta", "Dias"],
                         "rows": [["Reina", "16 dias\x07"]]}}
    assert rejected(payload) == "invalid_text"
    payload["table"]["rows"] = [["Reina", "16\ndias"]]
    assert rejected(payload) == "invalid_text"


def test_zero_width_character_is_rejected():
    payload = {"kind": "table", "title": "T\u200b", "source_citations": ["C1"], "table": TABLE["table"]}
    assert rejected(payload) == "invalid_text"


def test_empty_or_absent_title_is_rejected():
    assert rejected(TABLE | {"title": "   "}) == "invalid_text"
    payload = {key: value for key, value in TABLE.items() if key != "title"}
    assert rejected(payload) == "missing_payload"


def test_citation_outside_sources_is_rejected():
    payload = {"kind": "timeline", "title": "T", "source_citations": ["C9"],
               "timeline": {"events": [{"when": "12 de mayo", "label": "Llegada", "citations": ["C9"]}]}}
    assert rejected(payload) == "citation_unknown"
    payload["source_citations"] = ["C1"]
    assert rejected(payload) == "citation_unknown"


def test_duplicated_source_citation_is_rejected():
    assert rejected(TABLE | {"source_citations": ["C1", "C1"]}) == "citation_unknown"


def test_more_than_four_source_citations_is_rejected():
    payload = dict(TABLE, source_citations=["C1", "C2", "C3", "C1", "C2"])
    assert rejected(payload) == "too_large"


def test_negative_value_is_rejected():
    payload = {"kind": "bars", "title": "T", "source_citations": ["C1"],
               "bars": {"unit": "cuadros", "series": [{"label": "Perdidas", "value": -2, "citations": ["C1"]}]}}
    assert rejected(payload) == "negative_value"


def test_non_numeric_value_is_rejected():
    for bad in ("5", True, None, [5]):
        payload = {"kind": "bars", "title": "T", "source_citations": ["C1"],
                   "bars": {"unit": "cuadros", "series": [{"label": "Camara", "value": bad, "citations": ["C1"]}]}}
        assert rejected(payload) == "not_number", bad


def test_non_finite_value_is_rejected():
    payload = {"kind": "bars", "title": "T", "source_citations": ["C1"],
               "bars": {"unit": "cuadros", "series": [{"label": "Camara", "value": float("nan"),
                                                       "citations": ["C1"]}]}}
    assert rejected(payload) == "not_number"


def test_cell_number_outside_its_own_citations_is_rejected():
    payload = {"kind": "table", "title": "T", "source_citations": ["C1"],
               "table": {"columns": ["Colmena", "Cuadros"], "rows": [["A", "24 cuadros"]]}}
    assert rejected(payload, numbers_by_citation=allowed([("C1", {16.0})])) == "unsupported_number"


def test_number_from_uncited_neighbour_is_rejected():
    # 24 exists in C3 of the same turn, but the cell cites only C1: rejected.
    payload = {"kind": "table", "title": "T", "source_citations": ["C1"],
               "table": {"columns": ["Colmena", "Cuadros"], "rows": [["A", "24 cuadros"]]}}
    assert rejected(payload) == "unsupported_number"


def test_word_number_in_label_is_supported_by_its_citation():
    # "treinta y dos" states 2, 30 and 32 (see numbers()); a passage that says
    # it supports them all, a passage that only says "32" does not.
    payload = {"kind": "steps", "title": "T", "source_citations": ["C2"],
               "steps": {"items": [{"label": "Esperar treinta y dos dias", "citations": ["C2"]}]}}
    figure, reason = validate_figure(payload, SOURCES, allowed([("C2", {2.0, 30.0, 32.0})]))
    assert reason is None and figure["steps"]["items"][0]["label"].endswith("dias")
    assert rejected(payload, numbers_by_citation=allowed([("C2", {32.0})])) == "unsupported_number"


def test_row_shapes_must_match_columns():
    payload = {"kind": "table", "title": "T", "source_citations": ["C1"],
               "table": {"columns": ["Casta", "Dias"], "rows": [["Reina", "16 dias", "extra"]]}}
    assert rejected(payload) == "missing_payload"


def test_timeline_event_limits_apply():
    payload = {"kind": "timeline", "title": "T", "source_citations": ["C1"],
               "timeline": {"events": [{"when": "12 de mayo", "label": "L" * 161, "citations": ["C1"]}]}}
    assert rejected(payload) == "too_large"
    payload["timeline"]["events"] = [{"when": "12 de mayo", "label": "L", "citations": ["C1"]}] * 13
    assert rejected(payload) == "too_large"


def test_bars_and_steps_collection_limits_apply():
    payload = {"kind": "bars", "title": "T", "source_citations": ["C1"],
               "bars": {"unit": "u" * 17, "series": [{"label": "L", "value": 1, "citations": ["C1"]}]}}
    assert rejected(payload) == "too_large"
    payload = {"kind": "steps", "title": "T", "source_citations": ["C2"],
               "steps": {"items": [{"label": "L", "citations": ["C2"]}] * 9}}
    assert rejected(payload) == "too_large"


def test_nested_models_are_closed_too():
    with pytest.raises(ValidationError):
        TablePayload.model_validate({"columns": ["a", "b"], "rows": [["1", "2"]], "href": "javascript:"})
    with pytest.raises(ValidationError):
        Figure.model_validate(TABLE | {"style": "color:red"})
    with pytest.raises(ValidationError):
        Figure.model_validate(TIMELINE | {"steps": STEPS["steps"]})


def test_message_json_returns_empty_figures_for_none_column():
    message = Message(conversation_id="c", number=1, role="assistant", content="x",
                      status="completed", created_at=0)
    assert message.figures is None
    assert message_json(message)["figures"] == []


def test_message_json_returns_saved_figures_verbatim():
    figure = valid(TABLE)
    message = Message(conversation_id="c", number=1, role="assistant", content="x",
                      status="completed", created_at=0)
    message.figures = [figure]
    assert message_json(message)["figures"] == [figure]


def test_numbers_extraction_survives_the_move_to_textnums():
    assert extracted_numbers is numbers
    assert numbers("veintiún días, 5½ días y treinta y dos") >= {21, 5.5, 32}
    assert numbers("de dos a cuatro años") == {2, 4}
    assert numbers("una semana") == set()
