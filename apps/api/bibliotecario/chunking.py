"""Structural blocks, bounded UTF-8 payloads and exact revision locators."""
import re

from .converters import provenance

CHUNK_BYTES = 900
# Markdown links (URLs may contain one level of parentheses) and bare URLs.
LINKS = re.compile(r"\[[^\]]*\]\((?:[^()\s]|\([^()\s]*\))*\)|https?://[^\s)\]>]+")
# A line that is only an in-document anchor link, as in a table of contents.
NAVIGATION = re.compile(r"[ \t]*(?:[-*+]|\d+[.)])?[ \t]*\[[^\]\n]*\]\(#[^)\s]*\)[ \t]*")
BREAKS = (re.compile(r"\n"), re.compile(r"(?<=[.!?;:])[ \t]+"), re.compile(r"[ \t]+"))


def break_point(content, offset, stop, spans):
    """Latest boundary within the budget that does not split a word or link.

    Prefers line ends, then sentence ends, then spaces, searching the second half
    of the budget first so chunks stay reasonably full. A hard cut remains only
    for a single token (word or link) longer than the budget.
    """
    if stop >= len(content):
        return stop
    inside = lambda point: any(start < point < end for start, end in spans)
    floor = offset + (stop - offset) // 2
    attempts = [(pattern, floor, True) for pattern in BREAKS] + [(BREAKS[2], offset, True),
                (BREAKS[0], offset, False), (BREAKS[2], offset, False)]
    for pattern, start, avoid_links in attempts:
        points = [m.end() for m in pattern.finditer(content, start, stop)
                  if offset < m.end() <= stop and not (avoid_links and inside(m.end()))]
        if points:
            return points[-1]
    return stop


def heading_prefix(section_path):
    # Cap repeated heading context so pathological headings cannot consume the budget.
    heading = " > ".join(section_path).encode("utf-8")[:180].decode("utf-8", errors="ignore")
    return heading + "\n" if heading else ""


def group_blocks(blocks, lines, budget):
    """Merge consecutive blocks of the same section while the span fits the budget.

    Converted PDFs yield many tiny blocks (one per line or table row); merged spans
    keep block boundaries as cut points, and an oversized block stays alone so
    `break_point` splits it as before. Navigation blocks (only anchor links) are
    never merged: a whole table of contents in one fragment matches any question
    about sections while holding none of their content.
    """
    navigation = lambda block: all(NAVIGATION.fullmatch(line.rstrip("\n")) for line in
                                   lines[block["line_start"] - 1:block["line_end"]] if line.strip())
    groups = []
    for block in blocks:
        last = groups[-1] if groups else None
        if (last and last["section_path"] == block["section_path"]
                and not navigation(block) and not navigation(last["members"][-1])):
            capacity = budget - len(heading_prefix(block["section_path"]).encode("utf-8"))
            span = "".join(lines[last["line_start"] - 1:block["line_end"]])
            if len(span.encode("utf-8")) <= capacity:
                last["line_end"] = block["line_end"]
                last["members"].append(block)
                continue
        groups.append(block | {"members": [block]})
    return groups


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
    for block in group_blocks(blocks, lines, budget):
        start, end = block["line_start"], block["line_end"]
        locators = [dict(item) for item in source_map
                    if item["line_start"] <= end and item["line_end"] >= start]
        # Members the source map does not cover keep a normalized-revision locator.
        locators += [member | {"origin": "normalized"} for member in block["members"]
                     if not any(item["line_start"] <= member["line_end"] and item["line_end"] >= member["line_start"]
                                for item in locators)]
        locators.sort(key=lambda item: item["line_start"])
        prefix = heading_prefix(block["section_path"])
        capacity = budget - len(prefix.encode("utf-8"))
        content = "".join(lines[start - 1:end])
        spans = [m.span() for m in LINKS.finditer(content)]
        offset = 0
        while offset < len(content):
            stop, size = offset, 0
            while stop < len(content) and size + len(content[stop].encode("utf-8")) <= capacity:
                size += len(content[stop].encode("utf-8"))
                stop += 1
            if stop == offset:
                raise ValueError("chunk_budget_too_small")
            stop = break_point(content, offset, stop, spans)
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
