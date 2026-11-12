#!/usr/bin/env python
"""Repeatable census of the math-formatting defects the PDF cleanup fixes.

For every PDF of the corpus it counts, on real markdown, the three defect
families that ``bibliotecario.pdf_math_clean`` targets:

- ``emphasis``: a math line (the module's own ``_is_math_line`` predicate:
  ``=`` operator or curated math glyph, no table/heading/bullet/code shape)
  carrying at least one emphasis pair whose content is a math fragment per
  ``_is_math_fragment``. These are exactly the pairs the marker-only and the
  span stages remove; prose emphasis on the same lines (author names, labels)
  is not a defect;
- ``junction_glued``: two spans of *different* dict lines that overlap
  horizontally and share flags (the converter's sanitiser concatenates them),
  whose fused token (last word of the left span + first word of the right
  span, both at least 2 letters) appears word-bounded in the markdown;
- ``compound_glued``: a dict-line pair ``word-`` + ``next`` whose joined form
  contains a letter, is absent from the page vocabulary and has document or
  chain evidence (the module's own ``compound_fixes`` rules); the joined form
  appears word-bounded in the markdown.

Three stages are censused so before/after is reproducible end to end:

- ``raw``: ``pymupdf4llm`` chunks + text recovery, no cleaning (the T0/T1-era
  pipeline; the historical 84/36 defect counts of attention/bert were
  measured here);
- ``text``: the production pipeline with the span-based stages disabled (the
  marker-only pass only, i.e. the pre-port ``main`` behaviour);
- ``full``: the production pipeline as wired (all three stages).

Usage::

    .venv/Scripts/python.exe scripts/h3/pdf_math_census.py \
        --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus \
        --files arxiv-attention-is-all-you-need-en.pdf,arxiv-bert-en.pdf \
        --json .orca-task/pdf-math-census.json \
        --detail arxiv-attention-is-all-you-need-en.pdf,arxiv-bert-en.pdf
"""
from __future__ import annotations

import os
import sys

# Same determinism as the conversion harness: the legacy layout analysis can
# depend on string-hash ordering, so pin the seed (single re-exec).
if "PYTHONHASHSEED" not in os.environ:
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, *sys.argv])

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if API_ROOT.is_dir() and str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import bibliotecario.converters as converters  # noqa: E402
import bibliotecario.pdf_math_clean as pmc  # noqa: E402

DEFAULT_CORPUS = Path("D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus")
SETTINGS = SimpleNamespace(normalized_max_bytes=20 * 1024 * 1024, extraction_max_pages=1000,
                           pdf_layout="legacy")
MARK_PAIRS = ((pmc.STRIKEOUT, "strike"), (pmc.BOLD, "bold"), (pmc.ITALIC, "italic"))


def _page_markdown(leading, chunk_text, trailing):
    """Exactly the per-page content assembled by converters.convert()."""
    return "\n\n".join(part for part in leading + [chunk_text.rstrip()] + trailing if part.strip()) + "\n\n"


def emphasis_defects(markdown: str) -> tuple:
    """(math lines with a math-fragment emphasis pair, such pairs)."""
    lines = pairs = 0
    for line in markdown.splitlines():
        if not line.strip() or not pmc._is_math_line(line):
            continue
        found = sum(1 for pattern, kind in MARK_PAIRS
                    for match in pattern.finditer(line)
                    if pmc._is_math_fragment(kind, match.group(1)))
        if found:
            lines += 1
            pairs += found
    return lines, pairs


def _word_bounded(token: str, markdown: str) -> int:
    return len(re.findall(rf"(?<![^\W_]){re.escape(token)}(?![^\W_])", markdown))


def junction_glued(page, markdown: str) -> list:
    """Sorted ``[fused_token, occurrences]`` from cross-line span junctions."""
    found = {}
    for group in pmc._group_candidates(page):
        for s0, s1 in zip(group, group[1:]):  # group is x-sorted
            delta = s1.size * 0.1
            if not (s0.bbox[2] + delta >= s1.bbox[0] and s1.bbox[0] < s0.bbox[2] - 0.2):
                continue
            if s0.line_no == s1.line_no:
                continue
            if (s0.flags, s0.char_flags & ~2) != (s1.flags, s1.char_flags & ~2):
                continue
            tail = pmc.WORD.findall(pmc._nfkc(s0.text))
            head = pmc.WORD.findall(pmc._nfkc(s1.text))
            if not tail or not head or len(tail[-1]) < 2 or len(head[0]) < 2:
                continue  # single-letter bridges are reading-order artefacts, not glue
            fused = tail[-1] + head[0]
            count = _word_bounded(fused, markdown)
            if count:
                found[fused] = max(found.get(fused, 0), count)
    return sorted(found.items())


def compound_glued(page, markdown: str, vocabulary: set) -> list:
    """Sorted ``[joined_form, occurrences]`` of evidenced compound joins."""
    found = {}
    page_words = set(pmc.WORD.findall(pmc._nfkc(page.get_text()).casefold()))
    for current, following in pmc.dict_line_pairs(page):
        flat = pmc._nfkc(current)
        left = re.search(r"([^\W_]+)-$", flat)
        if left is None:
            continue
        head = pmc._first_segment(pmc._nfkc(following))
        head_word = re.match(r"([^\W_]+)", head)
        if not head_word:
            continue
        joined = left.group(1) + head_word.group(1)
        restored_form = left.group(1) + "-" + head_word.group(1)
        if not re.search(r"[^\W\d_]", joined) or joined.casefold() in page_words:
            continue
        tail_word = flat.rstrip()[:-1].rsplit(" ", 1)[-1]
        chain = "-" in tail_word or "-" in head
        if pmc._nfkc(restored_form).casefold() not in vocabulary and not chain:
            continue
        count = _word_bounded(joined, markdown)
        if count:
            found[joined] = max(found.get(joined, 0), count)
    return sorted(found.items())


def census_markdown(page, markdown: str, vocabulary: set) -> dict:
    lines, pairs = emphasis_defects(markdown)
    return {
        "emphasis_defect_lines": lines,
        "emphasis_pairs": pairs,
        "junction_glued": junction_glued(page, markdown),
        "compound_glued": compound_glued(page, markdown, vocabulary),
    }


def _capture_convert(path, span_gate: bool = True):
    """convert() with per-page capture; ``span_gate=False`` disables the span
    and compound stages (the marker-only pass only)."""
    captured = {}
    raw_texts = []
    original_recover = converters.recover_pdf_page
    original_chunks = converters.pdf_markdown_chunks
    original_gate = pmc.page_may_have_math

    def capture_recover(page, markdown):
        leading, trailing, diagnostics = original_recover(page, markdown)
        captured[page.number] = {"leading": leading, "trailing": trailing, "markdown": markdown}
        return leading, trailing, diagnostics

    def capture_chunks(document, strategy="legacy"):
        chunks, used = original_chunks(document, strategy)
        raw_texts.extend(chunk["text"] for chunk in chunks)
        return chunks, used

    converters.recover_pdf_page = capture_recover
    converters.pdf_markdown_chunks = capture_chunks
    if not span_gate:
        pmc.page_may_have_math = lambda page: False
    try:
        started = time.perf_counter()
        converted = converters.convert(path, "pdf", SETTINGS, filename=path.name)
        seconds = time.perf_counter() - started
    finally:
        converters.recover_pdf_page = original_recover
        converters.pdf_markdown_chunks = original_chunks
        pmc.page_may_have_math = original_gate
    vocabulary = pmc.document_compound_vocabulary(raw_texts)
    final = {number: _page_markdown(info["leading"], info["markdown"], info["trailing"])
             for number, info in captured.items()}
    return converted, final, vocabulary, seconds


def _raw_stage(path):
    """pymupdf4llm + text recovery, no cleaning (the T0/T1-era pipeline)."""
    import pymupdf

    started = time.perf_counter()
    chunks_by_page, vocabulary = {}, set()
    with pymupdf.open(path) as document:
        chunks = converters._legacy_pdf_chunks(document)
        vocabulary = pmc.document_compound_vocabulary([chunk["text"] for chunk in chunks])
        for page, chunk in zip(document, chunks):
            leading, trailing, _ = converters.recover_pdf_page(page, chunk["text"])
            chunks_by_page[page.number] = _page_markdown(leading, chunk["text"], trailing)
        pages = {page.number: page for page in document}
        result = {number: census_markdown(pages[number], markdown, vocabulary)
                  for number, markdown in chunks_by_page.items()}
    return result, round(time.perf_counter() - started, 3)


def _capture_stage(path, span_gate: bool):
    converted, final, vocabulary, seconds = _capture_convert(path, span_gate)
    with __import__("pymupdf").open(path) as document:
        pages = {page.number: page for page in document}
        result = {number: census_markdown(pages[number], markdown, vocabulary)
                  for number, markdown in final.items() if number in pages}
    return result, round(seconds, 3)


def _totals(per_page: dict) -> dict:
    lines = pairs = 0
    junction, compound = {}, {}
    for census in per_page.values():
        lines += census["emphasis_defect_lines"]
        pairs += census["emphasis_pairs"]
        for token, count in census["junction_glued"]:
            junction[token] = max(junction.get(token, 0), count)
        for token, count in census["compound_glued"]:
            compound[token] = compound.get(token, 0) + count
    return {
        "emphasis_defect_lines": lines,
        "emphasis_pairs": pairs,
        "junction_glued": sorted(junction),
        "compound_glued": sorted(compound),
        "compound_glued_occurrences": sum(compound.values()),
    }


def select_files(corpus: Path, names: str):
    if not corpus.is_dir():
        raise SystemExit(f"corpus not found: {corpus}")
    if names:
        paths = [corpus / name.strip() for name in names.split(",") if name.strip()]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise SystemExit("missing PDFs: " + ", ".join(missing))
        return paths
    return sorted(path for path in corpus.iterdir() if path.suffix.lower() == ".pdf")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--files", default="", help="comma-separated PDF names inside --corpus")
    parser.add_argument("--stages", default="raw,text,full", help="subset of raw,text,full")
    parser.add_argument("--detail", default="", help="files to break down per page")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    stages = [stage.strip() for stage in args.stages.split(",") if stage.strip()]
    unknown = [stage for stage in stages if stage not in {"raw", "text", "full"}]
    if unknown:
        raise SystemExit(f"unknown stages: {', '.join(unknown)}")
    detail = {name.strip() for name in args.detail.split(",") if name.strip()}

    records = []
    for path in select_files(args.corpus, args.files):
        record = {"file": path.name, "stages": {}}
        if "raw" in stages:
            per_page, seconds = _raw_stage(path)
            record["stages"]["raw"] = {"totals": _totals(per_page), "secs": seconds}
            if path.name in detail:
                record["stages"]["raw"]["per_page"] = {
                    number + 1: census for number, census in sorted(per_page.items())}
        if "text" in stages:
            per_page, seconds = _capture_stage(path, span_gate=False)
            record["stages"]["text"] = {"totals": _totals(per_page), "secs": seconds}
            if path.name in detail:
                record["stages"]["text"]["per_page"] = {
                    number + 1: census for number, census in sorted(per_page.items())}
        if "full" in stages:
            per_page, seconds = _capture_stage(path, span_gate=True)
            record["stages"]["full"] = {"totals": _totals(per_page), "secs": seconds}
            if path.name in detail:
                record["stages"]["full"]["per_page"] = {
                    number + 1: census for number, census in sorted(per_page.items())}
        records.append(record)
        console = {"file": path.name,
                   **{stage: record["stages"][stage]["totals"] for stage in record["stages"]}}
        print(json.dumps(console, ensure_ascii=True), flush=True)

    payload = {"corpus": str(args.corpus),
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "python_hash_seed": os.environ.get("PYTHONHASHSEED", "unset"),
               "stages": stages, "files": records}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
