import time
import pytest
from sqlalchemy import select

from test_h1 import application, login  # noqa: F401
from test_h2 import upload, complete, headers
from bibliotecario.chunking import split_blocks
from bibliotecario.converters import provenance
from bibliotecario.evaluation import calibrate, ranking_metrics, decision_metrics
from bibliotecario.indexing import finalize_index, model_signature
from bibliotecario.jobs import claim, fail, finish_cancel
from bibliotecario.models import Chunk, Document, DocumentVersion, RetrievalRun
from bibliotecario.retrieval import fuse, corpus_signature
from bibliotecario.sufficiency import policy_signature, VERSION


def reviewed(application, content=b"# Titulo\n\nTexto original.\n", path="/admin/documents"):
    app, client, sessions = application
    data = upload(client, content=content, path=path).json()
    complete(app, sessions, data)
    version = client.get(f"/admin/documents/{data['document']['id']}").json()["versions"][0]
    assert client.post(f"/admin/versions/{version['id']}/review", json={"expected_revision_id": version["revision_id"]}, headers=headers(client)).status_code == 200
    return data["document"]["id"], version


def queue(application, version):
    app, client, sessions = application
    response = client.post(f"/admin/versions/{version['id']}/publish", json={"expected_revision_id": version["revision_id"]}, headers=headers(client))
    assert response.status_code == 202, response.text
    lease = claim(sessions, app.state.settings, "index-worker")
    revision = client.get(f"/admin/versions/{version['id']}/normalized").json()
    chunks = split_blocks(revision["markdown"], revision["provenance"])
    result = {"revision_id": revision["revision_id"], "sha256": revision["sha256"], "model_signature": model_signature(app.state.settings),
              "chunks": [c | {"embedding": [0.1] * 768} for c in chunks]}
    return lease, result, response.json()["id"]


def test_chunks_preserve_unicode_content_structure_and_pages():
    markdown = "# Encabezado\n\n" + "á中🙂" * 1000 + "\n\n```python\nx = 1\n```\n"
    source = provenance(markdown, "pdf", page=3)
    chunks = split_blocks(markdown, source)
    assert all(len(c["search_content"].encode()) <= 900 for c in chunks)
    assert "".join(c["content"] for c in chunks).replace("\n", "") == markdown.replace("\n", "")
    assert all(c["provenance"] and c["provenance"][0]["page"] == 3 for c in chunks)
    assert chunks[-1]["content"].startswith("```python")


def test_unmapped_html_is_preserved_as_inert_normalized_text():
    markdown = "# Tema\n\nTexto.\n\n<div>Contenido HTML sin ejecutar</div>\n\n## Siguiente\n\nFinal.\n"
    chunks = split_blocks(markdown, provenance(markdown, "md"))
    assert ''.join(''.join(c['content'] for c in chunks).split()) == ''.join(markdown.split())
    html = next(c for c in chunks if '<div>' in c['content'])
    assert html['provenance'][0]['origin'] == 'normalized'
    assert html['provenance'][0]['page'] is None


def test_publish_requires_review_and_admin(application):
    app, client, sessions = application
    login(client)
    data = upload(client).json()
    complete(app, sessions, data)
    version = client.get(f"/admin/documents/{data['document']['id']}").json()["versions"][0]
    assert client.post(f"/admin/versions/{version['id']}/publish", json={"expected_revision_id": version["revision_id"]}, headers=headers(client)).status_code == 409
    login(client, "lector")
    assert client.post("/admin/retrieval/search", json={"query": "texto"}, headers=headers(client)).status_code == 403
    assert client.get("/admin/retrieval/runs").status_code == 403


def test_atomic_replacement_failed_index_and_stale_lease(application):
    app, client, sessions = application
    login(client)
    did, first = reviewed(application)
    lease, result, _ = queue(application, first)
    assert finalize_index(sessions, app.state.settings, lease, result)
    did, second = reviewed(application, b"# Nueva\n\nVersion nueva.\n", f"/admin/documents/{did}/versions")
    lease2, result2, _ = queue(application, second)
    with sessions() as db:
        assert db.get(Document, did).active_version_id == first["id"]
    bad = result2 | {"chunks": [result2["chunks"][0] | {"embedding": [0.1] * 767}]}
    with pytest.raises(Exception, match="invalid_embedding"):
        finalize_index(sessions, app.state.settings, lease2, bad)
    with sessions() as db:
        assert db.get(Document, did).active_version_id == first["id"]
        assert not db.scalars(select(Chunk).where(Chunk.version_id == second["id"])).all()
    assert finalize_index(sessions, app.state.settings, lease2, result2)
    with sessions() as db:
        assert db.get(Document, did).active_version_id == second["id"]
        assert db.get(DocumentVersion, first["id"]).status == "retirado"
    assert not finalize_index(sessions, app.state.settings, lease2, result2)


def test_withdraw_during_reindex_cannot_republish(application):
    app, client, sessions = application
    login(client)
    did, version = reviewed(application)
    lease, result, _ = queue(application, version)
    finalize_index(sessions, app.state.settings, lease, result)
    lease2, result2, _ = queue(application, version)
    assert client.post(f"/admin/documents/{did}/withdraw", headers=headers(client)).status_code == 200
    with pytest.raises(ValueError, match="snapshot_changed"):
        finalize_index(sessions, app.state.settings, lease2, result2)
    fail(sessions, lease2, "snapshot_changed", permanent=True)
    with sessions() as db:
        assert db.get(Document, did).active_version_id is None
        assert db.get(DocumentVersion, version["id"]).status == "retirado"


def test_cancel_index_has_no_partial_vectors(application):
    app, client, sessions = application
    login(client)
    did, version = reviewed(application)
    lease, result, jid = queue(application, version)
    assert client.post(f"/admin/jobs/{jid}/cancel", headers=headers(client)).status_code == 200
    assert not finalize_index(sessions, app.state.settings, lease, result)
    finish_cancel(sessions, lease)
    with sessions() as db:
        assert db.get(Document, did).active_version_id is None
        assert db.get(DocumentVersion, version["id"]).status == "requiere_revision"
        assert not db.scalars(select(Chunk)).all()


def test_failed_index_can_retry_and_reindex_stays_published(application):
    app, client, sessions = application
    login(client)
    did, version = reviewed(application)
    lease, result, jid = queue(application, version)
    fail(sessions, lease, "model_unavailable", permanent=True)
    response = client.post(f"/admin/jobs/{jid}/retry", headers=headers(client))
    assert response.status_code == 200
    retry_lease = claim(sessions, app.state.settings, "retry-worker")
    assert finalize_index(sessions, app.state.settings, retry_lease, result)
    lease2, result2, _ = queue(application, version)
    with sessions() as db:
        assert db.get(DocumentVersion, version["id"]).status == "publicado"
        assert db.get(Document, did).active_version_id == version["id"]
    assert finalize_index(sessions, app.state.settings, lease2, result2)


def test_fusion_deduplicates_and_keeps_channel_scores():
    fused = fuse([{"id": "a", "score": .9}, {"id": "b", "score": .8}], [{"id": "b", "score": .6}])
    assert [c[0] for c in fused] == ["b", "a"]
    assert set(fused[0][2]) == {"vector", "text"}


def test_calibration_rejects_overlap_and_preserves_conversation_groups():
    rows = [{"id": f"A{i}", "kind": "answerable", "expected_behavior": "answer", "score": .9, "recall10": 1} for i in range(4)]
    rows += [{"id": f"U{i}", "kind": "unanswerable", "expected_behavior": "abstain", "score": .95, "recall10": None} for i in range(4)]
    assert not calibrate(rows)["approved"]
    for row in rows[4:]:
        row["score"] = .1
    report = calibrate(rows)
    assert report["approved"] and report["threshold"] == .9
    assert not set(report["train_ids"]) & set(report["holdout_ids"])
    rows += [{"id": f"C{i}", "conversation_id": "CONV", "kind": "conversation", "expected_behavior": "answer", "score": .9, "recall10": 1} for i in range(3)]
    report = calibrate(rows)
    assert all(f"C{i}" in report["train_ids"] for i in range(3))


def test_locator_recall_penalizes_missing_sections_and_duplicates():
    case = {"expected_documents": ["DOC"], "expected_sections": ["Uno", "Dos"]}
    candidates = [{"document_id": "d", "provenance": [{"section_path": ["Uno"]}]}] * 10
    result = ranking_metrics(case, candidates, {"d": "DOC"})
    assert result["recall10"] == pytest.approx(2 / 3)
    assert result["mrr10"] == 1
    assert decision_metrics([{"expected_behavior": "abstain", "score": .9}], .8)["fp"] == 1


def test_calibration_endpoint_uses_recorded_traces_and_rejects_stale_models(application):
    app, client, sessions = application
    login(client)
    cases = []
    with sessions() as db:
        corpus = corpus_signature(db)
        for kind, count in (("answerable", 10), ("unanswerable", 5), ("ambiguous", 3), ("conversation", 6)):
            for i in range(count):
                score = .9 if kind in {"answerable", "conversation"} else .1
                candidate = {"document_id": "document", "provenance": [{"section_path": ["Tema"]}], "rerank_score": score}
                run = RetrievalRun(query=f"synthetic-{kind}-{i}", status="completed", created_at=int(time.time()),
                    result={"corpus_signature": corpus, "model_signature": policy_signature(app.state.settings),
                            "assessment": {"version": VERSION, "action": "answer" if score == .9 else "clarify" if kind == "ambiguous" else "abstain", "reason": "evidence_assessed"},
                            "scope": {"admin": True, "document_id": None}, "candidates": [candidate], "latency": {}})
                db.add(run)
                db.flush()
                cases.append({"id": f"{kind}-{i}", "kind": kind, "run_id": run.id,
                              "expected_documents": ["document"] if score == .9 else [],
                              "expected_sections": ["Tema"] if score == .9 else [],
                              "conversation_id": f"conv-{i // 3}" if kind == "conversation" else None})
        db.commit()
    assert client.get("/admin/retrieval/policy").json()["report"]["reason"] == "uncalibrated"
    response = client.post("/admin/retrieval/calibrate", json={"cases": cases}, headers=headers(client))
    assert response.status_code == 200, response.text
    assert response.json()["report"]["approved"]
    assert client.get("/admin/retrieval/policy").json()["report"]["threshold"] == .9
    app.state.settings.reranker_model = "changed-model"
    assert client.get("/admin/retrieval/policy").json()["report"]["reason"] == "uncalibrated"
    assert client.post("/admin/retrieval/calibrate", json={"cases": cases}, headers=headers(client)).status_code == 409
