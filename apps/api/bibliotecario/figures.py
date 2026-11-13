"""Declarative figures: typed data the web renders with fixed components.

The model never produces HTML. Every figure is closed data validated
server-side: undeclared fields are rejected, sizes are bounded, and every
number stated in the figure must come from the citations of its own datum.
This module is stdlib + pydantic only; it renders nothing.
"""
import math
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from typing import Literal

from .textnums import numbers

KINDS = ("table", "timeline", "bars", "steps")


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TablePayload(_Closed):
    columns: list[str] = Field(min_length=2, max_length=6)
    rows: list[list[str]] = Field(min_length=1, max_length=12)


class TimelineEvent(_Closed):
    when: str = Field(max_length=40)
    label: str = Field(max_length=160)
    citations: list[str] = Field(min_length=1, max_length=3)


class TimelinePayload(_Closed):
    events: list[TimelineEvent] = Field(min_length=1, max_length=12)


class BarSeries(_Closed):
    label: str = Field(max_length=80)
    value: float
    citations: list[str] = Field(min_length=1, max_length=3)


class BarsPayload(_Closed):
    unit: str = Field(max_length=16)
    series: list[BarSeries] = Field(min_length=1, max_length=12)


class Step(_Closed):
    label: str = Field(max_length=120)
    detail: str | None = Field(default=None, max_length=240)
    citations: list[str] = Field(min_length=1, max_length=3)


class StepsPayload(_Closed):
    items: list[Step] = Field(min_length=1, max_length=8)


PAYLOAD_MODELS = {"table": TablePayload, "timeline": TimelinePayload,
                  "bars": BarsPayload, "steps": StepsPayload}


class Figure(_Closed):
    kind: Literal["table", "timeline", "bars", "steps"]
    title: str = Field(min_length=1, max_length=120)
    caption: str | None = Field(default=None, max_length=240)
    source_citations: list[str] = Field(min_length=1, max_length=4)
    table: TablePayload | None = None
    timeline: TimelinePayload | None = None
    bars: BarsPayload | None = None
    steps: StepsPayload | None = None

    @model_validator(mode="after")
    def _exactly_the_kind_payload(self):
        present = [key for key in KINDS if getattr(self, key) is not None]
        if present != [self.kind]:
            raise ValueError("missing_payload" if not present else "extra_field")
        return self


# Control characters, line breaks and zero-width/bidi marks never belong in
# plain-text fields: the contract is data, not markup.
_FORBIDDEN = re.compile("[\x00-\x1f\x7f\u200b\u200c\u200d\u200e\u200f\u2060-\u2064\ufeff]")


def _clean_text(value):
    """(text, None) for acceptable plain text, else (None, reason).

    Text must be a string without control or zero-width characters and must
    not be empty once stripped. The stored value is the stripped text; sizes
    are measured on it, never silently truncated.
    """
    if not isinstance(value, str) or _FORBIDDEN.search(value):
        return None, "invalid_text"
    cleaned = value.strip()
    if not cleaned:
        return None, "invalid_text"
    return cleaned, None


def _citations(value, source_ids, maximum):
    """(citations, None) when every reference is a distinct turn source."""
    if not isinstance(value, list) or not value:
        return None, "citation_unknown"
    if len(value) > maximum:
        return None, "too_large"
    for marker in value:
        if not isinstance(marker, str) or marker not in source_ids:
            return None, "citation_unknown"
    if len(set(value)) != len(value):
        # A repeated marker is not a citation of the turn.
        return None, "citation_unknown"
    return value, None


def _numbers_supported(texts, citations, allowed_numbers):
    pool = set()
    for marker in citations:
        pool |= allowed_numbers.get(marker, set())
    for text in texts:
        if numbers(text) - pool:
            return False
    return True


def validate_figure(payload, source_ids, allowed_numbers):
    """Validate one declarative figure against the closed contract.

    Returns (figure, None), a cleaned JSON-safe dict, or (None, reason).
    Reasons: unknown_kind, extra_field, missing_payload, citation_unknown,
    too_large, invalid_text, negative_value, not_number, unsupported_number.
    """
    if not isinstance(payload, dict):
        return None, "invalid_text"
    if "kind" not in payload:
        return None, "missing_payload"
    kind = payload["kind"]
    if not isinstance(kind, str) or kind not in PAYLOAD_MODELS:
        return None, "unknown_kind"
    allowed_root = {"kind", "title", "caption", "source_citations", kind}
    if any(key not in allowed_root for key in payload):
        return None, "extra_field"
    body = payload.get(kind)
    if not isinstance(body, dict):
        return None, "missing_payload"
    if "title" not in payload or "source_citations" not in payload:
        return None, "missing_payload"
    title, reason = _clean_text(payload["title"])
    if reason:
        return None, reason
    if len(title) > 120:
        return None, "too_large"
    caption = None
    if payload.get("caption") is not None:
        caption, reason = _clean_text(payload["caption"])
        if reason:
            return None, reason
        if len(caption) > 240:
            return None, "too_large"
    source_citations, reason = _citations(payload["source_citations"], source_ids, 4)
    if reason:
        return None, reason

    clean_body = None
    if kind == "table":
        if any(key not in {"columns", "rows"} for key in body):
            return None, "extra_field"
        columns = body.get("columns")
        if not isinstance(columns, list) or len(columns) < 2:
            return None, "missing_payload"
        if len(columns) > 6:
            return None, "too_large"
        clean_columns = []
        for column in columns:
            column, reason = _clean_text(column)
            if reason:
                return None, reason
            if len(column) > 80:
                return None, "too_large"
            clean_columns.append(column)
        rows = body.get("rows")
        if not isinstance(rows, list) or not rows:
            return None, "missing_payload"
        if len(rows) > 12:
            return None, "too_large"
        clean_rows = []
        for row in rows:
            if not isinstance(row, list) or len(row) != len(clean_columns):
                return None, "missing_payload"
            clean_row = []
            for cell in row:
                cell, reason = _clean_text(cell)
                if reason:
                    return None, reason
                if len(cell) > 240:
                    return None, "too_large"
                clean_row.append(cell)
            # A table cell cites the figure's own sources.
            if not _numbers_supported(clean_row, source_citations, allowed_numbers):
                return None, "unsupported_number"
            clean_rows.append(clean_row)
        clean_body = {"columns": clean_columns, "rows": clean_rows}
    elif kind == "timeline":
        if any(key not in {"events"} for key in body):
            return None, "extra_field"
        events = body.get("events")
        if not isinstance(events, list) or not events:
            return None, "missing_payload"
        if len(events) > 12:
            return None, "too_large"
        clean_events = []
        for event in events:
            if not isinstance(event, dict) or any(key not in {"when", "label", "citations"} for key in event):
                return None, "extra_field" if isinstance(event, dict) else "missing_payload"
            if not {"when", "label", "citations"} <= set(event):
                return None, "missing_payload"
            when, reason = _clean_text(event["when"])
            if reason:
                return None, reason
            if len(when) > 40:
                return None, "too_large"
            label, reason = _clean_text(event["label"])
            if reason:
                return None, reason
            if len(label) > 160:
                return None, "too_large"
            citations, reason = _citations(event["citations"], source_ids, 3)
            if reason:
                return None, reason
            if not _numbers_supported([when, label], citations, allowed_numbers):
                return None, "unsupported_number"
            clean_events.append({"when": when, "label": label, "citations": citations})
        clean_body = {"events": clean_events}
    elif kind == "bars":
        if any(key not in {"unit", "series"} for key in body):
            return None, "extra_field"
        if "unit" not in body or "series" not in body:
            return None, "missing_payload"
        unit, reason = _clean_text(body["unit"])
        if reason:
            return None, reason
        if len(unit) > 16:
            return None, "too_large"
        series = body["series"]
        if not isinstance(series, list) or not series:
            return None, "missing_payload"
        if len(series) > 12:
            return None, "too_large"
        clean_series = []
        for item in series:
            if not isinstance(item, dict) or any(key not in {"label", "value", "citations"} for key in item):
                return None, "extra_field" if isinstance(item, dict) else "missing_payload"
            if not {"label", "value", "citations"} <= set(item):
                return None, "missing_payload"
            label, reason = _clean_text(item["label"])
            if reason:
                return None, reason
            if len(label) > 80:
                return None, "too_large"
            value = item["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return None, "not_number"
            if value < 0:
                return None, "negative_value"
            citations, reason = _citations(item["citations"], source_ids, 3)
            if reason:
                return None, reason
            value = float(value)
            if not _numbers_supported([label], citations, allowed_numbers) or value not in {
                    number for marker in citations for number in allowed_numbers.get(marker, set())}:
                return None, "unsupported_number"
            clean_series.append({"label": label, "value": value, "citations": citations})
        clean_body = {"unit": unit, "series": clean_series}
    else:
        if any(key not in {"items"} for key in body):
            return None, "extra_field"
        items = body.get("items")
        if not isinstance(items, list) or not items:
            return None, "missing_payload"
        if len(items) > 8:
            return None, "too_large"
        clean_items = []
        for item in items:
            if not isinstance(item, dict) or any(key not in {"label", "detail", "citations"} for key in item):
                return None, "extra_field" if isinstance(item, dict) else "missing_payload"
            if not {"label", "citations"} <= set(item):
                return None, "missing_payload"
            label, reason = _clean_text(item["label"])
            if reason:
                return None, reason
            if len(label) > 120:
                return None, "too_large"
            detail = None
            if item.get("detail") is not None:
                detail, reason = _clean_text(item["detail"])
                if reason:
                    return None, reason
                if len(detail) > 240:
                    return None, "too_large"
            citations, reason = _citations(item["citations"], source_ids, 3)
            if reason:
                return None, reason
            if not _numbers_supported([label] if detail is None else [label, detail],
                                      citations, allowed_numbers):
                return None, "unsupported_number"
            clean_item = {"label": label, "citations": citations}
            if detail is not None:
                clean_item["detail"] = detail
            clean_items.append(clean_item)
        clean_body = {"items": clean_items}

    figure = {"kind": kind, "title": title, "source_citations": source_citations}
    if caption is not None:
        figure["caption"] = caption
    figure[kind] = clean_body
    try:
        Figure.model_validate(figure)
    except ValidationError:
        # The closed models and this validator must agree; a mismatch here is
        # contract drift, not a model fault.
        return None, "invalid_text"
    return figure, None
