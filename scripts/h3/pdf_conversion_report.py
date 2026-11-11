#!/usr/bin/env python
"""Reproducible report of the repository's real PDF conversion.

Per PDF it reports pages, pages flagged with ``pdf_text_loss_page_*``, tables
detected and rebuilt, words inside detected tables that are absent from the
rebuilt Markdown, word coverage per page, Markdown size/SHA-256 and conversion
seconds. ``--layout`` selects the converter strategy (``legacy``, ``layout`` or
the measurement-only ``tables-lines``). Results are printed as JSON (one line
per file plus a summary) and can be written to a single ``--json`` document.

Since the content-loss audit (``bibliotecario.pdf_audit``, metric
``pdf-content-audit/1``) the report also carries a ``content_audit`` block per
file: real prose/equation loss vs measurement artifacts (duplicate layers,
hyphen fragments, reflow, figure labels, residual multiset surplus) measured
against the final per-page Markdown. The audit adds ~10 % wall time on the 17
PDF corpus (11.8 s against ~106 s of ``convert()``); ``--no-audit`` turns it
off and ``--audit-json PATH`` additionally writes the full census (per-page
numbers and sample evidence) to a separate document.

The measurement runs the production conversion path (``bibliotecario.converters
.convert``) from this worktree, not the editable install of the main checkout:
``apps/api`` is put first on ``sys.path`` before importing the package.

Usage::

    .venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py \
        --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus \
        --layout legacy --json .orca-task/pdf-conversion-legacy.json \
        --audit-json .orca-task/pdf-content-audit.json
"""
from __future__ import annotations

import os
import sys

# PyMuPDF's legacy layout analysis can depend on string-hash ordering, which is
# randomised per process by default. Pin it (single re-exec) so two runs of this
# harness produce byte-identical Markdown on the same corpus.
if "PYTHONHASHSEED" not in os.environ:
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, *sys.argv])

import argparse
import json
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if API_ROOT.is_dir() and str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import pymupdf  # noqa: E402  (path setup must precede the import)

import bibliotecario.converters as converters  # noqa: E402
import bibliotecario.pdf_audit as pdf_audit  # noqa: E402

DEFAULT_CORPUS = Path("D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus")
# Only the settings fields the PDF branch of convert()/validate_file() reads.
SETTINGS = SimpleNamespace(normalized_max_bytes=20 * 1024 * 1024, extraction_max_pages=1000,
                           pdf_layout="legacy")


def _page_markdown(leading, chunk_text, trailing):
    """Exactly the per-page content assembled by converters.convert()."""
    return "\n\n".join(part for part in leading + [chunk_text.rstrip()] + trailing if part.strip()) + "\n\n"


def _count(diagnostics, prefix):
    return sum(1 for item in diagnostics if item.startswith(prefix))


def _convert(path, layout="legacy"):
    """Run convert() while capturing each page's chunk and recovery result."""
    captured = {}
    original = converters.recover_pdf_page

    def capture(page, markdown):
        leading, trailing, diagnostics = original(page, markdown)
        captured[page.number] = {"markdown": markdown, "leading": leading,
                                 "trailing": trailing, "diagnostics": diagnostics}
        return leading, trailing, diagnostics

    converters.recover_pdf_page = capture
    previous = getattr(SETTINGS, "pdf_layout", "legacy")
    SETTINGS.pdf_layout = layout
    try:
        started = time.perf_counter()
        converted = converters.convert(path, "pdf", SETTINGS, filename=path.name)
        seconds = time.perf_counter() - started
    finally:
        SETTINGS.pdf_layout = previous
        converters.recover_pdf_page = original
    return converted, captured, seconds


def _analyse_pages(document, captured):
    """Tables and coverage from the final per-page Markdown."""
    detected = rebuilt = correct = 0
    table_words_lost = 0
    table_pages, loss_pages = [], []
    coverage = []
    for page in document:
        info = captured.get(page.number)
        if info is None:
            continue
        final_markdown = _page_markdown(info["leading"], info["markdown"], info["trailing"])
        final_available = converters._words(final_markdown)
        source = converters._words(page.get_text())
        total = sum(source.values())
        coverage.append(1 - sum((source - final_available).values()) / total if total else 1.0)
        if any(item.startswith(f"pdf_text_loss_page_{page.number + 1}") for item in info["diagnostics"]):
            loss_pages.append(page.number + 1)
        try:
            tables = page.find_tables().tables
        except Exception:  # pragma: no cover - PyMuPDF table detection is best effort
            tables = []
        raw_available = converters._words(info["markdown"])
        for table in tables:
            detected += 1
            table_pages.append(page.number + 1)
            table_words = Counter(word[4].casefold() for word in page.get_text("words", clip=table.bbox))
            lost = sum((table_words - final_available).values())
            table_words_lost += lost
            if lost == 0:
                correct += 1
            # Mirror recover_pdf_page's table pass against the raw chunk so the
            # "rebuilt" count keeps meaning the same before and after the
            # find_tables() optimisation.
            if converters._missing(page.get_textbox(table.bbox), raw_available) > 0.2:
                rebuilt_markdown = converters.pdf_table_markdown(page, table)
                if rebuilt_markdown:
                    rebuilt += 1
                    raw_available.update(converters._words(rebuilt_markdown))
    return {
        "tables_detected": detected,
        "tables_rebuilt": rebuilt,
        "tables_correct": correct,
        "table_words_lost": table_words_lost,
        "table_pages": table_pages,
        "loss_pages": loss_pages,
        "coverage_min": round(min(coverage), 4) if coverage else 1.0,
        "coverage_mean": round(statistics.fmean(coverage), 4) if coverage else 1.0,
    }


def _production_crosscheck(document, page_markdowns):
    """Lines with absent word sequence and how many ``_line_missing`` flags.

    Reproduces on the audit's line unit (dict lines) the question the task
    asks: of the lines whose word sequence is absent from the final markdown,
    how many does production ``_line_missing`` flag as lost?
    """
    candidates = flagged = 0
    for page in document:
        markdown = page_markdowns.get(page.number)
        if markdown is None:
            continue
        stream = converters._stream(markdown)
        available = converters._words(markdown)
        for raw in pdf_audit._raw_page_lines(page):
            words = converters.WORD.findall(raw.text.casefold())
            if not words:
                continue
            if " " + " ".join(words) + " " in stream:
                continue
            candidates += 1
            if converters._line_missing(raw.text, stream, available):
                flagged += 1
    return {"sequence_absent_lines": candidates, "line_missing_flagged": flagged}


def _content_audit(document, page_markdowns, filename):
    """Full audit verdict + production crosscheck, timed."""
    started = time.perf_counter()
    verdict = pdf_audit.audit_document(document, page_markdowns, filename=filename)
    verdict["production"] = _production_crosscheck(document, page_markdowns)
    verdict["audit_secs"] = round(time.perf_counter() - started, 3)
    return verdict


def _compact_content_audit(verdict):
    """The per-file ``content_audit`` block of the console record."""
    return {
        "metric_version": verdict["metric_version"],
        "lines": verdict["lines"],
        "real_prose_words": verdict["real_prose"]["words"],
        "real_equation_lines": verdict["real_equation"]["lines"],
        "artifacts": {category: {"lines": verdict[category]["lines"], "words": verdict[category]["words"]}
                      for category in pdf_audit.CATEGORY_ORDER},
        "missing_symbol_occurrences": verdict["missing_symbols"]["occurrences"],
        "equation_lines_total": verdict["equation_lines_total"],
        "production_sequence_absent_lines": verdict["production"]["sequence_absent_lines"],
        "production_line_missing_flagged": verdict["production"]["line_missing_flagged"],
    }


def measure(path, layout="legacy", audit=True):
    converted, captured, seconds = _convert(path, layout)
    diagnostics = converted["diagnostics"]
    audit_secs = 0.0
    verdict = None
    with pymupdf.open(path) as document:
        pages = len(document)
        stats = _analyse_pages(document, captured)
        if audit:
            page_markdowns = {}
            for page in document:
                info = captured.get(page.number)
                if info is not None:
                    page_markdowns[page.number] = _page_markdown(
                        info["leading"], info["markdown"], info["trailing"])
            verdict = _content_audit(document, page_markdowns, path.name)
            audit_secs = verdict["audit_secs"]
    markdown = converted["markdown"]
    record = {
        "file": path.name,
        "bytes": path.stat().st_size,
        "pages": pages,
        "secs": round(seconds, 3),
        "audit_secs": audit_secs,
        "requested_layout": layout,
        "pdf_layout": converted.get("pdf_layout", "legacy"),
        "markdown_bytes": len(markdown.encode("utf-8")),
        "sha256": converted["sha256"],
        "pages_text_loss": _count(diagnostics, "pdf_text_loss_page_"),
        "pages_tables_recovered": _count(diagnostics, "pdf_tables_recovered_page_"),
        "pages_text_recovered": _count(diagnostics, "pdf_text_recovered_page_"),
        "diagnostics": diagnostics,
    }
    record.update(stats)
    if verdict is not None:
        record["content_audit"] = _compact_content_audit(verdict)
    return record, verdict


def select_files(corpus, names):
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
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS,
                        help="directory holding the PDFs (default: %(default)s)")
    parser.add_argument("--files", default="", help="comma-separated PDF names inside --corpus")
    parser.add_argument("--layout", default="legacy",
                        choices=list(converters.PDF_LAYOUT_STRATEGIES) + ["tables-lines"],
                        help="PDF converter strategy (default: %(default)s)")
    parser.add_argument("--json", type=Path, default=None, help="write the full report to this path")
    parser.add_argument("--no-audit", action="store_true",
                        help="skip the content-loss audit (it costs ~10 %% of the harness)")
    parser.add_argument("--audit-json", type=Path, default=None,
                        help="write the full content-audit census (per page + evidence) here")
    args = parser.parse_args(argv)

    paths = select_files(args.corpus, args.files)
    records, verdicts = [], []
    for path in paths:
        record, verdict = measure(path, args.layout, audit=not args.no_audit)
        records.append(record)
        if verdict is not None:
            verdicts.append({key: value for key, value in verdict.items()})
        console = {key: value for key, value in record.items()
                   if key not in {"diagnostics", "table_pages", "loss_pages"}}
        print(json.dumps(console, ensure_ascii=True), flush=True)

    audited = [item for item in records if "content_audit" in item]
    slowest = sorted(records, key=lambda item: item["secs"], reverse=True)[:5]
    summary = {
        "requested_layout": args.layout,
        "fallbacks": sum(1 for item in records if item["pdf_layout"] != args.layout),
        "files": len(records),
        "pages": sum(item["pages"] for item in records),
        "secs": round(sum(item["secs"] for item in records), 3),
        "audit_secs": round(sum(item["audit_secs"] for item in records), 3),
        "pages_text_loss": sum(item["pages_text_loss"] for item in records),
        "pages_tables_recovered": sum(item["pages_tables_recovered"] for item in records),
        "pages_text_recovered": sum(item["pages_text_recovered"] for item in records),
        "tables_detected": sum(item["tables_detected"] for item in records),
        "tables_rebuilt": sum(item["tables_rebuilt"] for item in records),
        "tables_correct": sum(item["tables_correct"] for item in records),
        "table_words_lost": sum(item["table_words_lost"] for item in records),
        "real_prose_words": sum(item["content_audit"]["real_prose_words"] for item in audited),
        "real_equation_lines": sum(item["content_audit"]["real_equation_lines"] for item in audited),
        "slowest": [{"file": item["file"], "secs": item["secs"]} for item in slowest],
    }
    payload = {"corpus": str(args.corpus),
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "python_hash_seed": os.environ.get("PYTHONHASHSEED", "unset"),
               "converter_module": converters.__file__,
               "files": records, "summary": summary}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.audit_json:
        audit_payload = {"metric_version": pdf_audit.METRIC_VERSION,
                         "corpus": str(args.corpus),
                         "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "python_hash_seed": os.environ.get("PYTHONHASHSEED", "unset"),
                         "files": verdicts}
        args.audit_json.parent.mkdir(parents=True, exist_ok=True)
        args.audit_json.write_text(json.dumps(audit_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=True, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
