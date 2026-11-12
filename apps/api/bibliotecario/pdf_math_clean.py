"""Formatting cleanup of math-heavy pages in the legacy PDF conversion.

The legacy converter (``pymupdf4llm.to_markdown``) renders every span with the
markdown emphasis its font flags suggest. Mathematical fonts (Computer Modern
CMMI/CMSY/CMEX/CMR, MSAM/MSBM, STIX) carry italic/bold/strikeout flags, so
equation lines come out wrapped in ``_..._``, ``**...**`` and ``~~...~~``
(``Attention( _Q, K, V_ ) = softmax( _[QK]_ ...)``). Two further artefacts hit
the same pages:

- the converter's span sanitiser joins horizontally overlapping spans of
  *different* dict lines (tall glyphs such as ``√`` bridge two wrapped lines)
  by plain text concatenation, gluing words (``dimension`` + ``query`` ->
  ``dimensionquery``);
- a global ``replace("-\\n", "")`` removes the hyphen of every line-end
  hyphenation, which is right for syllable breaks (``representa-`` +
  ``tion``) but destroys compound hyphens (``self-`` + ``attention`` ->
  ``selfattention``).

One pipeline cleans one page's markdown; it runs three stages under a single
token invariant:

- **Span rebuild** (``clean_math_lines``, needs the page object, runs first):
  the page's spans of ``page.get_text("dict")`` — extracted with the
  converter's own flags — are re-rendered the way the converter would, first
  with the glue kept and then with the glue split and the math markers
  stripped. A markdown line is replaced only when its normalized
  marker-stripped tokens match one unambiguous candidate run (the whole span
  group or the column part before/after the gutter), so unmatched or
  ambiguous lines stay untouched; prose spans keep their markers, and the
  junction of two different dict lines is rendered with a separator space
  instead of plain concatenation. This stage must run on the converter's own
  output: its candidate keys reproduce the converter's rendering *with* the
  markers, which the marker-only pass would otherwise have removed.
- **Marker-only pass** (``clean_math_emphasis``, text only, always on):
  every line the rebuild could not reproduce gets the historical cleanup — a
  clearly mathematical line (an ``=`` operator or a curated math glyph
  outside link targets, no table/heading/bullet/code shape) has its
  ``_``/``**``/``~~`` pairs removed when the wrapped content is a math
  fragment; the line also OPENS a math block whose continuation lines
  (across the blank gaps of a displayed formula) are cleaned when they are
  bare math fragments, with the middot kept as a bullet artefact (it cleans
  its own marks but never opens a block). Prose emphasis, wiki-reference
  strikes, author names and table values keep their markers.
- **Compound hyphens** (``compound_fixes``, needs the page object): the
  line-end hyphenations the converter destroyed are restored only with
  evidence — the hyphenated form used mid-line elsewhere in the document, or
  either fragment continuing a hyphen chain — and never for a wrapped year
  (``201-``/``8``) or a plain syllable break without evidence.

The page is checked against the token invariant: the alphanumeric token
sequence may only lose markers or split glued words (``tokens_preserved``).
A page that breaks it is reverted whole. Pages and documents without math
stretches cost one cheap ``get_fonts`` check (``page_may_have_math``) and are
returned untouched.

Diagnostics, all prefixed ``pdf_math_`` and emitted by
``bibliotecario.converters`` on the PDF branch:

- ``pdf_math_emphasis_page_N``: the page had emphasis markers removed (either
  stage);
- ``pdf_math_glue_space_page_N``: the span rebuild split glued words;
- ``pdf_math_compound_hyphen_page_N``: compound hyphens were restored;
- ``pdf_math_clean_reverted_page_N``: the page's cleanup broke the token
  invariant (or the marker-only pass broke its own) and was reverted whole.

The functions are pure: they take a page-like object (``get_textpage`` /
``get_text`` / ``get_fonts``) plus the converted markdown and return the
cleaned markdown plus diagnostics.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Shared token and math-line predicates (stage 1)
# ---------------------------------------------------------------------------
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
    """The alphanumeric token sequence a marker-only cleanup must preserve."""
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
    """Stage 1 — strip emphasis markers from clearly mathematical lines.

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


# ---------------------------------------------------------------------------
# Stage 2 — rebuild math/glue lines from the page spans
# ---------------------------------------------------------------------------
# Mathematical font families (subset prefixes suffice: subsetted fonts embed
# them, e.g. "VWQKZV+CMMI10").
MATH_FONT = re.compile(r"(CMMI|CMSY|CMEX|CMR|MSAM|MSBM|STIX|EUFM)", re.I)
# Operand glyphs that make an italic line a math stretch (the synthetic-PDF
# case, where equations use ordinary italic fonts). Parentheses are excluded
# on purpose: prose parentheses must never turn a line into a math line.
OPERAND_GLYPH = re.compile("[=\u00d7\u00f7\u00b1\u2212+\u2215<>\u2211\u221a\u222a\u2202\u2264\u2265\u222b\u2248\u2260\u2261\u00b7]")
# Markdown lines the span rebuild never touches.
LINK_LINE = re.compile(r"\]\([^)]*\)")

FLAG_SUPERSCRIPPED = 1
FLAG_ITALIC = 2
FLAG_MONO = 8
FLAG_BOLD = 16
CHAR_STRIKEOUT = 1  # char_flags bit

GROUP_TOLERANCE = 3.0  # vertical deviation that puts two spans on one line


@dataclass
class CleanSpan:
    """One ``extractDICT`` span, normalized for the rebuild."""

    text: str
    bbox: tuple
    flags: int
    char_flags: int
    size: float
    font: str
    line_no: int
    block_no: int

    @property
    def italic(self):
        return bool(self.flags & FLAG_ITALIC)

    @property
    def math_font(self):
        return MATH_FONT.search(self.font) is not None

    def is_math(self, line_has_operand: bool, mostly_italic: bool = False):
        """Math span: math font, or italic in a mostly-italic line with operands.

        The italic path exists for equations set in ordinary italic fonts (the
        synthetic-PDF case). Requiring the run to be mostly italic keeps prose
        italics (``_York Times_`` next to ``apellido=Bakalar``) out of it.
        """
        return self.math_font or (self.italic and line_has_operand and mostly_italic)


def _sanitize(line: list, keep_glue: bool):
    """pymupdf4llm's span sanitiser, optionally splitting cross-line glue.

    Spans are joined when they touch horizontally (within 10 % of the font
    size) and share flags. When two spans of *different* dict lines overlap
    horizontally they come from different wrapped fragments (tall glyphs or
    superscripts bridge the lines); the converter joins them anyway and glues
    words. With ``keep_glue=False`` the pair stays separate (rendered with a
    separator space) and the junction is recorded.
    """
    line = sorted(line, key=lambda span: span.bbox[0])
    junctions = []
    for i in range(len(line) - 1, 0, -1):
        s0, s1 = line[i - 1], line[i]
        delta = s1.size * 0.1
        if s0.bbox[2] + delta < s1.bbox[0]:
            continue
        if (s0.flags, s0.char_flags & ~2) != (s1.flags, s1.char_flags & ~2):
            continue
        overlaps = s1.bbox[0] < s0.bbox[2] - 0.2
        if overlaps and s0.line_no != s1.line_no and not keep_glue:
            junctions.append((s0, s1))
            continue
        if s0.text != s1.text or s0.bbox != s1.bbox:
            s0.text += s1.text
        s0.bbox = (min(s0.bbox[0], s1.bbox[0]), min(s0.bbox[1], s1.bbox[1]),
                   max(s0.bbox[2], s1.bbox[2]), max(s0.bbox[3], s1.bbox[3]))
        del line[i]
    return line, junctions


def _group_lines(spans: list, tolerance: float = GROUP_TOLERANCE):
    """Group spans into raw lines by vertical proximity (converter's rule)."""
    if not spans:
        return []
    ordered = sorted(spans, key=lambda span: span.bbox[3])
    groups, current = [], [ordered[0]]
    for span in ordered[1:]:
        previous = current[-1].bbox
        if (abs(span.bbox[3] - previous[3]) <= tolerance
                or abs(span.bbox[1] - previous[1]) <= tolerance):
            current.append(span)
        else:
            groups.append(current)
            current = [span]
    groups.append(current)
    return groups


def page_spans(page) -> list:
    """All text spans of the page, extracted with the converter's own flags.

    The converter builds its textpage with ``TEXT_MEDIABOX_CLIP`` and
    ``TEXT_COLLECT_STYLES`` only; superscript spans get their text wrapped in
    brackets and their bottom aligned with a neighbour, white and invisible
    text is skipped.
    """
    import pymupdf

    textpage = page.get_textpage(flags=pymupdf.TEXT_MEDIABOX_CLIP | pymupdf.TEXT_COLLECT_STYLES,
                                 clip=page.rect)
    blocks = textpage.extractDICT()["blocks"]
    spans = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line_no, line in enumerate(block.get("lines", [])):
            if abs(1 - line.get("dir", [1, 0])[0]) > 1e-3:
                continue
            for span_no, span in enumerate(line.get("spans", [])):
                text = span.get("text", "")
                if not text.strip():
                    continue
                if span.get("alpha", 255) == 0 and span.get("font") != "Type3":
                    continue
                bbox = tuple(span["bbox"])
                if span["flags"] & FLAG_SUPERSCRIPPED:
                    neighbour = 1 if span_no == 0 else span_no - 1
                    if len(line["spans"]) > neighbour:
                        bbox = (bbox[0], bbox[1], bbox[2], line["spans"][neighbour]["bbox"][3])
                    text = f"[{text}]"
                spans.append(CleanSpan(text=text, bbox=bbox, flags=span["flags"],
                                       char_flags=span.get("char_flags", 0),
                                       size=span.get("size", 0.0), font=span.get("font", ""),
                                       line_no=line_no, block_no=block.get("number", 0)))
    return spans


def _clone(span: CleanSpan) -> CleanSpan:
    return CleanSpan(text=span.text, bbox=span.bbox, flags=span.flags,
                     char_flags=span.char_flags, size=span.size, font=span.font,
                     line_no=span.line_no, block_no=span.block_no)


def render_span(span: CleanSpan, strip: bool) -> str:
    """The converter's per-span rendering, optionally without markers."""
    text = span.text.strip()
    if not text:
        return ""
    if not strip:
        if span.flags & FLAG_MONO:
            text = f"`{text}`"
        if span.flags & FLAG_BOLD or span.char_flags & 8:
            text = f"**{text}**"
        if span.flags & FLAG_ITALIC:
            text = f"_{text}_"
        if span.char_flags & CHAR_STRIKEOUT:
            text = f"~~{text}~~"
    return text + " "


def _finish_line(text: str) -> str:
    """The converter's per-line post-processing."""
    return text.rstrip().replace(" ,", ",").replace("  ", " ")


def render_line(spans: list, has_operand: bool, strip_math: bool = False,
                mostly_italic: bool = False) -> str:
    """Render joined spans the way the converter would.

    With ``strip_math`` the emphasis markers come off math spans only; prose
    bold/mono spans keep theirs.
    """
    parts = [render_span(span, strip=strip_math and span.is_math(has_operand, mostly_italic))
             for span in spans]
    return _finish_line("".join(parts))


def _strip_markers(text: str) -> str:
    return re.sub(r"_+|\*+|~+|`+", " ", text)


def _normalize(text: str) -> str:
    return " ".join(re.split(r"\s+", _strip_markers(text).casefold().strip()))


def _has_math(spans: list, has_operand: bool, mostly_italic: bool = False) -> bool:
    return any(span.is_math(has_operand, mostly_italic) for span in spans)


def _group_candidates(page) -> list:
    """(x-sorted pre-sanitize spans,) per raw-line group."""
    return [sorted(group, key=lambda span: span.bbox[0])
            for group in _group_lines(page_spans(page))]


def _run_has_junction(run: list) -> bool:
    """True when the run holds two overlapping spans of different dict lines."""
    for s0, s1 in zip(run, run[1:]):  # run is x-sorted
        delta = s1.size * 0.1
        if (s0.bbox[2] + delta >= s1.bbox[0] and s1.bbox[0] < s0.bbox[2] - 0.2
                and s0.line_no != s1.line_no
                and (s0.flags, s0.char_flags & ~2) == (s1.flags, s1.char_flags & ~2)):
            return True
    return False


def _run_operand(run: list) -> bool:
    """True when the run's own text carries an operand glyph."""
    return bool(OPERAND_GLYPH.search("".join(span.text for span in run)))


def _mostly_italic(run: list) -> bool:
    """True when at least half the run's spans are italic (an equation run)."""
    italic = sum(1 for span in run if span.italic)
    return italic * 2 >= len(run)


def _run_keys(pre: list, md_keys: set) -> dict:
    """Original renderings of candidate runs, keyed by normalized tokens.

    Candidate runs are the whole group, its prefixes and its suffixes (the
    converter clips per layout rectangle, so a converted line is the whole
    group or the column part before/after the gutter). Only runs containing a
    math span or a glue junction and matching a markdown line of the page are
    kept. The operand signal is per run: an italic span is math only when its
    own converted line carries operands and is mostly italic, never because a
    neighbour column or a prose infobox does.
    """
    count = len(pre)
    pre_operand = _run_operand(pre)
    if not (_has_math(pre, pre_operand, _mostly_italic(pre)) or _run_has_junction(pre)):
        return {}
    ranges = [(0, count)]
    ranges.extend((0, end) for end in range(1, count))
    ranges.extend((start, count) for start in range(1, count))
    results = {}
    for start, end in ranges:
        run = pre[start:end]
        has_operand = _run_operand(run)
        mostly_italic = _mostly_italic(run)
        if not (_has_math(run, has_operand, mostly_italic) or _run_has_junction(run)):
            continue
        original, _ = _sanitize([_clone(span) for span in run], keep_glue=True)
        key = _normalize(render_line(original, has_operand))
        if key and key in md_keys:
            fixed, _ = _sanitize([_clone(span) for span in run], keep_glue=False)
            results.setdefault(key, set()).add(
                render_line(fixed, has_operand, strip_math=True, mostly_italic=mostly_italic))
    return results


def _splits_tokens(old: str, new: str) -> bool:
    """True when the fixed line contains tokens the original had glued."""
    old_tokens = set(_normalize(old).split())
    return any(token not in old_tokens for token in _normalize(new).split())


def clean_math_lines(page, markdown: str, page_number: int):
    """Stage 2 — rebuild math/glue markdown lines from the page spans.

    A markdown line is replaced only when its normalized marker-stripped token
    sequence matches a candidate span run of the page, so unmatched or
    ambiguous lines stay untouched. The replacement renders the same run with
    the glue split and the math markers removed; the reading order of the
    spans is never rearranged (the interleaving a tall glyph produces is a
    pre-existing converter artefact, out of scope here).
    """
    md_keys = {_normalize(line) for line in markdown.splitlines() if line.strip()}
    if not md_keys:
        return markdown, [], False
    candidates = {}
    math_page = False
    for pre in _group_candidates(page):
        math_page = math_page or _has_math(pre, _run_operand(pre), _mostly_italic(pre))
        for key, values in _run_keys(pre, md_keys).items():
            candidates.setdefault(key, set()).update(values)
    if not math_page or not candidates:
        return markdown, [], math_page
    replacements = {key: sorted(values)[0] for key, values in candidates.items()
                    if len(values) == 1}
    out, cleaned, glued = [], 0, 0
    for md_line in markdown.splitlines():
        new_line = md_line
        if (md_line.strip() and not TABLE_LINE.match(md_line) and not HEADING_LINE.match(md_line)
                and not BULLET_LINE.match(md_line) and not LINK_LINE.search(md_line)):
            fixed = replacements.get(_normalize(md_line))
            if fixed is not None and fixed != md_line:
                new_line = fixed
                cleaned += 1
                if _splits_tokens(md_line, fixed):
                    glued += 1
        out.append(new_line)
    diagnostics = []
    if cleaned:
        diagnostics.append(f"pdf_math_emphasis_page_{page_number}")
    if glued:
        diagnostics.append(f"pdf_math_glue_space_page_{page_number}")
    trailing = "\n" if markdown.endswith("\n") else ""
    return "\n".join(out) + trailing, diagnostics, math_page


# ---------------------------------------------------------------------------
# Stage 3 — restore compound hyphens destroyed by the converter
# ---------------------------------------------------------------------------
def dict_line_pairs(page) -> list:
    """Consecutive dict-line pairs the converter's ``replace("-\\n", "")`` joins."""
    pairs = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        texts = ["".join(span.get("text", "") for span in line.get("spans", [])).strip()
                 for line in block.get("lines", [])]
        for current, following in zip(texts, texts[1:]):
            if current.endswith("-") and following[:1].isalnum():
                pairs.append((current, following))
    return pairs


def _first_segment(text: str) -> str:
    match = re.match(r"\S+", text)
    return match.group(0) if match else ""


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def compound_fixes(page, markdown: str, document_compounds: set, page_number: int) -> tuple:
    """Stage 3 — restore compound hyphens destroyed by ``replace("-\\n", "")``.

    A line-end hyphenation joins ``left`` and ``right`` without a separator.
    The hyphen is restored only with evidence that the join crossed a compound:
    the hyphenated form is already used mid-line elsewhere in the document, or
    either fragment continues a hyphen chain (``left-to-`` + ``right``). The
    joined form must contain a letter (``201-`` + ``8`` is a wrapped year, not
    a compound) and be absent from the page vocabulary; the replacement is
    word-bounded so it can never hit an unrelated occurrence.
    """
    page_words = set(WORD.findall(_nfkc(page.get_text()).casefold()))
    out = markdown
    restored = 0
    for current, following in dict_line_pairs(page):
        flat = _nfkc(current)
        left = re.search(r"([^\W_]+)-$", flat)
        if left is None:
            continue
        head = _first_segment(_nfkc(following))
        if not head:
            continue
        head_word = re.match(r"([^\W_]+)", head)
        if not head_word:
            continue
        joined = left.group(1) + head_word.group(1)
        restored_form = left.group(1) + "-" + head_word.group(1)
        if not re.search(r"[^\W\d_]", joined) or joined.casefold() in page_words:
            continue
        tail_word = flat.rstrip()[:-1].rsplit(" ", 1)[-1]
        chain = "-" in tail_word or "-" in head
        if _nfkc(restored_form).casefold() not in document_compounds and not chain:
            continue
        pattern = rf"(?<![^\W_]){re.escape(joined)}(?![^\W_])"
        out, count = re.subn(pattern, restored_form.replace("\\", "\\\\"), out)
        restored += count
    return out, ([f"pdf_math_compound_hyphen_page_{page_number}"] if restored else [])


def document_compound_vocabulary(markdowns: list) -> set:
    """Hyphenated compounds used mid-line anywhere in the converted document."""
    compounds = set()
    for markdown in markdowns:
        for line in markdown.splitlines():
            if TABLE_LINE.match(line):
                continue
            compounds.update(compound.casefold()
                             for compound in re.findall(r"[^\W_]+-[^\W_]+(?:-[^\W_]+)*", _nfkc(line)))
    return compounds


# ---------------------------------------------------------------------------
# Entry point — one pipeline, one token invariant
# ---------------------------------------------------------------------------
def tokens_in_order(markdown: str) -> list:
    """Alphanumeric token sequence of a markdown text (markers invisible)."""
    return WORD.findall(markdown)


def tokens_preserved(before: list, after: list) -> bool:
    """The token invariant: same sequence, markers aside, glued words split.

    Every ``before`` token must appear in ``after`` at the same position,
    except tokens the cleanup split into two or more consecutive ``after``
    tokens (``dimensionquery`` -> ``dimension query``). Merges, deletions,
    reorderings and insertions all fail.
    """
    i = j = 0
    while i < len(before) and j < len(after):
        if before[i] == after[j]:
            i, j = i + 1, j + 1
            continue
        matched = False
        for end in range(j + 2, len(after) + 1):
            joined = "".join(after[j:end])
            if joined == before[i]:
                i, j, matched = i + 1, end, True
                break
            if len(joined) >= len(before[i]):
                break
        if not matched:
            return False
    return i == len(before) and j == len(after)


def clean_page_markdown(page, markdown: str, page_number: int,
                        document_compounds: set | None = None):
    """Clean one page's markdown with the full pipeline under one invariant.

    Runs the span rebuild first (it must match the converter's own rendering,
    which carries the emphasis markers the marker-only pass would remove —
    without them the normalized keys stop matching), then the marker-only
    pass for every line the rebuild could not reproduce, then the compound
    restore. All three run under one token invariant.
    The result is checked against ``tokens_preserved``; a page that breaks it
    is reverted whole, and so is a page whose stage-1 pass broke the
    marker-only invariant and nothing else repaired it.

    Returns ``(markdown, diagnostics)``.
    """
    before = tokens_in_order(markdown)
    text = markdown
    diagnostics = []
    if page is not None:
        text, found, _ = clean_math_lines(page, text, page_number)
        diagnostics.extend(found)
    text, changed, stage1_reverted = clean_math_emphasis(page_number, text)
    if changed and text != markdown:
        diagnostics.append(f"pdf_math_emphasis_page_{page_number}")
    if page is not None and document_compounds is not None:
        text, found = compound_fixes(page, text, document_compounds, page_number)
        diagnostics.extend(found)
    if text != markdown and not tokens_preserved(before, tokens_in_order(text)):
        return markdown, [f"pdf_math_clean_reverted_page_{page_number}"]
    if text == markdown:
        if stage1_reverted:
            return markdown, [f"pdf_math_clean_reverted_page_{page_number}"]
        return markdown, []
    return text, list(dict.fromkeys(diagnostics))


def page_may_have_math(page) -> bool:
    """Cheap page gate: a math font is embedded (fast ``get_fonts`` check)."""
    try:
        return any(MATH_FONT.search(font[3] or font[4] or "") for font in page.get_fonts())
    except Exception:  # pragma: no cover - font listing is best effort
        return True
