"""PDF conversion recovery and selectable converter strategies."""
import importlib.util
import sys
from types import SimpleNamespace

from bibliotecario import converters
from bibliotecario.config import Settings
from bibliotecario.converters import convert, recover_pdf_page


def pdf_settings(**changes):
    """The Settings attributes read by convert()/validate_file() for PDFs."""
    values = dict(normalized_max_bytes=20 * 1024 * 1024, extraction_max_pages=1000,
                  pdf_layout="legacy")
    return SimpleNamespace(**(values | changes))


def two_column_pdf(path):
    import pymupdf

    pdf = pymupdf.open()
    page = pdf.new_page()
    left = "\n".join(f"Columna izquierda linea {n}." for n in range(1, 9))
    right = "\n".join(f"Columna derecha linea {n}." for n in range(1, 9))
    page.insert_textbox(pymupdf.Rect(60, 60, 280, 420), left, fontsize=11)
    page.insert_textbox(pymupdf.Rect(320, 60, 540, 420), right, fontsize=11)
    pdf.save(path)
    pdf.close()


class FakeTables:
    def __init__(self, tables):
        self.tables = tables


class FakeRow:
    def __init__(self, cells):
        self.cells = cells
        self.bbox = (min(c[0] for c in cells), min(c[1] for c in cells),
                     max(c[2] for c in cells), max(c[3] for c in cells))


class FakeTable:
    def __init__(self, bbox, rows):
        self.bbox = bbox
        self.rows = rows


class FakePage:
    """Minimal page surface used by recover_pdf_page() and pdf_table_markdown()."""

    def __init__(self, number, blocks, text, tables=None, words=None, textboxes=None):
        self.number = number
        self._blocks = blocks
        self._text = text
        self._tables = tables or []
        self._words = words or []
        self._textboxes = textboxes or {}
        self.find_tables_calls = 0

    def get_text(self, kind="text", clip=None):
        if kind == "blocks":
            return list(self._blocks)
        if kind == "words":
            if clip is None:
                return list(self._words)
            return [word for word in self._words
                    if clip[0] <= (word[0] + word[2]) / 2 <= clip[2]
                    and clip[1] <= (word[1] + word[3]) / 2 <= clip[3]]
        return self._text

    def get_textbox(self, bbox):
        return self._textboxes.get(tuple(bbox), "")

    def find_tables(self):
        self.find_tables_calls += 1
        return FakeTables(self._tables)


def words(*items):
    """(text, x0, y0) -> PyMuPDF-like word tuples."""
    result = []
    for index, (text, x0, y0) in enumerate(items):
        result.append((x0, y0, x0 + len(text) * 4, y0 + 8, text, 0, index, 0))
    return result


def test_clean_page_skips_table_detection():
    text = "Texto que ya está convertido."
    page = FakePage(0, [(0, 0, 200, 10, text, 0, 0)], text)
    leading, trailing, diagnostics = recover_pdf_page(page, text)
    assert page.find_tables_calls == 0
    assert (leading, trailing, diagnostics) == ([], [], [])


def test_lost_text_page_is_recovered_and_still_reports_diagnostics():
    markdown = "# Título\n\nTexto convertido.\n"
    page = FakePage(0, [(0, 0, 200, 10, "Texto convertido.", 0, 0),
                        (0, 10, 200, 20, "Una línea perdida por completo.", 0, 0)],
                    "Texto convertido.\nUna línea perdida por completo.")
    leading, trailing, diagnostics = recover_pdf_page(page, markdown)
    assert page.find_tables_calls == 1
    assert diagnostics == ["pdf_text_recovered_page_1"]
    assert "Una línea perdida por completo." in trailing


def test_lost_table_page_is_rebuilt_and_still_reports_diagnostics():
    markdown = "# Tabla\n\nEsta página perdió la tabla entera.\n"
    cells = [(0, 0, 100, 10), (100, 0, 200, 10)]
    rows = [FakeRow(cells), FakeRow([(0, 10, 100, 20), (100, 10, 200, 20)]),
            FakeRow([(0, 20, 100, 30), (100, 20, 200, 30)])]
    table = FakeTable((0, 0, 200, 30), rows)
    page = FakePage(0, [(0, 0, 200, 30, "Nombre Valor\nAlfa 1\nBeta 2", 0, 0)],
                    "Nombre Valor\nAlfa 1\nBeta 2",
                    tables=[table],
                    words=words(("Nombre", 0, 0), ("Valor", 100, 0),
                                ("Alfa", 0, 10), ("1", 100, 10),
                                ("Beta", 0, 20), ("2", 100, 20)),
                    textboxes={(0, 0, 100, 10): "Nombre", (100, 0, 200, 10): "Valor",
                               (0, 0, 200, 30): "Nombre Valor Alfa 1 Beta 2"})
    leading, trailing, diagnostics = recover_pdf_page(page, markdown)
    assert page.find_tables_calls == 1
    assert diagnostics == ["pdf_tables_recovered_page_1"]
    rebuilt = "\n".join(leading + trailing)
    assert "| Nombre | Valor |" in rebuilt
    assert "| Alfa | 1 |" in rebuilt
    assert "| Beta | 2 |" in rebuilt


def test_document_scan_calls_find_tables_only_on_lossy_pages():
    clean_text = "Texto que ya está convertido."
    clean = FakePage(0, [(0, 0, 200, 10, clean_text, 0, 0)], clean_text)
    lossy = FakePage(1, [(0, 0, 200, 10, "Texto convertido.", 0, 0),
                         (0, 10, 200, 20, "Una línea perdida por completo.", 0, 0)],
                     "Texto convertido.\nUna línea perdida por completo.")
    pages = [clean, lossy]
    for page, markdown in zip(pages, [clean_text, "# Título\n\nTexto convertido.\n"]):
        recover_pdf_page(page, markdown)
    # The old implementation scanned every page of the document (2 calls).
    assert clean.find_tables_calls == 0
    assert sum(page.find_tables_calls for page in pages) == 1


def test_pdf_layout_setting_defaults_to_legacy(tmp_path, monkeypatch):
    values = dict(environment="test", database_url="sqlite://", storage_path=tmp_path,
                  llm_api_key="test-secret", embedding_dimensions=3)
    assert Settings(_env_file=None, **values).pdf_layout == "legacy"
    monkeypatch.setenv("BIB_PDF_LAYOUT", "layout")
    assert Settings(_env_file=None, **values).pdf_layout == "layout"


def test_default_setting_does_not_change_the_conversion(tmp_path):
    file = tmp_path / "two-columns.pdf"
    two_column_pdf(file)
    implicit = convert(file, "pdf", pdf_settings())
    explicit = convert(file, "pdf", pdf_settings(pdf_layout="legacy"))
    assert implicit["pdf_layout"] == "legacy"
    assert implicit["sha256"] == explicit["sha256"]
    assert implicit["markdown"] == explicit["markdown"]
    assert implicit["diagnostics"] == explicit["diagnostics"]


def test_missing_layout_extra_falls_back_to_legacy(tmp_path, monkeypatch):
    file = tmp_path / "two-columns.pdf"
    two_column_pdf(file)
    # ``None`` in sys.modules makes ``import pymupdf.layout`` raise ImportError,
    # which is exactly what happens when the optional extra is not installed.
    monkeypatch.setitem(sys.modules, "pymupdf.layout", None)
    result = convert(file, "pdf", pdf_settings(pdf_layout="layout"))
    assert result["pdf_layout"] == "legacy"
    assert "pdf_layout_unavailable" in result["diagnostics"]
    assert result["sha256"] == convert(file, "pdf", pdf_settings())["sha256"]


def test_layout_strategy_converts_a_small_pdf(tmp_path):
    if importlib.util.find_spec("pymupdf.layout") is None:
        import pytest

        pytest.skip("optional pymupdf-layout extra is not installed")
    file = tmp_path / "two-columns.pdf"
    two_column_pdf(file)
    result = convert(file, "pdf", pdf_settings(pdf_layout="layout"))
    assert result["pdf_layout"] == "layout"
    assert "pdf_layout_unavailable" not in result["diagnostics"]
    assert result["provenance"][0]["page"] == 1
    for expected in ("Columna izquierda linea 1.", "Columna izquierda linea 8.",
                     "Columna derecha linea 1.", "Columna derecha linea 8."):
        assert expected in result["markdown"]
    # A two-column layout read in order keeps the left column before the right.
    assert (result["markdown"].index("Columna izquierda linea 8.")
            < result["markdown"].index("Columna derecha linea 1."))
