"""Marker-only emphasis cleanup of math lines in the PDF conversion.

The legacy converter (``pymupdf4llm.to_markdown``) renders every span with the
markdown emphasis its font flags suggest. Mathematical fonts (Computer Modern
CMMI/CMSY/CMEX/CMR, MSAM/MSBM, STIX) surface as italic/bold/strikethrough
spans, so equation lines come out wrapped in ``_..._``, ``**...**`` and
``~~...~~``: ``Attention( _Q, K, V_ ) = softmax( _[QK]_ ~~_V_~~ _[T]_`` or
``_lrate_ = _d_ _[-]_ model [0] _[.]_ [5]``. The markers wrap glyph runs —
they never add content — but they present equations to chunking, retrieval and
the audit as if italics were words around an ``=`` sign.

This module removes ONLY emphasis markers, on lines that are clearly
mathematical, keeping every other character and the order:

- a line qualifies when, outside markdown link targets, it carries an ``=``
  operator or one of the curated mathematical glyphs (∑ √ ≤ ≥ ∈ ∂ ∫ × · − ±,
  arrows, letterlike symbols, the big brackets). Tables, headings, list
  bullets, fenced code and indented blocks never qualify: their emphasis is
  data (bold table values) or structure, and prose references wrapped in
  ``_..._`` live there. Link targets (``](https://...)``) are invisible to the
  predicate — a URL query string's ``=`` is not mathematics;
- a qualifying line OPENS a math block when it is strong mathematics — an
  ``=`` operator or a math glyph other than the middot (wiki markdown also
  uses a leading ``·`` as a bullet artefact): the lines that follow it —
  across the blank lines that pymupdf4llm leaves between the fragments of a
  displayed formula in a two-column PDF — are continuation lines and are
  cleaned too when they are bare math fragments (``_dk_``, ``) _V_ (1)``,
  ``_[ K]_ _i_``).
  A continuation line qualifies only when every emphasis pair on it is a math
  fragment AND everything outside the pairs is math shell (digits, brackets,
  plain operators, math glyphs, whitespace) with no sentence punctuation and
  no prose words; any other non-blank line — prose continuation, table row,
  heading, bullet, code — closes the block and keeps its emphasis. Blank
  lines never close a block: they are the vertical gaps inside a formula;
- a marker pair is removed only when its content looks like a math fragment:
  glyphs, brackets, digits, comma-separated short symbols (``Q, K, V``),
  single identifiers (``lrate``, ``Pdrop``, ``softmax``). A markdown link, a
  several-word prose title (``York Times``), an acronym (``BERTBASE``) and a
  bold label (``**Encoder:**``) keep their emphasis;
- the alphanumeric token sequence of a cleaned page must be identical to the
  original: markers can disappear but no token may merge, split or move. A
  page whose cleanup breaks the invariant is reverted whole.

The cleaning is deliberately blind to the page: it sees the converted chunk
text only, so it runs for every PDF layout strategy and costs nothing beyond
a few regex passes over lines that carry mathematics.
"""
from __future__ import annotations

import re

WORD = re.compile(r"[^\W_]+")

# Curated mathematical glyphs that make a line a math stretch: comparison and
# set operators, big operators, the root/partial/integral signs, multiplication
# and minus, arrows, letterlike number-set symbols, derivative primes and the
# tall brackets. ASCII + < > / are excluded on purpose: prose and URLs use them.
MATH_GLYPHS = ("\u00b1\u00d7\u00f7\u00b7\u2212"                       # ± × ÷ · −
               "\u2032\u2033\u2034"                                    # ′ ″ ‴
               "\u203e\u2044"                                          # ‾ ⁄
               "\u2100-\u214f"                                         # ℓ ℤ ℝ ℚ ℕ ℑ…
               "\u2190-\u21ff"                                        # arrows
               "\u2200-\u22ff"                                        # ∀ ∂ ∃ ∈ ∑ √ ≤ ≥ ≈ ≠ ∫…
               "\u2308-\u230b"                                        # ⌈ ⌉ ⌊ ⌋
               "\u27e8\u27e9"                                          # ⟨ ⟩
               "\u2a00-\u2aff"                                        # ⨁ ⨂ …
               )
MATH_GLYPH = re.compile(f"[{MATH_GLYPHS}]")
# A bare '=' operator set off by whitespace (``N = 6``), not '==', not the ':='
# of prose, not a URL fragment like 'apellido=Bakalar', not an arrow of signs.
EQUALS = re.compile(r"(?<!\S)=(?![=>])")

TABLE_LINE = re.compile(r"^\s*\|")
HEADING_LINE = re.compile(r"^\s*#{1,6}\s")
BULLET_LINE = re.compile(r"^\s*([-*+]|\d+[.)])\s")
INDENTED = re.compile(r"^\s{4,}")

LINK_TARGET = re.compile(r"\]\([^)]*\)")
STRIKEOUT = re.compile(r"(?<![\w*~])~~([^~\n]+)~~(?![\w*~])")
BOLD = re.compile(r"(?<![\w*~])\*\*([^*\n]+)\*\*(?![\w*~])")
ITALIC = re.compile(r"(?<![\w])_([^_\n]+)_(?![\w])")
MARK_CHARS = re.compile(r"[_*~]")

# Characters allowed OUTSIDE emphasis pairs on a math-continuation line:
# whitespace, digits, brackets/braces/parens/angles, plain operators and the
# curated math glyphs. Anything else — letters, sentence punctuation
# (.,;:!?), quotes, @, &, unpaired _ — means prose and closes the block.
CONT_SHELL = re.compile(f"[^\\s\\d\\[\\]{{}}()<>+\\-*/^%~=*~{MATH_GLYPHS}]")


def _words(text: str) -> list:
    return re.findall(r"[^\W\d_]+", text, re.UNICODE)


def _is_math_line(line: str) -> bool:
    """True when the line is clearly mathematical: an '=' operator or a math
    glyph outside link targets, and none of the structural markdown shapes
    (table, heading, bullet, fenced/indented code) whose emphasis is data."""
    if INDENTED.match(line) or line.lstrip().startswith("```"):
        return False
    stripped = line.strip()
    if not stripped or TABLE_LINE.match(stripped) or HEADING_LINE.match(stripped) \
            or BULLET_LINE.match(stripped):
        return False
    probe = LINK_TARGET.sub(" ", stripped)
    return bool(EQUALS.search(probe) or MATH_GLYPH.search(probe))


def _is_math_fragment(kind: str, content: str) -> bool:
    """True when the content between two emphasis markers looks like a math
    fragment rather than prose. ``kind`` is ``strike``, ``bold`` or ``italic``."""
    body = content.strip()
    if not body:
        return False
    if "](" in body:  # a markdown link: references and citations, never math
        return False
    if kind == "strike":
        # Struck glyphs are symbols (``~~_V_~~``); struck punctuation or bare
        # digits are wiki-reference artefacts, not mathematics.
        return bool(re.search(rf"[^\W\d_]|[{MATH_GLYPHS}\[\]{{}}_]", body))
    if MATH_GLYPH.search(body) or re.search(r"[\[\]{}]", body):
        return True
    words = _words(body)
    if not words:  # symbols and digits only: _[.]_, _[-]_, _1_, **41.29**
        return True
    if kind == "bold":
        # Bold carries data values and prose labels alike; only short symbol
        # runs pass (**z**, **10**, **[18]**), every wordy one keeps its mark.
        return len(body) <= 24 and all(len(word) <= 2 for word in words)
    if len(words) == 1 and len(body) <= 8:
        word = words[0].strip(".,;:!?")
        return len(word) <= 2 or word.islower() \
            or (word[0].isupper() and word[1:].islower()) \
            or (word[0].isupper() and word[-1].islower())
        # z, n, lrate, Pdrop, QWi, xW, softmax — and never York Times
    if len(body) <= 24 and all(len(word) <= 2 for word in words):
        return True  # Q, K, V · zn · Ti
    return False


def tokens(markdown: str) -> list:
    """The alphanumeric token sequence a cleanup must preserve."""
    return WORD.findall(markdown)


def _opens_math_block(line: str) -> bool:
    """True when a math line is strong enough to OPEN a math block: an ``=``
    operator or a math glyph other than the middot. The middot is a math glyph
    for the line predicate (``pos/ 10000 · 2 π``), but wiki markdown also uses
    a leading ``·`` as a bullet artefact (``·El helio pertenece al bloque``);
    such a line still gets its own markers cleaned, yet it must not open a
    block or the bold shell letters below it (``**s**``, the block-s letter)
    would be eaten as if they were a formula fragment."""
    if not _is_math_line(line):
        return False
    probe = LINK_TARGET.sub(" ", line.strip())
    if EQUALS.search(probe):
        return True
    return bool(re.search(f"[{MATH_GLYPHS.replace(chr(0xB7), '')}]", probe))


def _clean_math_continuation(body: str):
    """Cleaned text for a line that follows a math line inside a math block.

    Returns ``None`` when the line must not be touched — prose, a table row, a
    heading, a bullet, indented/fenced code, a link line — which also closes
    the block. Otherwise returns the (possibly unchanged) text: the line is a
    bare math fragment only when every emphasis pair on it is a math fragment
    and everything outside the pairs is math shell with no sentence
    punctuation and no prose words.
    """
    stripped = body.strip()
    if not stripped or TABLE_LINE.match(stripped) or HEADING_LINE.match(stripped) \
            or BULLET_LINE.match(stripped) or INDENTED.match(body) \
            or stripped.startswith("```") or "](" in stripped:
        return None
    residual = body
    for pattern, kind in ((STRIKEOUT, "strike"), (BOLD, "bold"), (ITALIC, "italic")):
        for match in pattern.finditer(body):
            if not _is_math_fragment(kind, match.group(1)):
                return None
            residual = residual.replace(match.group(0), " ", 1)
    if CONT_SHELL.search(LINK_TARGET.sub(" ", residual)):
        return None
    cleaned = STRIKEOUT.sub(
        lambda match: match.group(1) if _is_math_fragment("strike", match.group(1)) else match.group(0), body)
    cleaned = ITALIC.sub(
        lambda match: match.group(1) if _is_math_fragment("italic", match.group(1)) else match.group(0), cleaned)
    cleaned = BOLD.sub(
        lambda match: match.group(1) if _is_math_fragment("bold", match.group(1)) else match.group(0), cleaned)
    return cleaned


def clean_math_emphasis(page_number: int, markdown: str) -> tuple:
    """Strip emphasis markers from clearly mathematical lines of one chunk.

    A math line (``=`` operator or math glyph) is cleaned directly; it also
    OPENS a math block whose continuation lines — across blank lines, the
    vertical gaps of a two-column formula — are cleaned when they are bare
    math fragments (``_dk_``, ``) _V_ (1)``). Any non-blank line that is not a
    math fragment (prose continuation, table, heading, bullet, code) closes
    the block and keeps its emphasis; blank lines never close one.

    Returns ``(markdown, cleaned_lines, reverted)``. Only ``_``, ``**`` and
    ``~~`` pairs whose content is a math fragment disappear; every other line
    is byte-identical. If the cleanup would alter the page's alphanumeric
    token sequence the page is reverted whole (``reverted`` is True).
    """
    lines = markdown.splitlines(keepends=True)
    in_fence = False
    in_block = False
    changed = 0
    for index, line in enumerate(lines):
        eol = line[len(line.rstrip("\r\n")):]
        body = line[:len(line) - len(eol)]
        if body.lstrip().startswith("```"):
            in_fence = not in_fence
            in_block = False
            continue
        if in_fence:
            continue
        if _is_math_line(body):
            cleaned = STRIKEOUT.sub(
                lambda match: match.group(1) if _is_math_fragment("strike", match.group(1)) else match.group(0), body)
            cleaned = ITALIC.sub(
                lambda match: match.group(1) if _is_math_fragment("italic", match.group(1)) else match.group(0), cleaned)
            cleaned = BOLD.sub(
                lambda match: match.group(1) if _is_math_fragment("bold", match.group(1)) else match.group(0), cleaned)
            if cleaned != body:
                lines[index] = cleaned + eol
                changed += 1
            in_block = _opens_math_block(body)
            continue
        if in_block:
            cleaned = _clean_math_continuation(body)
            if cleaned is not None:
                if cleaned != body:
                    lines[index] = cleaned + eol
                    changed += 1
                continue  # a bare math fragment keeps the block open
            if body.strip():
                in_block = False  # prose or structure: the block ends here
            # a blank line is a formula's vertical gap: the block stays open
    result = "".join(lines)
    if changed and tokens(markdown) != tokens(result):
        return markdown, 0, True  # revert: the invariant is absolute
    return result, changed, False
