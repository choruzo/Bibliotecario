import hashlib
import re
from collections import Counter

from markdown_it import MarkdownIt

from .storage import InvalidFile, validate_file


PARSER = MarkdownIt("commonmark").enable("table")
BLOCKS = {"heading_open", "paragraph_open", "bullet_list_open", "ordered_list_open", "fence", "code_block", "table_open", "blockquote_open", "hr"}


def provenance(markdown, fmt, page=None, line_offset=0, section_prefix=None):
    tokens = PARSER.parse(markdown)
    sections = list(section_prefix or [])
    result = []
    for index, token in enumerate(tokens):
        if token.level != 0 or token.type not in BLOCKS or token.map is None:
            continue
        if token.type == "heading_open":
            level = int(token.tag[1:])
            title = tokens[index + 1].content
            sections = sections[:level - 1] + [title]
        result.append({"kind": "page" if page else "line_range" if fmt == "txt" else "section",
                       "page": page, "section_path": list(sections), "format": fmt,
                       "line_start": token.map[0] + 1 + line_offset,
                       "line_end": token.map[1] + line_offset, "origin": "original"})
    return result


def edited_provenance(previous, old_map, markdown):
    old_lines, new_lines = previous.splitlines(), markdown.splitlines()
    by_text = {}
    for locator in old_map:
        text = "\n".join(old_lines[locator["line_start"] - 1:locator["line_end"]])
        by_text.setdefault(text, []).append(locator)
    new_map = provenance(markdown, "md")
    counts = Counter("\n".join(new_lines[item["line_start"] - 1:item["line_end"]]) for item in new_map)
    for item in new_map:
        text = "\n".join(new_lines[item["line_start"] - 1:item["line_end"]])
        candidates = by_text.get(text, [])
        if len(candidates) == 1 and counts[text] == 1:
            original = candidates[0]
            item.update({key: original[key] for key in ("kind", "page", "format", "origin")})
        else:
            item["origin"] = "manual"
            item["page"] = None
    return new_map


def docx_to_markdown(path):
    from docx import Document
    from docx.table import Table

    document = Document(path)
    parts, diagnostics = [], []
    code_lines = []

    def flush_code():
        if code_lines:
            fence = "`" * max(3, max((len(match.group()) + 1 for value in code_lines for match in re.finditer(r"`+", value)), default=3))
            parts.append(fence + "\n" + "\n".join(code_lines) + "\n" + fence)
            code_lines.clear()

    for item in document.iter_inner_content():
        if isinstance(item, Table):
            flush_code()
            rows = [[cell.text.replace("|", "\\|").replace("\n", "<br>") for cell in row.cells] for row in item.rows]
            if rows:
                table = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * len(rows[0])) + " |"]
                table.extend("| " + " | ".join(row) + " |" for row in rows[1:])
                parts.append("\n".join(table))
            continue
        style = item.style.name if item.style else ""
        text = item.text
        if style in {"Code", "Code Block", "Source Code"} or (item.runs and all(run.font.name in {"Consolas", "Courier New"} for run in item.runs if run.text)):
            code_lines.append(text)
            continue
        flush_code()
        heading = re.fullmatch(r"Heading ([1-6])", style)
        if heading:
            parts.append("#" * int(heading.group(1)) + " " + text)
        elif style == "Title":
            parts.append("# " + text)
        elif style.startswith("List Bullet"):
            parts.append("- " + text)
        elif style.startswith("List Number"):
            parts.append("1. " + text)
        elif item._p.pPr is not None and item._p.pPr.numPr is not None:
            parts.append("- " + text)
            if "numbering_normalized" not in diagnostics:
                diagnostics.append("numbering_normalized")
        elif text:
            parts.append(text)
    flush_code()
    if document.inline_shapes:
        diagnostics.append("docx_images_omitted")
    if any(section.header.paragraphs[0].text or section.footer.paragraphs[0].text for section in document.sections):
        diagnostics.append("docx_header_footer_omitted")
    return "\n\n".join(parts), diagnostics


WORD = re.compile(r"[^\W_]+")
# Unrecovered PDF text must not be silently lost; below this coverage the page is flagged.
PDF_MIN_COVERAGE = 0.97


def _words(text):
    return Counter(WORD.findall(text.casefold()))


def _stream(markdown):
    # Link targets are not visible page text.
    return " " + " ".join(WORD.findall(re.sub(r"\]\([^)]*\)", " ", markdown).casefold())) + " "


def _missing(text, available):
    words = _words(text)
    total = sum(words.values())
    return sum((words - available).values()) / total if total else 0.0


def _line_missing(line, stream, available):
    # Short lines need their exact word sequence; longer lines tolerate small
    # normalization differences (e.g. a conjunction turned into a list marker).
    words = WORD.findall(line.casefold())
    if not words or " " + " ".join(words) + " " in stream:
        return False
    return len(words) < 4 or _missing(line, available) > 0.2


def _missing_runs(text, stream, available):
    """Consecutive lines of a PDF text block absent from the converted page."""
    runs, current = [], []
    for line in (line.strip() for line in text.splitlines()):
        if not WORD.search(line):
            continue
        if _line_missing(line, stream, available):
            current.append(line)
        elif current:
            runs.append(current)
            current = []
    return runs + ([current] if current else [])


def _block_missing(text, stream, available):
    total = sum(len(WORD.findall(line)) for line in text.splitlines())
    lost = sum(len(WORD.findall(line)) for run in _missing_runs(text, stream, available) for line in run)
    return lost / total if total else 0.0


def _center_in(word_box, box):
    x, y = (word_box[0] + word_box[2]) / 2, (word_box[1] + word_box[3]) / 2
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def pdf_table_markdown(page, table):
    """Rebuild a table from word coordinates; merged-cell extraction can repeat text."""
    rows = list(table.rows)
    if len(rows) < 2:
        return None
    header = max(rows, key=lambda row: sum(cell is not None for cell in row.cells))
    columns = [cell for cell in header.cells if cell]
    names = [page.get_textbox(cell).split() for cell in columns]
    # Layout artefacts (e.g. wrapped URLs) are not tables; their text is recovered as blocks.
    if len(columns) < 2 or any(not name or len(" ".join(name)) > 60 for name in names):
        return None
    words, used, grid = page.get_text("words", clip=table.bbox), set(), []
    for row in rows:
        cells = [[] for _ in columns]
        for index, word in enumerate(words):
            if index in used or not _center_in(word, (table.bbox[0], row.bbox[1], table.bbox[2], row.bbox[3])):
                continue
            center = (word[0] + word[2]) / 2
            column = next((i for i, cell in enumerate(columns) if cell[0] <= center < cell[2]),
                          min(range(len(columns)), key=lambda i: abs((columns[i][0] + columns[i][2]) / 2 - center)))
            cells[column].append(word)
            used.add(index)
        values = [" ".join(w[4] for w in sorted(cell, key=lambda w: (w[5], w[6], w[7]))).replace("|", "\\|")
                  for cell in cells]
        if any(values):
            grid.append(values)
    if len(grid) < 2:
        return None
    lines = ["| " + " | ".join(grid[0]) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in grid[1:])
    return "\n".join(lines)


def recover_pdf_page(page, markdown):
    """Return (leading, trailing, diagnostics) for page text the layout conversion dropped.

    Tables and text blocks are only added when their words are missing from the
    converted page, so correctly converted content is never duplicated.
    """
    available, number = _words(markdown), page.number + 1
    stream = [_stream(markdown)]
    leading, trailing, diagnostics, boxes = [], [], [], []
    blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    missing = {id(b): _block_missing(b[4], stream[0], available) > 0.5 for b in blocks}
    first_present = min((b[1] for b in blocks if not missing[id(b)]), default=float("inf"))

    def place(y, text):
        # Content above the first converted block continues the previous page's section.
        (leading if y < first_present else trailing).append((y, text))
        available.update(_words(text))
        stream[0] += _stream(text)

    try:
        tables = page.find_tables().tables
    except Exception:  # pragma: no cover - PyMuPDF table detection is best effort
        tables = []
    for table in tables:
        text = page.get_textbox(table.bbox)
        if _missing(text, available) <= 0.2:
            continue
        rebuilt = pdf_table_markdown(page, table)
        if rebuilt:
            place(table.bbox[1], rebuilt)
            boxes.append(table.bbox)
            if f"pdf_tables_recovered_page_{number}" not in diagnostics:
                diagnostics.append(f"pdf_tables_recovered_page_{number}")
    for block in blocks:
        if any(_center_in(block[:4], box) for box in boxes):
            continue
        for lines in _missing_runs(block[4], stream[0], available):
            # Escape leading markdown markers so recovered text stays inert paragraph text.
            place(block[1], "\n".join(re.sub(r"^([#>*+\-|]|\d+[.)])", r"\\\1", line) for line in lines))
            if f"pdf_text_recovered_page_{number}" not in diagnostics:
                diagnostics.append(f"pdf_text_recovered_page_{number}")
    source = _words(page.get_text())
    total = sum(source.values())
    if total and 1 - sum((source - available).values()) / total < PDF_MIN_COVERAGE:
        diagnostics.append(f"pdf_text_loss_page_{number}")
    order = lambda items: [text for _, text in sorted(items, key=lambda item: item[0])]
    return order(leading), order(trailing), diagnostics


def convert(path, fmt, settings, filename=None):
    validate_file(path, filename or f"original.{fmt}", None, settings)
    diagnostics, locators = [], []
    if fmt in {"md", "txt"}:
        markdown = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        locators = provenance(markdown, fmt)
    elif fmt == "docx":
        markdown, diagnostics = docx_to_markdown(path)
        locators = provenance(markdown, fmt)
    elif fmt == "pdf":
        import pymupdf
        import pymupdf4llm
        pieces, offset, sections = [], 0, []
        with pymupdf.open(path) as document:
            for page in document:
                if not page.get_text().strip():
                    diagnostics.append(f"possible_ocr_page_{page.number + 1}")
                if page.get_images() and "pdf_images_omitted" not in diagnostics:
                    diagnostics.append("pdf_images_omitted")
            chunks = pymupdf4llm.to_markdown(document, page_chunks=True, use_ocr=False,
                                            write_images=False, ignore_images=True, show_progress=False)
            recovered = [recover_pdf_page(page, chunk["text"]) for page, chunk in zip(document, chunks)]
        for index, chunk in enumerate(chunks):
            leading, trailing, found = recovered[index]
            diagnostics.extend(found)
            content = "\n\n".join(part for part in leading + [chunk["text"].rstrip()] + trailing if part.strip()) + "\n\n"
            maps = provenance(content, fmt, page=index + 1, line_offset=offset, section_prefix=sections)
            if maps:
                sections = maps[-1]["section_path"]
            locators.extend(maps)
            pieces.append(content)
            offset += len(content.splitlines())
        markdown = "".join(pieces)
    else:
        raise InvalidFile("format_unsupported")
    if len(markdown.encode("utf-8")) > settings.normalized_max_bytes:
        raise InvalidFile("normalized_too_large")
    if not markdown.strip():
        diagnostics.append("empty_document")
    return {"markdown": markdown, "provenance": locators, "diagnostics": diagnostics,
            "sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest()}
