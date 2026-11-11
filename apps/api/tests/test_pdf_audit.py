"""Pure content-loss audit (bibliotecario.pdf_audit): metric version 1.

Every category of the census gets a synthetic case (no corpus, no network) and
there is a control case: correctly converted text is not flagged at all. Pages
are duck-typed (the audit only uses ``get_text("dict")``, ``get_drawings()``,
``get_image_info()``, ``rect`` and ``number``), which keeps the font/encoding
surface of real PDFs out of the assertions.
"""
import json

from bibliotecario import pdf_audit as audit


def fake_page(number, lines, drawings=(), images=(), text=None):
    """A duck-typed PyMuPDF page: ``lines`` = [(text, (x0, y0, x1, y1), block_no)]."""
    blocks = {}
    for text_item, bbox, block_no in lines:
        block = blocks.setdefault(block_no, {"type": 0, "number": block_no,
                                             "bbox": list(bbox), "lines": []})
        block["lines"].append({"bbox": list(bbox), "spans": [{"text": text_item}]})
    class FakeRect:
        x0, y0, x1, y1 = 0, 0, 595, 842

        def get_area(self):
            return (self.x1 - self.x0) * (self.y1 - self.y0)

    class FakePage:
        def __init__(self):
            self.number = number
            self.rect = FakeRect()

        def get_text(self, kind="text"):
            if kind == "dict":
                return {"blocks": [blocks[key] for key in sorted(blocks)]}
            return text if text is not None else "\n".join(item for item, _, _ in lines)

        def get_drawings(self):
            return [{"rect": FakeRect2(rect)} for rect in drawings]

        def get_image_info(self):
            return [{"bbox": list(image)} for image in images]

    class FakeRect2:
        def __init__(self, values):
            self.x0, self.y0, self.x1, self.y1 = values

        @property
        def is_valid(self):
            return True

        @property
        def is_empty(self):
            return False

        def get_area(self):
            return (self.x1 - self.x0) * (self.y1 - self.y0)

    return FakePage()


def counts(page, markdown):
    """Full audit_page result (underscore-prefixed keys hold the evidence)."""
    return audit.audit_page(page, markdown)


def words_of(result, category):
    return result[category]["words"]


# --- normalization and tokenization -----------------------------------------

def test_normalize_joins_hyphen_breaks_and_casefolds():
    assert audit.normalize_text("Pre-\nTrain") == "pretrain"
    assert audit.normalize_text("Pre-\nTrain\r\ncolor") == "pretrain color"
    assert audit.normalize_text("  a\n\nb  ") == "a b"


def test_word_tokens_apply_nfkc_to_ligatures():
    assert audit.word_tokens("ﬁne tuning") == {"fine": 1, "tuning": 1}
    # a hyphenated break joins into one word (like the merged PDF lines)
    assert audit.word_tokens("ﬁne-\ntuning") == {"finetuning": 1}


def test_markdown_words_add_compound_forms_but_not_line_end_fragments():
    words = audit.markdown_words("pre-training y state-of-the-art\ncono-\ncido")
    assert words["pre"] == 1 and words["training"] == 1
    assert words["pretraining"] == 1
    assert words["stateoftheart"] == 1
    # the recovered fragment stays a fragment: production tokenization
    assert "cono" in words and "cido" in words and "conocido" not in words


def test_markdown_fragment_compounds_map_joined_words():
    compounds = audit.markdown_fragment_compounds("la transcrip-\ncion del modelo")
    assert compounds == {"transcripcion": "md:transcrip+cion=transcripcion"}


def test_symbol_tokens_cover_math_glyphs_only():
    assert audit.symbol_tokens("a ∑ √ ≤ ∈ ∂ b") == {"∑": 1, "√": 1, "≤": 1, "∈": 1, "∂": 1}
    assert audit.symbol_tokens("a = b < c") == {}  # ASCII math stays punctuation


# --- one case per category --------------------------------------------------

MD_BASE = "Texto base del documento convertido.\n\nSegundo parrafo presente."


def test_real_prose_flags_absent_long_lines():
    page = fake_page(0, [("Los zorros cafetean sobre perros dormidos hoy", (60, 100, 500, 110), 1)])
    result = counts(page, MD_BASE)
    assert result["real_prose"]["lines"] == 1
    assert result["real_prose"]["words"] == 7


def test_real_equation_flags_symbol_lines_half_missing():
    page = fake_page(0, [("x = ∑ (y + z) con q", (60, 100, 500, 110), 1)])
    result = counts(page, MD_BASE)
    # tokens: x y z q con (5 words, all absent) + symbols = + ∑ (2 absent) -> 7/7 >= 50 %
    assert result["real_equation"]["lines"] == 1
    assert result["real_equation"]["words"] == 5
    assert result["_evidence"]["real_equation"][0]["missing_symbols"]


def test_non_text_glyph_flags_symbol_only_lines():
    page = fake_page(0, [("∑ √ ≤ ∈", (60, 100, 500, 110), 1)])
    result = counts(page, MD_BASE)
    assert result["non_text_glyph"]["lines"] == 1
    assert result["non_text_glyph"]["words"] == 0


def test_figure_label_by_region_and_by_shortness():
    # inside a drawing region: a line of any length is a figure label
    page = fake_page(0, [("Etiqueta dentro del grafico dibujado", (60, 100, 300, 110), 1)],
                     drawings=[(50, 90, 320, 120)])
    result = counts(page, MD_BASE)
    assert result["figure_label"]["lines"] == 1
    # outside any region: <= 3 tokens without sentence punctuation
    page = fake_page(0, [("Etiqueta corta", (60, 100, 300, 110), 1)])
    result = counts(page, MD_BASE)
    assert result["figure_label"]["lines"] == 1


def test_reflow_flags_absent_sequences_with_present_multiset():
    markdown = "alpha epsilon beta zeta gamma delta y algo mas.\n\n" + MD_BASE
    page = fake_page(0, [("alpha beta gamma delta epsilon zeta", (60, 100, 500, 110), 1)])
    result = counts(page, markdown)
    assert result["reflow"]["lines"] == 1


def test_hyphen_fragment_counts_fragment_joins_on_raw_lines():
    markdown = "La transcripcion del modelo se registro.\n\n" + MD_BASE
    page = fake_page(0, [("la transcrip-", (60, 100, 500, 110), 1),
                         ("cion del modelo.", (60, 111, 500, 121), 1)])
    result = counts(page, markdown)
    # the joined logical line is present, so nothing is real loss...
    assert result["real_prose"]["lines"] == 0
    # ...but the raw fragments are the artifact the word counter sees
    assert result["hyphen_fragment"]["lines"] == 1
    assert result["hyphen_fragment"]["words"] == 2
    assert result["_evidence"]["hyphen_fragment"][0]["join"] == "transcrip+cion=transcripcion"


def test_hyphen_fragment_counts_markdown_side_fragments():
    # the markdown holds the word as fragments; the PDF line is joined
    markdown = "La transcrip-\ncion del modelo se registro.\n\n" + MD_BASE
    page = fake_page(0, [("la transcripcion del modelo.", (60, 100, 500, 110), 1)])
    result = counts(page, markdown)
    assert result["hyphen_fragment"]["lines"] == 1
    assert result["hyphen_fragment"]["words"] == 1
    assert result["_evidence"]["hyphen_fragment"][0]["join"].startswith("md:")


def test_duplicate_layer_counts_repeated_block_content():
    markdown = MD_BASE + "\n\nAviso legal repetido en la pagina."
    page = fake_page(0, [("Aviso legal repetido", (60, 100, 300, 110), 1),
                         ("Aviso legal repetido", (60, 200, 300, 210), 2)])
    result = counts(page, markdown)
    assert result["duplicate_layer"]["lines"] == 2
    assert result["duplicate_layer"]["words"] == 3  # (2 pdf - 1 md) * 3 tokens


def test_coverage_residual_reports_unattributed_multiset_surplus():
    # every line sequence is present in the markdown, but the page repeats the
    # year once more than the markdown rendering: the surplus has no line to
    # blame and the residual attributes it
    markdown = (MD_BASE + "\n\n| ano | valor |\n| --- | --- |\n| 1994 | uno |\n\n"
                "Entre 1994 y 1998 hubo finales.")
    page = fake_page(0, [("1994", (60, 100, 100, 110), 1),
                         ("1994", (60, 200, 100, 210), 2),
                         ("1994 y 1998", (60, 300, 200, 310), 3)])
    result = counts(page, markdown)
    assert result["coverage_residual"]["lines"] == 0
    assert result["coverage_residual"]["words"] == 1
    assert any(sample["token"] == "1994" for sample in result["_evidence"]["coverage_residual"])


def test_real_short_flags_punctuated_short_lines():
    page = fake_page(0, [("Zaragoza.", (60, 100, 300, 110), 1)])
    result = counts(page, MD_BASE)
    assert result["real_short"]["lines"] == 1


def test_correctly_converted_text_is_not_flagged():
    text = "Parrafo correctamente convertido al markdown de la pagina."
    page = fake_page(0, [(text, (60, 100, 500, 110), 1)])
    result = counts(page, text + "\n\n" + MD_BASE)
    for category in audit.CATEGORY_ORDER:
        assert result[category] == {"lines": 0, "words": 0}, category


def test_present_word_present_even_when_markdown_hyphenates_it():
    # the markdown compounds the word (pre-training) and the page carries the
    # joined form: the sequence matches through the variant stream, no loss
    markdown = "El modelo pre-training es comun.\n\n" + MD_BASE
    page = fake_page(0, [("el modelo pretraining es comun", (60, 100, 500, 110), 1)])
    result = counts(page, markdown)
    for category in audit.CATEGORY_ORDER:
        assert result[category] == {"lines": 0, "words": 0}, category


# --- aggregation and determinism --------------------------------------------

def test_logical_lines_merge_hyphenated_breaks_and_record_joins():
    raw = [audit.RawLine(text="la representa-", bbox=(0, 0, 100, 10), number=0),
           audit.RawLine(text="tion final.", bbox=(0, 11, 100, 21), number=1)]
    logical = audit._logical_lines(raw)
    assert len(logical) == 1
    assert "representation" in logical[0].words
    assert logical[0].joins == [("representa", "tion")]


def test_audit_document_aggregates_pages_and_carries_version():
    page_a = fake_page(0, [("Los zorros cafetean sobre perros dormidos hoy", (60, 100, 500, 110), 1)])
    page_b = fake_page(1, [("∑ √ ≤ ∈", (60, 100, 500, 110), 1)])
    markdowns = {0: MD_BASE, 1: MD_BASE}
    verdict = audit.audit_document([page_a, page_b], markdowns, filename="ficticio.pdf")
    assert verdict["metric_version"] == audit.METRIC_VERSION
    assert verdict["pages"] == 2
    assert verdict["real_prose"]["lines"] == 1
    assert verdict["non_text_glyph"]["lines"] == 1
    assert verdict["equation_lines_total"] == 1  # the symbol-only line carries operator glyphs
    assert len(verdict["per_page"]) == 2
    assert verdict["samples"]["real_prose"]


def test_audit_page_is_deterministic():
    page = fake_page(0, [("la transcrip-", (60, 100, 500, 110), 1),
                         ("cion del modelo.", (60, 111, 500, 121), 1),
                         ("Aviso repetido", (60, 200, 300, 210), 2),
                         ("Aviso repetido", (60, 300, 300, 310), 3)])
    markdown = "La transcripcion del modelo.\n\nAviso repetido en el texto."
    first = audit.audit_page(page, markdown)
    second = audit.audit_page(page, markdown)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
