import hashlib
import json
import time
from typing import Literal
from time import perf_counter

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from .auth import administrator, database, require_csrf
from .indexing import model_signature
from .models import Chunk, Document, DocumentVersion, EvidencePolicy, RetrievalRun
from .providers import ProviderError
from .evaluation import calibrate, ranking_metrics, summarize

router = APIRouter(prefix="/admin/retrieval", dependencies=[Depends(administrator)])
POOL = 30
RRF_K = 60


class Search(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=10)
    document_id: str | None = None
    scope: Literal["admin", "usuario"] = "admin"


def corpus_signature(db):
    rows = db.execute(select(Document.id, Document.active_version_id, Chunk.revision_id, Chunk.model_signature,
                             DocumentVersion.metadata_json)
                      .select_from(Document)
                      .join(Chunk, Chunk.version_id == Document.active_version_id)
                      .join(DocumentVersion, DocumentVersion.id == Document.active_version_id)
                      .where(Document.deleted_at.is_(None), Document.deletion_requested.is_(False))
                      .order_by(Document.id, Chunk.revision_id)).all()
    unique = sorted({json.dumps(list(row), sort_keys=True) for row in rows})
    return hashlib.sha256(json.dumps(unique).encode()).hexdigest()


def fuse(vector, lexical):
    scores, details = {}, {}
    for name, rows in (("vector", vector), ("text", lexical)):
        for rank, row in enumerate(rows, 1):
            cid = row["id"]
            scores[cid] = scores.get(cid, 0) + 1 / (RRF_K + rank)
            details.setdefault(cid, {})[name] = {"rank": rank, "score": float(row["score"])}
    return [(cid, score, details[cid]) for cid, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))][:POOL]


def candidate_pools(db, vector, query, signature, document_id, admin):
    if db.bind.dialect.name != "postgresql":
        raise ProviderError("retrieval_requires_postgresql")
    # Both channels use the same MVCC statement snapshot and permission predicates.
    stmt = text("""WITH eligible AS MATERIALIZED (
        SELECT c.id, c.embedding, c.search_vector FROM chunks c
        JOIN document_versions v ON v.id=c.version_id
        JOIN documents d ON d.active_version_id=v.id
        WHERE d.deleted_at IS NULL AND NOT d.deletion_requested
          AND v.status IN ('publicado','indexando') AND c.model_signature=:signature
          AND (CAST(:document_id AS varchar) IS NULL OR d.id=CAST(:document_id AS varchar))
          AND (:admin OR v.metadata_json->>'visibility'='usuarios')
    ), vectors AS (
        SELECT id, 1-(embedding <=> CAST(:vector AS vector)) AS score,
               row_number() OVER (ORDER BY embedding <=> CAST(:vector AS vector), id) AS rank
        FROM eligible ORDER BY embedding <=> CAST(:vector AS vector), id LIMIT :pool
    ), lexical AS (
        SELECT id, ts_rank_cd(search_vector, websearch_to_tsquery('spanish', :query)) AS score,
               row_number() OVER (ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('spanish', :query)) DESC, id) AS rank
        FROM eligible WHERE search_vector @@ websearch_to_tsquery('spanish', :query)
        ORDER BY score DESC, id LIMIT :pool
    ) SELECT 'vector' AS channel, id, score, rank FROM vectors
      UNION ALL SELECT 'text' AS channel, id, score, rank FROM lexical""")
    rows = db.execute(stmt, {"signature": signature, "vector": json.dumps(vector), "query": query,
                            "pool": POOL, "document_id": document_id, "admin": admin}).mappings().all()
    return tuple([dict(row) for row in sorted(rows, key=lambda r: r["rank"]) if row["channel"] == name]
                 for name in ("vector", "text"))


def evidence_decision(db, settings, corpus, results, filtered=False, admin=True):
    if filtered:
        return {"action": "abstain", "reason": "filtered_scope_uncalibrated"}
    policy = db.scalar(select(EvidencePolicy).where(EvidencePolicy.scope == ("admin" if admin else "usuario"), EvidencePolicy.signature == model_signature(settings),
                      EvidencePolicy.corpus_signature == corpus).order_by(EvidencePolicy.created_at.desc()).limit(1))
    if not policy or not policy.report.get("approved"):
        return {"action": "abstain", "reason": "uncalibrated", "policy_id": policy.id if policy else None}
    threshold = policy.report.get("threshold")
    sufficient = bool(results) and threshold is not None and results[0]["rerank_score"] >= threshold
    return {"action": "answer" if sufficient else "abstain", "reason": "calibrated_score",
            "policy_id": policy.id, "threshold": threshold}


async def retrieve(db, settings, clients, query, limit=10, document_id=None, admin=False):
    query = query.strip()
    if not query:
        raise ValueError("empty_query")
    timing = {}
    started = perf_counter()
    if await clients.embedding_tokens("search_query: " + query) > 1000:
        raise ValueError("query_context_exceeded")
    vector = (await clients.embed([query], query=True))[0]
    timing["embedding_ms"] = (perf_counter() - started) * 1000
    started = perf_counter()
    # Do not retain the auth read's old transaction during external inference.
    db.rollback()
    db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    corpus = corpus_signature(db)
    vector_rows, text_rows = candidate_pools(db, vector, query, model_signature(settings), document_id, admin)
    timing["search_ms"] = (perf_counter() - started) * 1000
    started = perf_counter()
    fused = fuse(vector_rows, text_rows)
    candidates = []
    for cid, score, channels in fused:
        chunk = db.get(Chunk, cid)
        version = db.get(DocumentVersion, chunk.version_id)
        candidates.append({"chunk_id": cid, "document_id": version.document_id,
            "version_id": version.id, "version": version.number, "revision_id": chunk.revision_id,
            "title": version.metadata_json["title"], "content": chunk.content, "search_content": chunk.search_content,
            "provenance": chunk.provenance, "rrf_score": score, "channels": channels})
    db.rollback()  # Release snapshot before the slow reranker.
    timing["fusion_ms"] = (perf_counter() - started) * 1000
    started = perf_counter()
    if candidates:
        ranking = await clients.rerank(query, [c["search_content"] for c in candidates])
        candidates = [candidates[row["index"]] | {"rerank_score": row["relevance_score"]} for row in ranking]
    timing["reranking_ms"] = (perf_counter() - started) * 1000
    # A withdrawal/deletion during inference must invalidate the returned evidence.
    db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    ids = [c["chunk_id"] for c in candidates]
    visible = set(db.scalars(select(Chunk.id).join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
        .join(Document, Document.active_version_id == DocumentVersion.id)
        .where(Chunk.id.in_(ids), Document.deleted_at.is_(None), Document.deletion_requested.is_(False),
               DocumentVersion.status.in_(["publicado", "indexando"]))).all())
    candidates = [c for c in candidates if c["chunk_id"] in visible]
    changed = corpus_signature(db) != corpus
    decision = {"action": "abstain", "reason": "corpus_changed"} if changed else evidence_decision(
        db, settings, corpus, candidates, filtered=document_id is not None, admin=admin)
    return {"query": query, "candidates": candidates, "results": candidates[:limit],
            "pools": {"vector": vector_rows, "text": text_rows}, "decision": decision,
            "scope": {"admin": admin, "document_id": document_id},
            "latency": {key: round(value, 2) for key, value in timing.items()},
            "corpus_signature": corpus, "model_signature": model_signature(settings)}


@router.post("/search")
async def inspect(body: Search, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    try:
        result = await retrieve(db, request.app.state.settings, request.app.state.clients,
                                body.query, body.limit, body.document_id, admin=body.scope == "admin")
        run = RetrievalRun(actor_id=identity.user.id, query=body.query, status="completed", result=result, created_at=int(time.time()))
        db.add(run)
        db.commit()
        return result | {"run_id": run.id}
    except (httpx.HTTPError, ProviderError, ValueError, SQLAlchemyError) as exc:
        db.rollback()
        code = str(exc) if isinstance(exc, (ProviderError, ValueError)) else type(exc).__name__
        db.add(RetrievalRun(actor_id=identity.user.id, query=body.query, status="error", result={"error": code}, created_at=int(time.time())))
        db.commit()
        raise HTTPException(503 if not isinstance(exc, ValueError) else 422, code) from exc


@router.get("/runs")
def runs(db=Depends(database)):
    rows = db.scalars(select(RetrievalRun).order_by(RetrievalRun.created_at.desc()).limit(50)).all()
    return {"items": [{"id": r.id, "query": r.query, "status": r.status, "created_at": r.created_at,
                       "decision": r.result.get("decision"), "error": r.result.get("error")} for r in rows]}


@router.get("/runs/{run_id}")
def run_detail(run_id: str, db=Depends(database)):
    run = db.get(RetrievalRun, run_id)
    if not run:
        raise HTTPException(404, "Traza no encontrada")
    return {"id": run.id, "status": run.status, "result": run.result}


class LabeledRun(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    run_id: str = Field(min_length=36, max_length=36)
    kind: Literal["answerable", "unanswerable", "ambiguous", "conversation"]
    expected_documents: list[str] = Field(default_factory=list, max_length=30)
    expected_sections: list[str] = Field(default_factory=list, max_length=30)
    conversation_id: str | None = Field(default=None, max_length=100)
    language: str = Field(default="es", max_length=16)


class CalibrationBank(BaseModel):
    cases: list[LabeledRun] = Field(min_length=24, max_length=500)
    scope: Literal["admin", "usuario"] = "admin"


@router.get("/policy")
def current_policy(request: Request, scope: Literal["admin", "usuario"] = "admin", db=Depends(database)):
    signature = model_signature(request.app.state.settings)
    corpus = corpus_signature(db)
    policy = db.scalar(select(EvidencePolicy).where(EvidencePolicy.scope == scope, EvidencePolicy.signature == signature,
                      EvidencePolicy.corpus_signature == corpus).order_by(EvidencePolicy.created_at.desc()).limit(1))
    return {"id": policy.id if policy else None, "corpus_signature": corpus,
            "report": policy.report if policy else {"approved": False, "reason": "uncalibrated"}}


@router.post("/calibrate")
def calibrate_recorded_runs(body: CalibrationBank, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    if len({c.id for c in body.cases}) != len(body.cases) or len({c.run_id for c in body.cases}) != len(body.cases):
        raise HTTPException(422, "Casos y trazas deben ser unicos")
    minimums = {"answerable": 10, "unanswerable": 5, "ambiguous": 3, "conversation": 6}
    if any(sum(c.kind == kind for c in body.cases) < count for kind, count in minimums.items()):
        raise HTTPException(422, "El banco no cubre las cuatro clases de H0")
    corpus, signature = corpus_signature(db), model_signature(request.app.state.settings)
    rows = []
    for case in body.cases:
        run = db.get(RetrievalRun, case.run_id)
        if (not run or run.status != "completed" or run.result.get("corpus_signature") != corpus
                or run.result.get("model_signature") != signature
                or run.result.get("scope") != {"admin": body.scope == "admin", "document_id": None}):
            raise HTTPException(409, "Las trazas deben pertenecer al corpus y modelos vigentes, sin filtros")
        if case.kind in {"answerable", "conversation"} and not case.expected_documents:
            raise HTTPException(422, "Faltan fuentes esperadas")
        if case.kind == "conversation" and not case.conversation_id:
            raise HTTPException(422, "Falta grupo conversacional")
        expected = "answer" if case.kind in {"answerable", "conversation"} else "clarify" if case.kind == "ambiguous" else "abstain"
        row = case.model_dump() | {"expected_behavior": expected}
        results = run.result["candidates"]
        row.update(ranking_metrics(row, results, {c["document_id"]: c["document_id"] for c in results}))
        row["score"] = results[0]["rerank_score"] if results else None
        row["latency"] = run.result["latency"]
        rows.append(row)
    report = calibrate(rows) | {"metrics": summarize(rows), "cases": rows}
    policy = EvidencePolicy(scope=body.scope, signature=signature, corpus_signature=corpus, report=report, created_at=int(time.time()))
    db.add(policy)
    from .models import AuditEvent
    db.add(AuditEvent(actor_id=identity.user.id, action="retrieval_calibrated", correlation_id=request.state.correlation_id))
    db.commit()
    return {"id": policy.id, "report": report}
