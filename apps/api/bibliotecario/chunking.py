"""Structural blocks, bounded UTF-8 payloads and exact revision locators."""
from .converters import provenance

CHUNK_BYTES = 900


def split_blocks(markdown, source_map, budget=CHUNK_BYTES):
    lines = markdown.splitlines(keepends=True)
    blocks = provenance(markdown, "md")
    # H2's structural map omits raw HTML. Keep every nonblank uncovered range
    # as inert text, with a normalized-revision locator rather than an invented page.
    covered = {line for block in blocks for line in range(block["line_start"], block["line_end"] + 1)}
    gaps, position = [], 1
    while position <= len(lines):
        if position in covered or not lines[position - 1].strip():
            position += 1
            continue
        start = position
        while position <= len(lines) and position not in covered:
            position += 1
        preceding = [block for block in blocks if block["line_end"] < start]
        sections = preceding[-1]["section_path"] if preceding else []
        gaps.append({"kind": "section", "page": None, "section_path": sections, "format": "md",
                     "line_start": start, "line_end": position - 1, "origin": "normalized"})
    blocks = sorted(blocks + gaps, key=lambda block: block["line_start"])
    result = []
    for block in blocks:
        start, end = block["line_start"], block["line_end"]
        locators = [dict(item) for item in source_map
                    if item["line_start"] <= end and item["line_end"] >= start]
        if not locators:
            locators = [block | {"origin": "normalized"}]
        section = " > ".join(block["section_path"])
        # Cap repeated heading context so pathological headings cannot consume the budget.
        heading = section.encode("utf-8")[:180].decode("utf-8", errors="ignore")
        prefix = heading + "\n" if heading else ""
        capacity = budget - len(prefix.encode("utf-8"))
        content = "".join(lines[start - 1:end])
        offset = 0
        while offset < len(content):
            stop, size = offset, 0
            while stop < len(content) and size + len(content[stop].encode("utf-8")) <= capacity:
                size += len(content[stop].encode("utf-8"))
                stop += 1
            if stop == offset:
                raise ValueError("chunk_budget_too_small")
            text = content[offset:stop]
            if text.strip():
                line_start = start + content[:offset].count("\n")
                line_end = start + content[:stop].rstrip("\n").count("\n")
                mapped = [item | {"chunk_line_start": line_start, "chunk_line_end": line_end}
                          for item in locators if item["line_start"] <= line_end and item["line_end"] >= line_start]
                result.append({"content": text, "search_content": prefix + text,
                               "provenance": mapped or locators,
                               "line_start": line_start, "line_end": line_end})
            offset = stop
    return result
