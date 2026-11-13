"""Multi-query decomposition: facets for questions that span several topics.

A question whose evidence lives in two documents ("abejas y fotosíntesis")
resembles a single aspect, so retrieval only surfaces passages of one of them and
the assessment never sees the second aspect. Decomposition asks the model for
self-contained search queries — one per aspect — so every aspect gets its own
candidate pool before the union is reranked.

It never raises: any provider error, timeout or invalid JSON returns [] and the
turn continues with today's single-query retrieval.
"""
import unicodedata
from typing import Annotated

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from .providers import LLM_PHASE, ProviderError

DECOMPOSE_MAX_TOKENS = 500
DECOMPOSE_PROMPT = """Descompón la pregunta en consultas de búsqueda independientes, una por cada aspecto o tema distinto que necesite evidencia propia para responderla.
Devuelve exclusivamente JSON {"facets": ["consulta 1", "consulta 2"]}.
Cada facet es una consulta de búsqueda breve, en español y autocontenida: debe poder buscarse sola, sin pronombres ni referencias a la pregunta original ni a otras facets.
No parafrasees la pregunta completa: cada facet cubre UN aspecto distinto (un concepto, un dato o un procedimiento concreto) que por sí solo necesite pasajes propios.
No añadas hechos, nombres, cifras ni supuestos que la pregunta no mencione. No repitas la pregunta original como facet.
Si la pregunta tiene un solo tema, devuelve {"facets": []}. Máximo dos facets. No respondas la pregunta."""


class Facets(BaseModel):
    """Closed decompose schema: 0-2 self-contained queries, each 3-120 characters."""

    model_config = ConfigDict(extra="forbid", strict=True)
    facets: list[Annotated[str, StringConstraints(min_length=3, max_length=120)]] = Field(max_length=2)


def _key(text):
    """Accent- and case-folded comparison key for facet deduplication."""
    folded = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(folded.casefold().split())


async def decompose(clients, question, diagnostics=None):
    """Self-contained Spanish search queries (0-2) for the aspects of ``question``.

    Single-topic questions return []. Every failure mode (provider error,
    timeout, invalid or out-of-range JSON) also returns [] so retrieval degrades
    to the single-query path. The reason is a fixed short code — never provider
    details — stored in ``diagnostics["error"]`` when that dict is supplied.
    Facets repeating the question (or contained in it) are dropped: the original
    question already gets its own pool, and a repeated query only fattens it.
    """
    try:
        LLM_PHASE.set("facets")
        raw = await clients.generate(
            [{"role": "system", "content": DECOMPOSE_PROMPT},
             {"role": "user", "content": question}],
            max_tokens=DECOMPOSE_MAX_TOKENS, response_schema=Facets.model_json_schema())
        value = Facets.model_validate_json(raw)
    except (httpx.HTTPError, ProviderError, ValidationError, ValueError, TypeError) as exc:
        if diagnostics is not None:
            diagnostics["error"] = ("provider_timeout" if isinstance(exc, httpx.TimeoutException)
                                    else str(exc) if isinstance(exc, ProviderError) else
                                    "provider_error" if isinstance(exc, httpx.HTTPError) else "invalid_facets")
        return []
    original = _key(question)
    facets, seen = [], {original}
    for facet in value.facets:
        text = " ".join(facet.split())
        key = _key(text)
        if len(text) < 3 or len(text) > 120 or not key or key in seen:
            continue
        if key in original or original in key:
            continue
        seen.add(key)
        facets.append(text)
        if len(facets) == 2:
            break
    return facets
