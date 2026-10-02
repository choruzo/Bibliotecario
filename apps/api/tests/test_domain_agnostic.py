"""Regressions found by ingesting a domain-agnostic PDF (Apis mellifera)."""
import asyncio
import json
import re
from types import SimpleNamespace

import pytest

from test_h1 import application, login, settings  # noqa: F401
from bibliotecario.chat import contextual_query, extractive_answer, numbers, validate_answer
from bibliotecario.chunking import split_blocks
from bibliotecario.converters import convert, provenance
from bibliotecario.evaluation import calibrate
from bibliotecario.models import Document, DocumentVersion, EvidencePolicy
from bibliotecario.query import missing_terms
from bibliotecario.retrieval import corpus_members, corpus_signature, evidence_decision
from bibliotecario.sufficiency import VERSION, policy_signature


def table_pdf(path):
    import pymupdf
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 60), "Ciclo de desarrollo de las castas.")
    header = ["Tipo", "Huevo", "Larva", "Pupa", "Total"]
    rows = [["Reina", "3 días", "5½ días", "8 días", "16 días"],
            ["Zángano", "3 días", "6½ días", "14½ días", "24 días"]]
    x = [72, 150, 230, 310, 390, 470]
    for r, values in enumerate([header] + rows):
        y = 90 + r * 20
        for c, value in enumerate(values):
            page.draw_rect((x[c], y, x[c + 1], y + 20))
            page.insert_text((x[c] + 4, y + 14), value)
    page.insert_text((72, 200), "Texto posterior a la tabla.")
    pdf.save(path)
    pdf.close()


ZANGANO = r"\|\s*Zángano\s*\|\s*3 días\s*\|\s*6½ días\s*\|\s*14½ días\s*\|\s*24 días\s*\|"


@pytest.mark.parametrize("drop_tables", [False, True])
def test_pdf_tables_are_kept_with_row_and_column_correspondence(tmp_path, monkeypatch, drop_tables):
    import pymupdf4llm
    file = tmp_path / "castas.pdf"
    table_pdf(file)
    if drop_tables:
        real = pymupdf4llm.to_markdown
        # The legacy layout mode dropped the Apis mellifera tables without any diagnostic.
        monkeypatch.setattr(pymupdf4llm, "to_markdown", lambda document, **kwargs: [
            chunk | {"text": "\n".join(line for line in chunk["text"].splitlines() if not line.startswith("|"))}
            for chunk in real(document, **kwargs)])
    result = convert(file, "pdf", settings(tmp_path))
    markdown = result["markdown"]
    assert re.search(ZANGANO, markdown), markdown
    assert markdown.count("14½") == 1
    assert ("pdf_tables_recovered_page_1" in result["diagnostics"]) is drop_tables
    assert "Texto posterior a la tabla." in markdown
    assert not any(code.startswith("pdf_text_loss_page_") for code in result["diagnostics"])
    assert all(locator["page"] == 1 for locator in result["provenance"])


def test_dropped_pdf_text_is_recovered_and_reported(tmp_path, monkeypatch):
    import pymupdf
    import pymupdf4llm
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Primer parrafo convertido correctamente.")
    page.insert_text((72, 300), "La abeja de la miel poliniza la flor de la rabina")
    file = tmp_path / "caption.pdf"
    pdf.save(file)
    pdf.close()
    real = pymupdf4llm.to_markdown

    def lossy(document, **kwargs):
        # Simulates the layout conversion silently dropping a caption.
        return [chunk | {"text": chunk["text"].replace("La abeja de la miel poliniza la flor de la rabina", "")}
                for chunk in real(document, **kwargs)]
    monkeypatch.setattr(pymupdf4llm, "to_markdown", lossy)
    result = convert(file, "pdf", settings(tmp_path))
    assert "La abeja de la miel poliniza la flor de la rabina" in result["markdown"]
    assert "pdf_text_recovered_page_1" in result["diagnostics"]
    assert result["markdown"].count("Primer parrafo convertido correctamente.") == 1


def test_chunks_break_at_words_and_never_inside_links():
    link = "[jalea real](https://es.wikipedia.org/wiki/Jalea_(alimento))"
    paragraph = " ".join(f"palabra{i} {link} continuación" for i in range(60))
    markdown = "# Alimentación\n\n" + paragraph + "\n"
    chunks = split_blocks(markdown, provenance(markdown, "md"))
    assert len(chunks) > 3
    assert ''.join(''.join(c['content'] for c in chunks).split()) == ''.join(markdown.split())
    for first, second in zip(chunks, chunks[1:]):
        assert not (first["content"][-1:].isalnum() and second["content"][:1].isalnum())
    for chunk in chunks:
        assert all(len(c["search_content"].encode()) <= 900 for c in chunks)
        text = chunk["content"]
        assert text.count("[") == text.count("](") == text.count("_(alimento))"), text


def test_small_blocks_of_one_section_are_grouped_with_all_locators():
    rows = "".join(f"Artículo {i}. Texto breve del artículo número {i}.\n\n" for i in range(1, 41))
    markdown = "# Título\n\n" + rows + "## Otra sección\n\nFinal.\n"
    pages = [provenance(markdown, "pdf", page=1)[0]] + [
        item | {"page": 1 + i // 20, "kind": "page"} for i, item in enumerate(provenance(markdown, "pdf", page=1)[1:])]
    chunks = split_blocks(markdown, pages)
    assert ''.join(''.join(c['content'] for c in chunks).split()) == ''.join(markdown.split())
    assert all(len(c["search_content"].encode()) <= 900 for c in chunks)
    assert len(chunks) < 10
    body = [c for c in chunks if "Artículo" in c["content"]]
    assert all(c["content"].rstrip().endswith(".") for c in body)
    assert sum(len(c["provenance"]) for c in body) >= 40
    assert {p["page"] for c in body for p in c["provenance"]} == {1, 2}
    # A new section never shares a fragment with the previous one.
    assert chunks[-1]["content"].startswith("## Otra sección")
    assert all("Artículo" not in c["content"] for c in chunks if "Otra sección" in c["content"])


def test_table_of_contents_links_are_not_grouped_into_one_fragment():
    toc = "".join(f"[Apartado {i} {i + 1}](#_Toc{i})\n\n" for i in range(8))
    markdown = "Guía\n\nContenido\n\n" + toc + "# Apartado 0\n\nTexto.\n"
    chunks = split_blocks(markdown, provenance(markdown, "md"))
    assert ''.join(''.join(c['content'] for c in chunks).split()) == ''.join(markdown.split())
    assert all(c["content"].count("](#") <= 1 for c in chunks)
    assert chunks[0]["content"].startswith("Guía") and "Contenido" in chunks[0]["content"]


def test_numbers_are_recognised_as_digits_words_and_fractions():
    assert numbers("veintiún días, 5½ días y treinta y dos") >= {21, 5.5, 32}
    assert numbers("de dos a cuatro años") == {2, 4}
    assert numbers("una semana") == set()


def source(quote, marker="C1"):
    return {"citation_id": marker, "quote": quote, "title": "Abeja", "document_id": "d",
            "locator": {"section_path": ["Ciclo"]}}


@pytest.mark.parametrize("explanation,general", [
    ("La reina vive de dos a cuatro años.", ""),
    ("La pupa dura una semana (casi 7 días).", ""),
    ("La reina vive unos tres años.", "Las reinas suelen vivir de dos a cuatro años."),
])
def test_explanations_cannot_add_figures_absent_from_the_passages(explanation, general):
    sources = [source("La reina vive tres años; la pupa dura aproximadamente una semana.")]
    raw = json.dumps({"evidence": [{"citation_id": "C1", "quote": sources[0]["quote"], "explanation": explanation}],
                      "general": general})
    with pytest.raises(ValueError, match="unsupported_number"):
        validate_answer(raw, sources)
    text, used, _ = extractive_answer(sources)
    assert "dos a cuatro" not in text and "7 días" not in text and used


def test_faithful_explanations_with_restated_figures_are_accepted():
    sources = [source("El periodo de desarrollo es de veintiún días para las obreras.")]
    raw = json.dumps({"evidence": [{"citation_id": "C1", "quote": sources[0]["quote"],
                                    "explanation": "Las obreras tardan 21 días en desarrollarse."}], "general": ""})
    assert validate_answer(raw, sources)[0].startswith("Las obreras tardan 21 días")


def test_partial_locators_do_not_move_the_threshold_but_wrong_documents_do():
    def row(i, kind, score, eligible, split, **extra):
        return {"id": f"{kind}{i}", "kind": kind, "score": score, "answer_eligible": eligible, "split": split,
                "expected_behavior": {"answerable": "answer", "unanswerable": "abstain"}[kind],
                "recall10": 1, "document_recall10": 1} | extra
    rows = [row(i, "answerable", -1 + i, True, split) for i in range(4) for split in ("calibration", "validation")]
    rows += [row(i, "unanswerable", -5, False, split, recall10=None, document_recall10=None)
             for i in range(3) for split in ("calibration", "validation")]
    for i, r in enumerate(rows):
        r["id"] += r["split"]
    baseline = calibrate(rows)
    rows[0]["recall10"] = 2 / 3  # correct document, one expected section missing
    noisy = calibrate(rows)
    assert baseline["approved"] and noisy["approved"]
    assert noisy["threshold"] == baseline["threshold"] == -1
    assert noisy["accepted_locator_recall10"] < 1
    rows[0]["document_recall10"] = 0  # answered from the wrong document
    assert calibrate(rows)["threshold"] > -1


def test_new_documents_inherit_the_approved_policy_but_changed_ones_do_not(application):
    app, client, sessions = application
    assessment = {"version": VERSION, "action": "answer", "reason": "evidence_assessed"}
    with sessions() as db:
        members = {"doc-a": ["ver-a", "usuarios"]}
        db.add(EvidencePolicy(scope="admin", signature=policy_signature(app.state.settings), corpus_signature="old",
                              report={"approved": True, "threshold": 0.5, "corpus_members": members}, created_at=0))
        db.commit()
        corpus = corpus_signature(db)
        decision = evidence_decision(db, app.state.settings, corpus, [{"rerank_score": 0.9}], admin=True,
                                     assessment=assessment)
        assert decision["action"] == "answer" and decision["policy_inherited"] is True
        assert evidence_decision(db, app.state.settings, corpus, [{"rerank_score": 0.1}], admin=True,
                                 assessment=assessment)["action"] == "abstain"
        assert evidence_decision(db, app.state.settings, corpus, [{"rerank_score": 0.9}], admin=False,
                                 assessment=assessment)["reason"] == "uncalibrated"
        db.add(Document(id="doc-a", title="A", created_at=0))
        db.flush()
        db.add(DocumentVersion(id="ver-b", document_id="doc-a", number=2, status="publicado", original_sha256="0" * 64,
                               metadata_json={"title": "A", "visibility": "usuarios"}, created_at=0))
        db.flush()
        db.get(Document, "doc-a").active_version_id = "ver-b"
        db.commit()
        assert corpus_members(db)["doc-a"] == ["ver-b", "usuarios"]
        assert evidence_decision(db, app.state.settings, corpus, [{"rerank_score": 0.9}], admin=True,
                                 assessment=assessment)["reason"] == "uncalibrated"


def test_follow_up_rewrites_keep_the_new_subject_and_use_the_last_question():
    class Clients:
        settings = SimpleNamespace(sufficiency_reasoning_effort="low")

        def __init__(self, answers):
            self.answers, self.calls = list(answers), []

        async def generate(self, messages, **kwargs):
            self.calls.append(messages)
            return self.answers.pop(0)
    recent = [{"role": "user", "content": "¿Quién clasificó a la abeja europea?", "references": []},
              {"role": "assistant", "content": "Linneo " * 400, "references": []},
              {"role": "user", "content": "¿Cuántos días tarda en desarrollarse una abeja obrera?", "references": []},
              {"role": "assistant", "content": "Veintiún días.", "references": []}]
    good = "¿Cuántos días tarda en desarrollarse una abeja reina?"
    clients = Clients(["¿Quién clasificó a la abeja europea?", good])
    assert asyncio.run(contextual_query(clients, "¿Y la reina?", "", recent)) == good
    payload = json.loads(clients.calls[0][1]["content"])
    assert payload["last_user_question"] == recent[2]["content"]
    assert len(payload["recent"][1]["content"]) <= 300
    assert "reina" in clients.calls[1][-1]["content"]
    clients = Clients(["¿Quién clasificó a la abeja europea?"] * 3)
    assert asyncio.run(contextual_query(clients, "¿Y la reina?", "", recent)) == "¿Y la reina?"
    # An echoed elliptical follow-up is retried with the previous question's topic.
    clients = Clients(["¿Y la reina?", good])
    assert asyncio.run(contextual_query(clients, "¿Y la reina?", "", recent)) == good
    assert "obrera" in clients.calls[1][-1]["content"]
    clients = Clients(["Resuelve únicamente referentes explícitos del historial: ¿Cuánto vive?",
                       "¿Cuánto vive una abeja obrera?"])
    assert asyncio.run(contextual_query(clients, "¿Cuánto vive?", "", recent)) == "¿Cuánto vive una abeja obrera?"
    # A self-contained question may legitimately stay unchanged.
    clients = Clients(["¿Cómo se instala Git en Windows?"])
    assert asyncio.run(contextual_query(clients, "¿Cómo se instala Git en Windows?", "", recent)) == "¿Cómo se instala Git en Windows?"
    assert missing_terms("los zánganos pican?", "¿Pican los zánganos?") == []


def test_library_titles_cannot_supply_a_missing_referent():
    from bibliotecario.query import requires_specific_context
    assert requires_specific_context("Necesito cambiar sus parámetros, ¿por dónde empiezo?")
    assert requires_specific_context("¿Qué hago con esto?")
    assert not requires_specific_context("¿Cómo configuro el switch con su consola?")
    assert not requires_specific_context("los zánganos pican?")


@pytest.mark.parametrize("question,rewrite", [
    ("En ese documento, ¿cómo se exporta?", "¿Cómo se exporta en DOORS?"),
    ("En esa misma guía, ¿cómo se configura la VM Ubuntu para usar su propio DNS?",
     "¿Cómo se configura la VM Ubuntu para usar un DNS propio según la documentación del entorno VMware?"),
    ("¿Y qué viene inmediatamente después?", "¿Qué fase sigue a la instalación en la entrega de un GTR?"),
])
def test_resolved_references_are_not_reported_as_missing_terms(question, rewrite):
    assert missing_terms(question, rewrite) == []
    assert missing_terms("¿Y la reina?", "¿Quién clasificó a la abeja europea?") == ["reina"]
