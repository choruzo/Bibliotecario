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
        for index, chunk in enumerate(chunks):
            content = chunk["text"].rstrip() + "\n\n"
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
