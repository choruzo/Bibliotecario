"""Unit tests of the math-formatting cleanup (pdf_math_clean).

Two families share one pipeline:

- the marker-only pass (``clean_math_emphasis``): emphasis stripped on math
  lines and continuation blocks, prose kept, token invariant with whole-page
  revert;
- the span-based stages (``clean_page_markdown`` with a page object):
  synthetic spans with math emphasis and prose bold kept, glue spaces at
  cross-line junctions, compound-hyphen restoration with its evidence rules,
  normal-prose pages left untouched, the token invariant helper, the font
  gate and a synthetic two-column PDF with an italic equation.
"""
import re
from types import SimpleNamespace

import pymupdf

from bibliotecario import pdf_math_clean as pmc
from bibliotecario.converters import convert


def clean(markdown: str):
    cleaned, changed, reverted = pmc.clean_math_emphasis(1, markdown)
    return cleaned, changed, reverted


def test_attention_equation_is_cleaned_marker_only():
    before = " Attention( _Q, K, V_ ) = softmax( _[QK]_ ~~_V_~~ _[T]_ "
    after, changed, reverted = clean(before)
    assert (after, changed, reverted) == \
        (" Attention( Q, K, V ) = softmax( [QK] V [T] ", 1, False)
    assert pmc.tokens(before) == pmc.tokens(after)


def test_lrate_equation_is_cleaned():
    before = "_lrate_ = _d_ _[-]_ model [0] _[.]_ [5]"
    after, _, reverted = clean(before)
    assert not reverted
    assert after == "lrate = d [-] model [0] [.] [5]"
    assert pmc.tokens(before) == pmc.tokens(after)


def test_prose_with_loose_equals_and_legit_emphasis_is_untouched():
    before = ("Total Parameters=110M) and **BERTBASE** — see _York Times_ "
              "apellido=Bakalar reference")
    after, changed, reverted = clean(before)
    assert (after, changed, reverted) == (before, 0, False)


def test_wiki_reference_strike_is_not_math():
    before = ("[miseria en la crisis del café entre 1998 y 200](https://example.com/a) "
              "~~4~~ ~~.~~ [126] cuando la enorme caída")
    after, changed, _ = clean(before)
    assert (after, changed) == (before, 0)


def test_bold_prose_label_on_equals_line_is_untouched():
    before = '**Operador** **de asignación en expresiones (:=)** : Conocido como el "operador morsa",'
    after, changed, _ = clean(before)
    assert (after, changed) == (before, 0)


def test_prose_bold_names_on_a_math_line_keep_their_marks():
    before = "**Ashish Vaswani** _[∗]_"
    after, _, _ = clean(before)
    assert after == "**Ashish Vaswani** [∗]"


def test_table_heading_bullet_indented_and_code_lines_are_never_touched():
    before = "\n".join([
        "|big|6<br>1024<br>4096<br>16<br>0.3<br>300K|**4.33**<br>**26.4**<br>213|",
        "## **Attention Is All You Need**",
        "- **Batch size** : 16, 32",
        "1. _Proceedings of the 2006 conference_",
        "    _indented_ code _x_ = 1",
        "```",
        "_y_ = 2",
        "```",
    ])
    after, changed, _ = clean(before)
    assert (after, changed) == (before, 0)


def test_multiline_formula_continuations_are_cleaned_across_blank_lines():
    before = "\n".join([
        "Attention( _Q, K, V_ ) = softmax( _[QK]_ ~~_V_~~ _[T]_",
        "",
        "_dk_",
        "",
        "",
        ") _V_ (1)",
    ]) + "\n"
    after, changed, reverted = clean(before)
    assert not reverted
    assert changed == 3
    assert after == "\n".join([
        "Attention( Q, K, V ) = softmax( [QK] V [T]",
        "",
        "dk",
        "",
        "",
        ") V (1)",
    ]) + "\n"
    assert pmc.tokens(before) == pmc.tokens(after)


def test_prose_continuation_after_a_math_line_is_untouched():
    before = "\n".join([
        "_lrate_ = _d_ _[-]_ model [0] _[.]_ [5]",
        "where _warmup_ steps and the **learning rate** schedule are described in section 5.3.",
        "_dk_, the dot products grow large in magnitude, pushing the softmax function.",
    ])
    after, changed, _ = clean(before)
    assert changed == 1  # only the equation line itself
    assert after.splitlines()[1:] == before.splitlines()[1:]
    assert pmc.tokens(before) == pmc.tokens(after)


def test_table_after_a_math_line_closes_the_block():
    before = "\n".join([
        "PE ( pos, 2 i ) = sin ( pos/ 10000 [2] [i/d] [model] )",
        "",
        "|big|6|**4.33**|",
        "",
        "**26.4**",
    ]) + "\n"
    after, changed, _ = clean(before)
    assert (after, changed) == (before, 0)
    assert pmc.tokens(before) == pmc.tokens(after)


def test_heading_after_a_math_line_closes_the_block():
    before = "\n".join([
        "lrate = d [-] model [0] [.] [5]",
        "",
        "## **Positional Encoding**",
        "",
        "_dk_",
    ]) + "\n"
    after, changed, _ = clean(before)
    assert (after, changed) == (before, 0)


def test_blank_lines_bridge_a_block_but_prose_closes_it():
    before = "\n".join([
        "Attention( Q, K, V ) = softmax( [QK] √ [T]",
        "",
        "",
        "_dk_",
        "",
        "",
        ") _V_ (1)",
        "",
        "The two most commonly used attention functions are additive attention.",
        "",
        "_dk_",
    ]) + "\n"
    after, changed, reverted = clean(before)
    assert not reverted
    assert changed == 2
    assert "\ndk\n\n\n) V (1)" in after
    assert after.endswith("additive attention.\n\n_dk_\n")
    assert pmc.tokens(before) == pmc.tokens(after)


def test_multihead_formula_fragments_are_cleaned_and_prose_keeps_marks():
    before = "\n".join([
        "where headi = Attention( QWi [Q]",
        "",
        "_[ K]_ _i_ _[, V W][ V]_ _i_",
        "",
        "_[ V]_ _i_ [)]",
        "",
        "Where the projections are parameter matrices _W_ _[Q]_",
    ]) + "\n"
    after, changed, reverted = clean(before)
    assert not reverted
    assert changed == 2  # both fragment lines; the formula line carries no markers
    assert "[ K] i [, V W][ V] i" in after
    assert "[ V] i [)]" in after
    assert "_W_ _[Q]_" in after  # the prose line keeps its emphasis
    assert pmc.tokens(before) == pmc.tokens(after)


def test_snake_case_identifiers_keep_their_underscores():
    before = "where d_model = _h_ and n_head = 8"
    after, changed, _ = clean(before)
    assert (after, changed) == ("where d_model = h and n_head = 8", 1)
    assert pmc.tokens(before) == pmc.tokens(after)


def test_markers_flanked_by_alphanumerics_are_left_alone():
    before = "a**b**c = _d_"
    after, changed, reverted = clean(before)
    assert (after, changed, reverted) == ("a**b**c = d", 1, False)
    assert pmc.tokens(before) == pmc.tokens(after)


def test_page_is_reverted_when_a_substitution_would_drop_tokens(monkeypatch):
    class Broken:
        @staticmethod
        def sub(_replacement, text):  # loses every alphanumeric character
            return "lost" if "**" in text else text

    monkeypatch.setattr(pmc, "BOLD", Broken)
    before = "value **42** = key"
    cleaned, changed, reverted = pmc.clean_math_emphasis(1, before)
    assert (cleaned, changed, reverted) == (before, 0, True)


def test_synthetic_pdf_equation_loses_markers_and_prose_keeps_them(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_textbox(pymupdf.Rect(60, 60, 520, 100), "a = b + 2", fontsize=12,
                        fontname="Times-Italic")
    page.insert_textbox(pymupdf.Rect(60, 120, 520, 260),
                        "This prose sentence keeps its emphasis markers intact.",
                        fontsize=12, fontname="Times-Italic")
    path = tmp_path / "synthetic.pdf"
    pdf.save(path)
    pdf.close()

    settings = SimpleNamespace(normalized_max_bytes=20 * 1024 * 1024,
                               extraction_max_pages=1000, pdf_layout="legacy")
    result = convert(path, "pdf", settings)
    markdown = result["markdown"]
    assert "a = b + 2" in markdown
    assert "_a_" not in markdown
    assert "keeps its emphasis markers intact" in markdown
    assert re.search(r"_This prose sentence", markdown)
    assert not any(item.startswith("pdf_math_clean_reverted") for item in result["diagnostics"])
    assert any(item.startswith("pdf_math_emphasis_page_1") for item in result["diagnostics"])


# ---------------------------------------------------------------------------
# Span-based stages (clean_page_markdown with a page object)
# ---------------------------------------------------------------------------
def span(text, x0, y0, x1, y1, font="NimbusRomNo9L-Regu", flags=4, size=10.0,
         char_flags=16, line_no=0, block_no=0):
    return {"text": text, "bbox": [x0, y0, x1, y1], "flags": flags, "char_flags": char_flags,
            "size": size, "font": font, "alpha": 255}


def block(number, lines):
    return {"type": 0, "number": number, "bbox": [0, 0, 500, 700],
            "lines": [{"bbox": [0, 0, 500, 700], "dir": [1, 0], "spans": spans} for spans in lines]}


class FakeTextPage:
    def __init__(self, blocks):
        self._blocks = blocks

    def extractDICT(self):
        return {"blocks": self._blocks}


class FakePage:
    """Minimal page surface for pdf_math_clean (dict + text + fonts)."""

    def __init__(self, blocks, text="", fonts=()):
        self._blocks = blocks
        self._text = text
        self._fonts = list(fonts)
        self.number = 0
        self.rect = (0, 0, 612, 792)

    def get_textpage(self, flags=None, clip=None):
        return FakeTextPage(self._blocks)

    def get_text(self, kind="text"):
        if kind == "dict":
            return {"blocks": self._blocks}
        return self._text

    def get_fonts(self):
        return self._fonts


def math_span(text, x0, y0, x1, y1, size=10.0, line_no=0):
    return span(text, x0, y0, x1, y1, font="CMMI10", flags=6, size=size, line_no=line_no)


def test_math_emphasis_is_stripped_and_prose_bold_is_kept():
    page = FakePage([block(0, [[
        span("Attention(", 100, 100, 160, 110),
        math_span("Q, K, V", 160, 100, 220, 110),
        span(") = softmax(", 220, 100, 300, 110),
        math_span("QK", 300, 100, 330, 110),
        span(")", 330, 100, 340, 110),
    ]])])
    markdown = "Attention( _Q, K, V_ ) = softmax( _QK_ )\n"
    cleaned, diagnostics = pmc.clean_page_markdown(page, markdown, 1)
    assert cleaned == "Attention( Q, K, V ) = softmax( QK )\n"
    assert diagnostics == ["pdf_math_emphasis_page_1"]


def test_superscript_brackets_and_strikeout_markers_disappear_on_math():
    page = FakePage([block(0, [[
        span("of", 100, 100, 115, 110),
        span("√", 116, 100, 130, 110, font="CMSY10", flags=7, char_flags=17),
        math_span("[T]", 130, 100, 142, 110, size=7.0),
    ]])])
    markdown = "of ~~_[√]_~~ _[T]_\n"
    cleaned, _ = pmc.clean_page_markdown(page, markdown, 1)
    assert cleaned == "of [√] [T]\n"


def test_prose_page_without_math_is_untouched():
    spans = [span("Texto normal de prueba sin matematicas.", 100, 100, 300, 110)]
    page = FakePage([block(0, [spans])])
    markdown = "Texto normal de prueba sin matematicas.\n"
    cleaned, diagnostics = pmc.clean_page_markdown(page, markdown, 1)
    assert cleaned == markdown
    assert diagnostics == []


def test_page_without_math_fonts_is_untouched_even_with_operands():
    # An italic span with operands but no math font and a non-italic run:
    # ordinary prose italics must never be stripped.
    page = FakePage([block(0, [[
        span("_York Times_", 100, 100, 170, 110, font="NimbusRomNo9L-ReguIt", flags=6),
        span(" . 2006-08-15 apellido=Bakalar", 170, 100, 320, 110),
    ]])])
    markdown = "_York Times_ . 2006-08-15 apellido=Bakalar\n"
    cleaned, diagnostics = pmc.clean_page_markdown(page, markdown, 1)
    assert cleaned == markdown
    assert diagnostics == []


def test_glued_words_at_cross_line_junction_get_a_space():
    # Two spans of DIFFERENT dict lines that overlap horizontally and share
    # flags: the converter joins them ('dimensionquery'); the cleanup splits.
    page = FakePage([block(0, [
        [span("queries and keys of dimension", 107.5, 381.3, 229.2, 391.1, line_no=0)],
        [span("query with all keys", 108.0, 383.9, 247.6, 401.3, line_no=1)],
        [math_span("dk", 229.2, 383.9, 241.1, 391.1, line_no=0)],
    ])])
    markdown = "queries and keys of dimensionquery with all keys _dk_\n"
    cleaned, diagnostics = pmc.clean_page_markdown(page, markdown, 1)
    assert cleaned == "queries and keys of dimension query with all keys dk\n"
    assert sorted(diagnostics) == ["pdf_math_emphasis_page_1", "pdf_math_glue_space_page_1"]


def test_compound_hyphen_is_restored_with_document_evidence():
    page = FakePage(
        [block(0, [
            [span("without substantial task-", 100, 100, 250, 110, line_no=0)],
            [span("specific architecture modifications.", 100, 111, 300, 121, line_no=1)],
        ])],
        text="without substantial task-specific architecture modifications.")
    markdown = "without substantial taskspecific architecture modifications.\n"
    # 'task-specific' used mid-line elsewhere in the document:
    vocabulary = {"task-specific"}
    cleaned, diagnostics = pmc.clean_page_markdown(page, markdown, 1, vocabulary)
    assert cleaned == "without substantial task-specific architecture modifications.\n"
    assert diagnostics == ["pdf_math_compound_hyphen_page_1"]


def test_compound_hyphen_chain_evidence():
    page = FakePage(
        [block(0, [
            [span("to pre-train word vectors, left-to-", 100, 100, 260, 110, line_no=0)],
            [span("right language modeling.", 100, 111, 250, 121, line_no=1)],
        ])],
        text="to pre-train word vectors, left-to-right language modeling.")
    markdown = "to pre-train word vectors, left-toright language modeling.\n"
    cleaned, diagnostics = pmc.clean_page_markdown(page, markdown, 1, set())
    assert cleaned == "to pre-train word vectors, left-to-right language modeling.\n"
    assert diagnostics == ["pdf_math_compound_hyphen_page_1"]


def test_wrapped_year_is_never_restored_as_compound():
    page = FakePage(
        [block(0, [
            [span("julio de 201-", 100, 100, 180, 110, line_no=0)],
            [span("8. Consultado el 14 de julio.", 100, 111, 260, 121, line_no=1)],
        ])],
        text="julio de 201-8. Consultado el 14 de julio.")
    markdown = "julio de 2018. Consultado el 14 de julio.\n"
    cleaned, diagnostics = pmc.clean_page_markdown(page, markdown, 1, {"201-8", "201-9"})
    assert cleaned == markdown
    assert diagnostics == []


def test_syllable_hyphenation_without_evidence_is_left_joined():
    page = FakePage(
        [block(0, [
            [span("language representa-", 100, 100, 210, 110, line_no=0)],
            [span("tion model called BERT.", 100, 111, 250, 121, line_no=1)],
        ])],
        text="language representation model called BERT.")
    markdown = "language representation model called BERT.\n"
    cleaned, diagnostics = pmc.clean_page_markdown(page, markdown, 1, set())
    assert cleaned == markdown
    assert diagnostics == []


def test_tokens_preserved_accepts_splits_and_rejects_the_rest():
    assert pmc.tokens_preserved(["dimensionquery"], ["dimension", "query"])
    assert pmc.tokens_preserved(["leftto", "right"], ["left", "to", "right"])
    assert pmc.tokens_preserved(["a", "b", "c"], ["a", "b", "c"])
    assert not pmc.tokens_preserved(["a", "b"], ["ab"])  # merge
    assert not pmc.tokens_preserved(["a", "b", "c"], ["a", "c", "b"])  # reorder
    assert not pmc.tokens_preserved(["a", "b"], ["a"])  # deletion
    assert not pmc.tokens_preserved(["a"], ["a", "b"])  # insertion


def test_page_may_have_math_uses_embedded_font_names():
    assert pmc.page_may_have_math(FakePage([], fonts=[(1, 0, "Type1", "VWQKZV+CMMI10", "F1")]))
    assert not pmc.page_may_have_math(FakePage([], fonts=[(1, 0, "Type1", "NimbusRomNo9L-Regu", "F1")]))


def test_broken_cleanup_is_reverted_whole(monkeypatch):
    page = FakePage([block(0, [[
        span("Attention(", 100, 100, 160, 110),
        math_span("Q, K, V", 160, 100, 220, 110),
        span(")", 220, 100, 230, 110),
    ]])])
    markdown = "Attention( _Q, K, V_ )\n"
    real_render = pmc.render_line

    def fake_render(spans, has_operand, strip_math=False, mostly_italic=False):
        if strip_math:
            return "words vanishing entirely"
        return real_render(spans, has_operand, strip_math=False, mostly_italic=mostly_italic)

    monkeypatch.setattr(pmc, "render_line", fake_render)
    cleaned, diagnostics = pmc.clean_page_markdown(page, markdown, 1)
    assert cleaned == markdown
    assert diagnostics == ["pdf_math_clean_reverted_page_1"]


def two_column_equation_pdf(path):
    """A4 page: left column holds an italic equation, right column prose."""
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((60, 100), "E = mc2", fontname="tiit", fontsize=11)
    page.insert_text((320, 100), "Texto normal de la columna derecha.", fontname="tiro", fontsize=11)
    pdf.save(path)
    pdf.close()


def test_synthetic_two_column_pdf_with_italic_equation(tmp_path):
    file = tmp_path / "two-columns-equation.pdf"
    two_column_equation_pdf(file)
    import pymupdf4llm

    with pymupdf.open(file) as document:
        chunks = pymupdf4llm.to_markdown(document, page_chunks=True, write_images=False,
                                         ignore_images=True, show_progress=False,
                                         table_strategy="lines_strict")
        markdown = chunks[0]["text"]
        assert "_E = mc2_" in markdown
        cleaned, diagnostics = pmc.clean_page_markdown(document[0], markdown, 1)
        assert diagnostics == ["pdf_math_emphasis_page_1"]
        assert "E = mc2" in cleaned
        assert "_E = mc2_" not in cleaned
        assert pmc.tokens_preserved(pmc.tokens_in_order(markdown), pmc.tokens_in_order(cleaned))
        assert "Texto normal de la columna derecha." in cleaned


def test_convert_gate_skips_documents_without_math_fonts(tmp_path):
    """The font gate leaves the span-based stages off for non-math documents.

    The marker-only pass always runs (as on main before the port), so the
    italic equation loses its markers anyway; what the gate must prevent is
    any span rebuild, glue split, compound restore or revert diagnostic.
    """
    file = tmp_path / "two-columns-equation.pdf"
    two_column_equation_pdf(file)
    settings = SimpleNamespace(normalized_max_bytes=20 * 1024 * 1024, extraction_max_pages=1000,
                               pdf_layout="legacy")
    result = convert(file, "pdf", settings, filename=file.name)
    assert "E = mc2" in result["markdown"]
    assert "Texto normal de la columna derecha." in result["markdown"]
    assert not any(d.startswith(("pdf_math_glue_space", "pdf_math_compound", "pdf_math_clean_reverted"))
                   for d in result["diagnostics"])
