r"""Pure content-loss audit for the PDF conversion (metric version 1).

This module separates REAL content loss from measurement artifacts when the
production PDF conversion (:mod:`bibliotecario.converters`) is compared with
the page's own text. It never converts, never writes and never imports
production converters: it consumes a PyMuPDF page plus the final per-page
markdown that ``convert()`` produced and classifies every text line whose word
sequence is absent from that markdown.

Normalization (shared by both sides of every comparison):

- Unicode NFKC (ligatures such as U+FB01 become ``fi``, like pymupdf4llm's
  markdown output);
- a hyphen + line break inside a word is joined (``pre-\\ntrain`` ->
  ``pretrain``), letter-letter only;
- whitespace collapsed and casefolded.

Tokens come in two flavours:

- word tokens: ``[^\W_]+`` on the normalized text (same pattern as
  ``converters.WORD``); hyphenated compounds in the markdown additionally
  contribute their joined form (``pre-training`` -> ``pretraining``);
- symbol tokens: each character of a curated set of mathematical glyphs
  (``∑ √ ≤ ≥ ∈ ∂ − ± × ÷ · ° ′ arrows …``) is its own token, because
  ``WORD`` is blind to them.

Lines are audited in two shapes:

- *raw lines*, exactly ``page.get_text("dict")`` produces them: hyphen
  fragments live here (``representa-`` and ``tion`` are separate raw lines);
- *logical lines*: raw lines joined across a hyphen that breaks a word (the
  reader's line).

Categories, each with a line count, a token count and sample evidence:

===================  ==========================================================
``duplicate_layer``  raw line present in the markdown (>= 1 occurrence) yet
                     repeated across >= 2 distinct blocks of the page (e.g.
                     the arXiv side notice): ``place()`` deduplicates, so no
                     copy is recoverable and the coverage multiset counts the
                     rest as missing. ``words`` counts only occurrences the
                     markdown lacks.
``hyphen_fragment``  fragment joins on raw lines: the fragments are absent
                     from the markdown word multiset but their joined word is
                     present (``representa-`` + ``tion`` -> ``representation``).
                     ``lines`` counts joins, ``words`` counts missing
                     fragment tokens.
``reflow``           logical line whose sequence is absent but whose word
                     multiset is >= 0.8 present (same words, different line
                     breaks or sub/superscript tokenization).
``figure_label``     logical line inside a drawing/image region of the page
                     (table cells included), or of <= 3 tokens without
                     sentence punctuation.
``non_text_glyph``   logical line with math symbols and no word token of >= 2
                     characters.
``real_equation``    logical line with math symbols where >= 50 % of its
                     combined word+symbol tokens are absent from the markdown.
``real_prose``       logical line of >= 4 word tokens whose multiset overlap
                     is < 0.8.
``real_short``       residual: 1-3 tokens with sentence punctuation genuinely
                     absent.
``coverage_residual``  page-multiset surplus the line-level categories do not
                     attribute (no single line is missing): word occurrences
                     the page repeats — usually table cells — whose markdown
                     rendering keeps fewer copies. Not line-based: ``lines``
                     is always 0 and the evidence lists the surplus tokens.
===================  ==========================================================

A logical line whose missing tokens are all fragment-explainable (the markdown
holds the same word as split fragments) is not loss at all and is skipped.
Priority within the sequence-absent classification: ``figure_label``,
``non_text_glyph``, ``real_equation``, ``reflow``, ``real_prose``,
``real_short``.

The verdict per file reports real prose loss in words, real equation loss in
lines, the artifact breakdown per category and the math glyphs present on the
pages but absent from the markdown.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

METRIC_VERSION = "pdf-content-audit/1"

WORD = re.compile(r"[^\W_]+")
LETTER = r"[^\W\d_]"
# Hyphenated word break in flowing text: a letter, a hyphen, a line break, a letter.
HYPHEN_BREAK = re.compile(rf"({LETTER})-\n({LETTER})")
# Mid-line hyphen between letters (markdown compounds like pre-training).
HYPHEN_MID = re.compile(rf"(?<={LETTER})-(?={LETTER})")
# Mid-line hyphenated compounds in the markdown (``pre-training``). A hyphen at
# a line end is NOT a compound: those are fragments handled by MD_FRAGMENT_JOIN.
COMPOUND = re.compile(rf"{LETTER}+(?:-{LETTER}+)+")
# Curated math glyphs that WORD cannot see (after NFKC). ASCII math characters
# (= + < >) are excluded on purpose: they are also ordinary punctuation.
SYMBOL = re.compile(
    "[\u00b0\u00b1\u00b7\u00d7\u00f7"        # ° ± · × ÷
    "\u2032-\u2037"                          # ′ ″ ‴ ‵ ‶ ‷
    "\u2100-\u214f"                          # letterlike symbols (ℓ ℤ ℜ …)
    "\u2190-\u21ff"                          # arrows
    "\u2200-\u22ff"                          # mathematical operators
    "\u2308-\u230b\u27e8\u27e9"              # ⌈⌉⌊⌋ ⟨⟩
    "\u2a00-\u2aff]"                         # supplemental operators
)
SENTENCE_END = re.compile(r"[.!?][\"')\]]?$")
# Operator-grade glyphs for ``equation_lines_total``: units and typographic
# marks (° ′ ″ letterlike) are glyphs, not equations.
OPERATOR = re.compile(
    "[\u00b1\u00b7\u00d7\u00f7"             # ± · × ÷
    "\u2190-\u21ff"                          # arrows
    "\u2200-\u22ff"                          # mathematical operators
    "\u2308-\u230b\u27e8\u27e9"              # ⌈⌉⌊⌋ ⟨⟩
    "\u2a00-\u2aff]"                         # supplemental operators
)
DUPLICATE_MAX_SAMPLES = 3

CATEGORY_ORDER = ("duplicate_layer", "hyphen_fragment", "reflow", "figure_label",
                  "non_text_glyph", "real_equation", "real_prose", "real_short",
                  "coverage_residual")


def normalize_text(text: str) -> str:
    """NFKC, join hyphenated line breaks, collapse whitespace, casefold."""
    text = unicodedata.normalize("NFKC", text)
    text = HYPHEN_BREAK.sub(r"\1\2", text.replace("\r\n", "\n").replace("\r", "\n"))
    return re.sub(r"\s+", " ", text).casefold().strip()


def word_tokens(text: str) -> Counter:
    """Word multiset of ``text`` under the audit normalization."""
    return Counter(WORD.findall(normalize_text(text)))


def symbol_tokens(text: str) -> Counter:
    """Math-glyph multiset of ``text`` under the audit normalization."""
    return Counter(SYMBOL.findall(normalize_text(text)))


def operator_lines(lines) -> int:
    """Number of the given text lines carrying at least one operator glyph."""
    return sum(1 for text in lines if OPERATOR.search(normalize_text(text)))


def _joined_compound(compound: str) -> str:
    return compound.replace("-", "").replace("\n", "").replace(" ", "")


def _compounds(markdown: str) -> set:
    """De-hyphenated forms of the compounds the markdown text contains."""
    flat = unicodedata.normalize("NFKC", markdown.replace("\r\n", "\n").replace("\r", "\n"))
    return {_joined_compound(compound) for compound in COMPOUND.findall(flat.casefold())
            if _joined_compound(compound)}


def _md_flat(markdown: str) -> str:
    """NFKC + newline normalization of markdown, without joining hyphen breaks.

    The markdown side keeps production tokenization: a hyphen at the end of a
    recovered line stays a fragment (``cono-`` / ``cido``), so the audit sees
    the same multiset the coverage metric sees.
    """
    return unicodedata.normalize("NFKC", markdown.replace("\r\n", "\n").replace("\r", "\n"))


# Hyphenated fragments inside the markdown itself (recovered raw lines keep the
# break, optionally wrapped in emphasis markers).
MD_FRAGMENT_JOIN = re.compile(rf"({LETTER}+)-[ \t_*]{{0,3}}\n[ \t_*]{{0,3}}({LETTER}+)")


def markdown_words(markdown: str) -> Counter:
    """Markdown word multiset (production tokenization) + mid-line compound forms.

    ``pre-training`` contributes ``pre``/``training`` and the joined
    ``pretraining``; a hyphen at a line end stays a fragment, like production.
    """
    flat = _md_flat(markdown)
    words = Counter(WORD.findall(flat.casefold()))
    for compound in COMPOUND.findall(flat.casefold()):
        joined = _joined_compound(compound)
        if joined:
            words[joined] += 1
    return words


def markdown_fragment_compounds(markdown: str) -> dict:
    """Words the markdown itself holds as hyphen-split fragments (``cono-``/``cido``).

    Maps each joined form to the fragment evidence; used to attribute the part
    of the coverage gap caused by fragments the recovery left inside the
    markdown.
    """
    flat = _md_flat(markdown).casefold()
    compounds = {}
    for left, right in MD_FRAGMENT_JOIN.findall(flat):
        joined = left + right
        compounds.setdefault(joined, f"md:{left}+{right}={joined}")
    return compounds


def page_words(text: str) -> Counter:
    """Word multiset of raw page/markdown text under production-like tokenization.

    No hyphen-break joining (a fragment stays a fragment) and NFKC so both
    sides of the comparison see the same ligatures.
    """
    return Counter(WORD.findall(_md_flat(text).casefold()))


def _streams(markdown: str):
    """(primary, variant) word streams for contiguous-sequence checks.

    Link targets are not visible page text and the primary stream keeps
    production tokenization (no hyphen-break joining). The variant stream
    additionally joins mid-line hyphenated compounds so ``pretrain`` matches
    ``pre-training``.
    """
    flat = re.sub(r"\]\([^)]*\)", " ", _md_flat(markdown).casefold())
    primary = " " + " ".join(WORD.findall(flat)) + " "
    variant = " " + " ".join(WORD.findall(HYPHEN_MID.sub("", flat))) + " "
    return primary, variant


@dataclass
class RawLine:
    """One dict line of the page, unmodified."""

    text: str
    bbox: tuple
    words: Counter = field(default_factory=Counter)
    number: int = 0


@dataclass
class LogicalLine:
    """Raw lines joined across hyphenated breaks: the reader's line."""

    text: str
    bbox: tuple
    words: Counter
    first_raw: int
    last_raw: int
    joins: list = field(default_factory=list)


def _letter_hyphen_break(prev_text, next_text):
    """True when ``prev_text`` ends a word with a hyphen that ``next_text`` continues."""
    prev_text = prev_text.rstrip()
    head = next_text.lstrip()
    return (prev_text.endswith("-") and re.search(rf"{LETTER}-$", prev_text)
            and bool(head) and re.match(LETTER, head[:1]) is not None)


def _logical_lines(raw_lines):
    """Join raw lines across letter-hyphen line breaks (within and across blocks)."""
    lines, buf = [], None
    for raw in raw_lines:
        if buf is None:
            buf = [raw]
        elif _letter_hyphen_break(buf[-1].text, raw.text):
            buf.append(raw)
        else:
            lines.append(buf)
            buf = [raw]
    if buf:
        lines.append(buf)
    result = []
    for group in lines:
        text = group[0].text
        joins = []
        for raw in group[1:]:
            merged_head = text.rstrip()
            left = WORD.findall(normalize_text(merged_head))
            right = WORD.findall(normalize_text(raw.text.lstrip()))
            if left and right:
                joins.append((left[-1], right[0]))
            text = merged_head[:-1] + raw.text.lstrip()
        result.append(LogicalLine(text=text,
                                  bbox=(min(r.bbox[0] for r in group), min(r.bbox[1] for r in group),
                                        max(r.bbox[2] for r in group), max(r.bbox[3] for r in group)),
                                  words=word_tokens(text),
                                  first_raw=group[0].number, last_raw=group[-1].number,
                                  joins=joins))
    return result


def _in_regions(bbox, regions):
    """True when the line bbox lies (mostly) inside one drawing/image region."""
    area = max((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 1e-9)
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    for rect in regions:
        ix0, iy0 = max(bbox[0], rect[0]), max(bbox[1], rect[1])
        ix1, iy1 = min(bbox[2], rect[2]), min(bbox[3], rect[3])
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        if (ix1 - ix0) * (iy1 - iy0) >= 0.5 * area:
            return True
        if rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]:
            return True
    return False


def _line_regions(page, page_area):
    """Drawing/image regions of the page as (x0, y0, x1, y1) tuples.

    Regions covering ~the whole page (frames) are ignored.
    """
    regions = []
    try:
        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if rect is None or not rect.is_valid or rect.is_empty:
                continue
            if rect.get_area() < 0.9 * page_area:
                regions.append((rect.x0, rect.y0, rect.x1, rect.y1))
    except Exception:  # pragma: no cover - PyMuPDF drawing extraction is best effort
        pass
    try:
        for info in page.get_image_info():
            bbox = info.get("bbox")
            if bbox:
                regions.append(tuple(bbox))
    except Exception:  # pragma: no cover - PyMuPDF image info is best effort
        pass
    return regions


def _raw_page_lines(page):
    """All text lines of the page in document order, as RawLine items."""
    raw_lines = []
    try:
        layout = page.get_text("dict")
    except Exception:  # pragma: no cover - PyMuPDF extraction is best effort
        layout = {"blocks": []}
    for block in layout.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if not text.strip():
                continue
            raw_lines.append(RawLine(text=text, bbox=tuple(line["bbox"]), words=word_tokens(text),
                                     number=len(raw_lines)))
    return raw_lines


def _fragment_joins(raw_lines, ctx, page_number, evidence):
    """hyphen_fragment census on raw lines: joins whose word the markdown holds.

    A run of raw lines chained by hyphenated breaks is checked as a whole
    (``im-`` ``prove-`` ``ment`` -> ``improvement``) and, failing that, pair by
    pair. Only fragments absent from the markdown are counted.
    """
    joins = words = 0
    index = 0
    while index < len(raw_lines) - 1:
        if not _letter_hyphen_break(raw_lines[index].text, raw_lines[index + 1].text):
            index += 1
            continue
        end = index
        pairs = []
        while end < len(raw_lines) - 1 and _letter_hyphen_break(raw_lines[end].text, raw_lines[end + 1].text):
            left = WORD.findall(normalize_text(raw_lines[end].text))
            right = WORD.findall(normalize_text(raw_lines[end + 1].text))
            if left and right:
                pairs.append((left[-1], right[0]))
            end += 1
        chain = [pairs[0][0]] + [right for _, right in pairs]
        found = None
        joined = "".join(chain)
        missing = [frag for frag in chain if frag not in ctx["md_words"]]
        if joined in ctx["md_words"] and missing:
            found = (chain, joined)
        else:
            for (left, right) in pairs:
                pair_joined = left + right
                pair_missing = [frag for frag in (left, right) if frag not in ctx["md_words"]]
                if pair_joined in ctx["md_words"] and pair_missing:
                    found = ([left, right], pair_joined)
                    break
        if found:
            chain, joined = found
            missing = [frag for frag in chain if frag not in ctx["md_words"]]
            joins += 1
            words += len(missing)
            if len(evidence["hyphen_fragment"]) < DUPLICATE_MAX_SAMPLES:
                evidence["hyphen_fragment"].append(
                    {"page": page_number + 1, "join": "+".join(chain) + "=" + joined,
                     "missing_fragments": missing})
        index = end
    return joins, words


def _joinables(line: LogicalLine, ctx, overlap: float) -> dict:
    """Missing tokens of the line that the markdown holds in another shape.

    Evidences, strongest first: the markdown itself holds the word as hyphen-
    split fragments (``cono-`` / ``cido``); the token was formed by joining two
    fragments at a line break and the markdown holds both fragments; the token
    joins exactly with the next raw line's first token (unmerged fragment); or
    the line is mostly present (overlap >= 0.8) and the token is a proper
    prefix/suffix of a markdown compound's joined form.
    """
    missing = line.words - ctx["md_words"]
    if not missing:
        return {}
    joins = {}
    for token in sorted(set(missing)):
        fragment_evidence = ctx["md_fragment_compounds"].get(token)
        if fragment_evidence:
            joins[token] = fragment_evidence
    for left, right in line.joins:
        joined = left + right
        if (joined in missing and joined not in joins
                and left in ctx["md_words"] and right in ctx["md_words"]):
            joins[joined] = f"{left}+{right}={joined}"
    raw = ctx["raw_lines"]
    for token in sorted(set(missing) - set(joins)):
        if line.last_raw + 1 < len(raw):
            nxt = WORD.findall(normalize_text(raw[line.last_raw + 1].text))
            end_token = WORD.findall(normalize_text(line.text))
            if end_token and nxt and end_token[-1] == token and token + nxt[0] in ctx["md_words"]:
                joins[token] = f"{token}+{nxt[0]}={token + nxt[0]}"
                continue
        if overlap >= 0.8:
            for candidate in sorted(ctx["md_compounds"]):
                if (len(candidate) > len(token) >= 3
                        and (candidate.startswith(token) or candidate.endswith(token))):
                    joins[token] = f"{token}~{candidate}"
                    break
    return joins


def _classify(line: LogicalLine, ctx, in_region: bool, missing, overlap: float) -> tuple | None:
    """Category of a logical line whose sequence is absent from the markdown.

    ``missing`` already excludes fragment-explainable tokens. Returns
    ``(category, detail)`` with the evidence payload, or ``None`` when nothing
    is actually lost (a symbol-only line whose glyphs the markdown has).
    """
    symbols = symbol_tokens(line.text)
    missing_symbols = symbols - ctx["md_symbols"]
    if symbols and not any(len(token) >= 2 for token in line.words):
        if missing_symbols:
            return "non_text_glyph", {"missing_symbols": dict(missing_symbols)}
        return None  # the markdown holds every glyph: nothing is lost
    total = sum(line.words.values()) + sum(symbols.values())
    missing_total = sum(missing.values()) + sum(missing_symbols.values())

    if in_region or (len(line.words) <= 3 and not SENTENCE_END.search(line.text.strip())):
        return "figure_label", {}
    if symbols and total and missing_total / total >= 0.5:
        return "real_equation", {"missing_symbols": dict(missing_symbols)}
    if overlap >= 0.8:
        return "reflow", {}
    if len(line.words) >= 4:
        return "real_prose", {}
    return "real_short", {}


def audit_page(page, page_markdown: str) -> dict:
    """Census of one page: artifacts and real loss against ``page_markdown``.

    ``page`` is any object exposing the PyMuPDF page API used here
    (``get_text("dict")``, ``get_drawings()``, ``get_image_info()``, ``rect``).
    """
    page_area = page.rect.get_area() if hasattr(page, "rect") else 1e18
    regions = _line_regions(page, page_area)
    raw_lines = _raw_page_lines(page)
    logical = _logical_lines(raw_lines)
    md_primary, md_variant = _streams(page_markdown)
    md_words = markdown_words(page_markdown)
    ctx = {"md_words": md_words, "md_symbols": symbol_tokens(page_markdown),
           "md_compounds": _compounds(page_markdown),
           "md_fragment_compounds": markdown_fragment_compounds(page_markdown),
           "raw_lines": raw_lines}
    counts, words = Counter(), Counter()
    dup_covered = Counter()
    pass2_covered = Counter()
    evidence = {category: [] for category in CATEGORY_ORDER}

    # duplicate_layer: content the markdown has (>= 1) repeated in distinct blocks.
    block_of, start = {}, 0
    try:
        layout = page.get_text("dict")
    except Exception:  # pragma: no cover - PyMuPDF extraction is best effort
        layout = {"blocks": []}
    for block in layout.get("blocks", []):
        if block.get("type") != 0:
            continue
        width = sum(1 for line in block.get("lines", [])
                    if "".join(span.get("text", "") for span in line.get("spans", [])).strip())
        for number in range(start, start + width):
            block_of[number] = block.get("number", start)
        start += width
    content_blocks, content_lines = Counter(), {}
    for raw in raw_lines:
        key = normalize_text(raw.text)
        if not key:
            continue
        content_blocks[key] += 1
        content_lines.setdefault(key, []).append(raw)
    for key, occurrences in content_blocks.items():
        if occurrences < 2:
            continue
        md_occurrences = md_primary.count(f" {' '.join(WORD.findall(key))} ")
        if md_occurrences < 1:
            continue
        involved = content_lines[key]
        counts["duplicate_layer"] += len(involved)
        lost = max(0, occurrences - md_occurrences)
        words["duplicate_layer"] += lost * len(WORD.findall(key))
        for token, count in Counter(WORD.findall(key)).items():
            dup_covered[token] += lost * count
        if len(evidence["duplicate_layer"]) < DUPLICATE_MAX_SAMPLES:
            evidence["duplicate_layer"].append(
                {"page": page.number + 1, "text": key[:120], "pdf_occurrences": occurrences,
                 "markdown_occurrences": md_occurrences,
                 "blocks": len({block_of[r.number] for r in involved})})

    # hyphen_fragment on raw lines.
    joins, fragment_words = _fragment_joins(raw_lines, ctx, page.number, evidence)
    counts["hyphen_fragment"] += joins
    words["hyphen_fragment"] += fragment_words

    # Sequence-absent logical lines, classified by priority.
    for line in logical:
        seq = " " + " ".join(WORD.findall(normalize_text(line.text))) + " "
        has_symbols = bool(SYMBOL.search(normalize_text(line.text)))
        if (not line.words and not has_symbols) or seq in md_primary or seq in md_variant:
            continue
        missing = line.words - ctx["md_words"]
        overlap = sum((line.words & ctx["md_words"]).values()) / sum(line.words.values()) if line.words else 1.0
        if missing:
            joins = _joinables(line, ctx, overlap)
            effective = missing - Counter({token: 1 for token in joins})
            if not effective:
                # The markdown holds every missing token in another shape. Only
                # the md-internal fragment joins mark a real coverage gap (the
                # PDF word is joined, the markdown counts fragments).
                md_fragments = [token for token, mark in joins.items() if mark.startswith("md:")]
                if md_fragments:
                    counts["hyphen_fragment"] += 1
                    words["hyphen_fragment"] += len(md_fragments)
                    if len(evidence["hyphen_fragment"]) < DUPLICATE_MAX_SAMPLES:
                        evidence["hyphen_fragment"].append(
                            {"page": page.number + 1, "join": joins[md_fragments[0]],
                             "missing_fragments": sorted(md_fragments)})
                continue
            overlap = sum((line.words & (ctx["md_words"] + Counter({token: 1 for token in joins}))).values()) / sum(line.words.values())
        else:
            effective = missing
        in_region = bool(regions) and _in_regions(line.bbox, regions)
        category, detail = _classify(line, ctx, in_region, effective, overlap)
        if category is None:
            continue
        counts[category] += 1
        words[category] += sum(effective.values())
        pass2_covered.update(effective)
        if len(evidence[category]) < DUPLICATE_MAX_SAMPLES:
            item = {"page": page.number + 1, "text": normalize_text(line.text)[:120],
                    "words": sum(line.words.values())}
            item.update(detail)
            if effective:
                item["missing"] = sorted(effective)
            evidence[category].append(item)

    # coverage_residual: page-multiset surplus the line-level categories do not
    # attribute. No line is missing: the page repeats words (table cells) whose
    # markdown rendering keeps fewer copies.
    try:
        source_words = page_words(page.get_text())
    except Exception:  # pragma: no cover - PyMuPDF extraction is best effort
        source_words = Counter()
    deficit = source_words - md_words
    explained = sum(words[category] for category in CATEGORY_ORDER if category != "coverage_residual")
    residual = max(0, sum(deficit.values()) - explained)
    counts["coverage_residual"] = 0
    words["coverage_residual"] = residual
    for token in sorted(deficit):
        left = deficit[token] - dup_covered[token] - pass2_covered[token]
        if left > 0 and len(evidence["coverage_residual"]) < DUPLICATE_MAX_SAMPLES:
            evidence["coverage_residual"].append(
                {"page": page.number + 1, "token": token, "surplus": left})
    result = {"page": page.number + 1, "lines": len(raw_lines), "logical_lines": len(logical),
              "regions": len(regions), "word_gap": sum(deficit.values())}
    for category in CATEGORY_ORDER:
        result[category] = {"lines": counts[category], "words": words[category]}
    result["_evidence"] = evidence
    return result


def audit_document(document, page_markdowns: dict, filename: str = "") -> dict:
    """Verdict for one file: real loss vs artifacts, with sample evidence.

    ``document`` is an open PyMuPDF document (or any iterable of pages exposing
    ``number`` and the extraction API) and ``page_markdowns`` maps
    ``page.number`` to the final per-page markdown that ``convert()`` produced.
    """
    pages = []
    for page in document:
        if page.number in page_markdowns:
            pages.append(audit_page(page, page_markdowns[page.number]))
    verdict = {
        "metric_version": METRIC_VERSION,
        "file": filename,
        "pages": len(pages),
        "lines": sum(item["lines"] for item in pages),
        "logical_lines": sum(item["logical_lines"] for item in pages),
    }
    for category in CATEGORY_ORDER:
        verdict[category] = {
            "lines": sum(item[category]["lines"] for item in pages),
            "words": sum(item[category]["words"] for item in pages),
        }
    with_text = [page for page in document if page.number in page_markdowns]
    missing_symbols = Counter()
    for page in with_text:
        missing_symbols += symbol_tokens(page.get_text()) - symbol_tokens(page_markdowns[page.number])
    verdict["missing_symbols"] = {
        "occurrences": sum(missing_symbols.values()),
        "glyphs": {glyph: count for glyph, count in sorted(missing_symbols.items())},
    }
    verdict["equation_lines_total"] = operator_lines(
        raw.text for page in with_text for raw in _raw_page_lines(page))
    verdict["per_page"] = [{key: value for key, value in item.items() if not key.startswith("_")}
                           for item in pages]
    verdict["samples"] = {}
    for category in CATEGORY_ORDER:
        items = [sample for item in pages for sample in item["_evidence"][category]]
        verdict["samples"][category] = items[:DUPLICATE_MAX_SAMPLES]
    return verdict
