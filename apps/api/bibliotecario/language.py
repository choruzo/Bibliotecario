"""Deterministic language detection and first-turn translation to Spanish.

The detector only looks at stopwords and orthographic features. It never calls a
model, so an ambiguous or very short question stays in Spanish (the corpus and
the lexical index are Spanish) and a failure to detect cannot add latency.
"""
import asyncio
import re
import unicodedata

from .providers import LLM_PHASE

DEFAULT_LANGUAGE = "es"
SUPPORTED_LANGUAGES = ("es", "en", "fr", "de", "it", "pt")

# Stopwords that are characteristic of one language. Words shared by several
# languages still add a little evidence, but a distinctive word counts twice.
STOPWORDS = {
    "es": set("""el los las unos unas del al y es son esta estan era eran ser tiene tienen puedo puede
        hay muy tambien pero mas se sus les lo mi tu este esta estos estas ese esa esos esas eso esto sin
        sobre entre desde hasta segun dice dicen hace hacen configuro""".split()),
    "en": set("""the of and to is are was were does do did how what when where which who why with for on
        from about in it its this that these those there their can could should would has have had long many
        much""".split()),
    "fr": set("""le les des du et est sont dans pour avec comment combien ou quand pourquoi une au aux ce
        cette ces qui plus pas ne sur par mais son sa ses leur leurs etre avoir fait font""".split()),
    "de": set("""der die das den dem des und ist sind nicht von zu mit fur auf sich im ein eine einen einem
        einer wie warum wann wo was wer viele mehr auch aber oder kann konnen wird werden hat haben gibt
        lebt""".split()),
    "it": set("""il lo gli le di del della dei delle che e per con come quanto quanti dove quando perche un
        una nel nella sono non piu anche ma si suo sua loro questo questa questi queste cosa chi quale quali
        fa fanno puo possono vive""".split()),
    "pt": set("""o os as de do da dos das que e para com como quanto quantos onde quando porque um uma no na
        nos nas sao nao mais tambem mas se seu sua seus suas este esta estes estas isso isto quem qual quais
        fazem pode podem ha vive rede""".split()),
}

_COUNTS = {}
for _language, _words in STOPWORDS.items():
    for _word in _words:
        _COUNTS[_word] = _COUNTS.get(_word, 0) + 1
SHARED_WORDS = {word for word, count in _COUNTS.items() if count > 1}

# Exact accented forms. Their plain form is often shared ("como" exists in
# Spanish and Portuguese), so the accent itself is the distinctive signal.
ACCENTED_WORDS = {
    "es": set("cuánto cuánta cuántos cuántas cómo dónde cuándo qué quién quiénes también está están según "
              "años más así aplicación configuración instalación".split()),
    "pt": set("são não uma você também ação informações".split()),
    "fr": set("où être très français déjà".split()),
    "de": set("für können über schön".split()),
    "it": set("perché più è città".split()),
}

_TRANSLATION_REFUSAL = re.compile(
    r"(?i)lo siento|no puedo (?:ayudar|proporcionar|traducir)|no (?:puedo|debo) (?:responder|traducir)")
_QUOTES = "\"'`“”‘’«»"


def _plain(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c))


def detect_language(text):
    """Return one of SUPPORTED_LANGUAGES, defaulting to Spanish when in doubt."""
    if not text or not text.strip():
        return DEFAULT_LANGUAGE
    low = text.casefold()
    plain = _plain(text)
    tokens = re.findall(r"[^\W_]+", plain, re.UNICODE)
    raw = re.findall(r"[^\W_]+", low, re.UNICODE)
    scores = {language: 0 for language in SUPPORTED_LANGUAGES}

    for language, words in STOPWORDS.items():
        for token in tokens:
            if token in words:
                scores[language] += 1 if token in SHARED_WORDS else 2

    # Orthographic features are independent of the tokenizer.
    if "¿" in text or "¡" in text:
        scores["es"] += 6
    if "ñ" in low:
        scores["es"] += 3
    if "ã" in low or "õ" in low:
        scores["pt"] += 4
    if "ç" in low:
        scores["pt"] += 1
    if "œ" in low:
        scores["fr"] += 4
    if "ß" in low:
        scores["de"] += 5
    if any(character in low for character in "äöü"):
        scores["de"] += 2
    if re.search(r"\b(?:l|d|qu|c|j|n|s|t)'", low):
        scores["fr"] += 2
    if any("nh" in token or "lh" in token for token in tokens):
        scores["pt"] += 2
    if any(token.endswith("cao") or token.endswith("coes") for token in tokens):
        scores["pt"] += 3
    if any(token.endswith("cion") or token.endswith("ciones") for token in tokens):
        scores["es"] += 2
    if any(token.endswith("zione") or token.endswith("zioni") for token in tokens):
        scores["it"] += 2
    if any(token.endswith("ung") for token in tokens):
        scores["de"] += 1
    if "gli" in tokens:
        scores["it"] += 2
    if "che" in tokens:
        scores["it"] += 1
    for language, words in ACCENTED_WORDS.items():
        for token in raw:
            if token in words:
                scores[language] += 2

    best = max(scores.values())
    if best < 2:
        return DEFAULT_LANGUAGE
    leaders = [language for language, score in scores.items() if score == best]
    # Spanish wins a tie: a false positive would add an unnecessary model call,
    # while a false negative would keep the untranslated query.
    return DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in leaders else sorted(leaders)[0]


TRANSLATION_PROMPT = """Traduce al español la pregunta del usuario.
Devuelve únicamente la traducción, sin comillas, sin explicación y sin responderla.
Conserva tal cual los nombres propios, siglas, modelos, versiones, cifras y unidades.
No añadas requisitos, pasos, ejemplos ni datos que no estén en la pregunta.
Si la pregunta ya está en español, devuélvela sin cambios. Máximo 1000 caracteres."""
TRANSLATION_MAX_TOKENS = 600
TRANSLATION_TIMEOUT_SECONDS = 8.0


def clean_translation(value):
    """Reject empty, runaway or refusal outputs instead of searching with them."""
    if not isinstance(value, str):
        raise ValueError("invalid_translation")
    text = value.strip()
    if len(text) >= 2 and text[0] in _QUOTES and text[-1] in _QUOTES:
        text = text[1:-1].strip()
    text = re.sub(r"(?i)^(?:traducción|traduccion|translation)\s*:\s*", "", text).strip()
    if not text or len(text) > 1000 or _TRANSLATION_REFUSAL.search(text):
        raise ValueError("invalid_translation")
    return text


async def translate_to_spanish(clients, question, timeout=None):
    """One short, deterministic model call. Raises if it fails or times out."""
    LLM_PHASE.set("translation")
    timeout = timeout or TRANSLATION_TIMEOUT_SECONDS
    call = clients.generate(
        [{"role": "system", "content": TRANSLATION_PROMPT},
         {"role": "user", "content": question}],
        max_tokens=TRANSLATION_MAX_TOKENS, reasoning_effort="disabled")
    try:
        value = await asyncio.wait_for(call, timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise TimeoutError("translation_timeout") from exc
    return clean_translation(value)
