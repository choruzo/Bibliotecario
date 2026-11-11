"""Emphasis-marker cleanup of math lines (marker-only, invariant-gated)."""
import re
from types import SimpleNamespace

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
    import pymupdf

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
