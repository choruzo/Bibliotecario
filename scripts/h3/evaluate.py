"""Run inside the API image with /tmp/h3/{docs,evaluation}; isolated disposable DB.

No document snippets or queries are printed/exported. Original corpus hashes are
checked before any conversion/indexing. Reports are written to /tmp/h3-report.json.
"""
import asyncio
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from bibliotecario.config import get_settings
from bibliotecario.converters import provenance
from bibliotecario.db import build_database
from bibliotecario.evaluation import calibrate, decision_metrics, ranking_metrics, summarize
from bibliotecario.indexing import build_index, finalize_index, model_signature
from bibliotecario.jobs import claim, enqueue
from bibliotecario.models import Document, DocumentVersion, EvidencePolicy, NormalizedRevision, Role, User, RetrievalRun
from bibliotecario.providers import ModelClients
from bibliotecario.retrieval import corpus_signature, retrieve
from bibliotecario.storage import storage_path


async def evaluate(settings, sessions, base):
    clients = ModelClients(settings)
    catalog = json.loads((base / "evaluation/h0/corpus_catalog.json").read_text())["documents"]
    questions_path = base / "evaluation/h0/questions.jsonl"
    cases = [json.loads(line) for line in questions_path.read_text().splitlines() if line.strip()]
    mapping, indexed, rows, traces = {}, [], [], []
    actor_id = str(uuid.uuid4())
    with sessions() as db:
        db.add(User(id=actor_id, username="h3-evaluation", password_hash="disabled", role="admin", active=False))
        db.commit()
    try:
        for item in catalog:
            source = base / item["path"]
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("corpus_hash_mismatch:" + item["id"])
            content = data.decode("utf-8-sig").replace("\r\n", "\n")
            did, vid, rid = [str(uuid.uuid4()) for _ in range(3)]
            key = f"normalized/{vid}/{rid}.md"
            target = storage_path(settings, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            metadata = {"title": item["id"], "visibility": "usuarios", "language": "es"}
            with sessions() as db:
                db.add(Document(id=did, title=item["id"], created_at=int(time.time())))
                db.flush()
                db.add(DocumentVersion(id=vid, document_id=did, number=1, status="requiere_revision",
                                       original_sha256=item["sha256"], metadata_json=metadata, created_at=int(time.time()), reviewed_at=int(time.time())))
                db.flush()
                revision = NormalizedRevision(id=rid, version_id=vid, number=1, storage_key=key,
                    sha256=hashlib.sha256(content.encode()).hexdigest(), provenance=provenance(content, "md"),
                    metadata_json=metadata, created_at=int(time.time()))
                db.add(revision)
                db.flush()
                db.get(DocumentVersion, vid).current_revision_id = rid
                db.get(DocumentVersion, vid).status = "indexando"
                enqueue(db, did, vid, actor_id, str(uuid.uuid4()), str(uuid.uuid4()), "index",
                        {"revision_id": rid, "active_version_id": None})
                db.commit()
                started = time.perf_counter()
                result = await build_index(settings, revision, clients)
            lease = claim(sessions, settings, "eval")
            if not finalize_index(sessions, settings, lease, result):
                raise ValueError("evaluation_index_failed")
            mapping[did] = item["id"]
            indexed.append({"id": item["id"], "chunks": len(result["chunks"]), "coverage_verified": result["coverage_verified"],
                            "latency_ms": round((time.perf_counter() - started) * 1000)})
            print("Indexed " + item["id"] + ": " + str(len(result["chunks"])) + " chunks", flush=True)
        for case in cases:
            row = {key: case[key] for key in ("id", "kind", "language", "expected_behavior")}
            if "conversation_id" in case:
                row["conversation_id"] = case["conversation_id"]
            with sessions() as db:
                try:
                    result = await retrieve(db, settings, clients, case["query"], admin=True)
                    traces.append({"case_id": case["id"], "result": result})
                    row.update(ranking_metrics(case, result["candidates"], mapping))
                    row["score"] = result["candidates"][0]["rerank_score"] if result["candidates"] else None
                    row["latency"] = result["latency"]
                    run = RetrievalRun(actor_id=actor_id, query=case["query"], status="completed", result=result, created_at=int(time.time()))
                    db.add(run)
                    db.commit()
                    row["run_id"] = run.id
                except Exception as exc:
                    db.rollback()
                    row["error"] = type(exc).__name__
            rows.append(row)
            print("Evaluated " + case["id"] + (": " + row["error"] if "error" in row else ""), flush=True)
        calibration = calibrate(rows)
        if any(row.get("error") for row in rows):
            calibration["approved"] = False
            calibration["reason"] = "evaluation_errors"
        with sessions() as db:
            corpus = corpus_signature(db)
            db.add(EvidencePolicy(signature=model_signature(settings), corpus_signature=corpus, report=calibration, created_at=int(time.time())))
            db.commit()
        report = {"date": datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat(), "format": "md", "query_mode": "raw_without_h4_reformulation",
                  "questions_sha256": hashlib.sha256(questions_path.read_bytes()).hexdigest(),
                  "model_signature": model_signature(settings), "corpus_signature": corpus,
                  "indexed": indexed, "cases": rows, "metrics": summarize(rows), "calibration": calibration,
                  "decision_metrics": decision_metrics(rows, calibration["threshold"] if calibration["approved"] else None),
                  "decisions_by_kind": {kind: decision_metrics([r for r in rows if r["kind"] == kind],
                      calibration["threshold"] if calibration["approved"] else None) for kind in sorted({r["kind"] for r in rows})},
                  "clarification_accuracy": 0, "ndcg_scope": "binary relevance within retrieved candidate pool",
                  "traces": "Recorded in isolated evaluation DB during run; sanitized case metrics exported"}
        Path("/tmp/h3-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        Path("/tmp/h3-traces.json").write_text(json.dumps(traces, ensure_ascii=False), encoding="utf-8")
    finally:
        await clients.close()


def main():
    original = get_settings()
    base = Path("/tmp/h3")
    # Separate database and file directory, no production documents or policies changed.
    name = "h3_eval_" + uuid.uuid4().hex[:12]
    admin_url = make_url(original.database_url.get_secret_value())
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    engine = None
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        url = admin_url.set(database=name).render_as_string(hide_password=False)
        env = os.environ | {"BIB_DATABASE_URL": url, "BIB_STORAGE_PATH": "/tmp/h3-storage"}
        result = subprocess.run(["alembic", "upgrade", "head"], env=env, capture_output=True)
        if result.returncode:
            raise RuntimeError("evaluation_migration_failed")
        settings = original.model_copy(update={"database_url": type(original.database_url)(url), "storage_path": Path("/tmp/h3-storage")})
        engine, sessions = build_database(settings)
        asyncio.run(evaluate(settings, sessions, base))
    finally:
        if engine:
            engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin_engine.dispose()


if __name__ == "__main__":
    main()
