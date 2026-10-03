import hashlib
import json
import time
import re
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
from .providers import LLM_TRACE, ProviderError, summarize_calls
from .sufficiency import assess, policy_signature, VERSION
from .evaluation import calibrate, ranking_metrics, summarize

router = APIRouter(prefix="/admin/retrieval", dependencies=[Depends(administrator)])
POOL = 30
RRF_K = 60
CONTEXT_POOL = 60
CONTEXT_BYTES = 36000


def lexical_query(query):
    # OR supplies lexical recall for natural-language questions; BGE judges relevance.
    # Quotes/operators from user input must not change the query's boolean semantics.
    words = re.findall(r"[^\W_]+", query.lower(), re.UNICODE)
    ignored = set("me puedes puede explicar explicas explica dime favor pasos paso como cómo que qué cuál cuáles para por los las el la un una del de al en se y o es son según sobre necesito quiero saber".split())
    return " OR ".join(dict.fromkeys(w for w in words if w not in ignored)) or query


class Search(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=10)
    document_id: str | None = None
    scope: Literal["admin", "usuario"] = "admin"
    previous_questions: list[str] = Field(default_factory=list, max_length=6)


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


def corpus_members(db):
    """Active version and visibility per document, used to decide policy inheritance."""
    rows = db.execute(select(Document.id, Document.active_version_id, DocumentVersion.metadata_json)
                      .join(DocumentVersion, DocumentVersion.id == Document.active_version_id)
                      .where(Document.deleted_at.is_(None), Document.deletion_requested.is_(False))).all()
    return {doc: [version, (metadata or {}).get("visibility")] for doc, version, metadata in rows}


def find_policy(db, settings, scope, corpus):
    """Exact-corpus policy, else the latest approved one whose calibrated documents are unchanged.

    Publishing or withdrawing other documents keeps the calibrated threshold (the
    per-question coverage assessment still gates every answer), so the chat does not
    stop answering until a slow recalibration finishes. Replacing a calibrated
    document's version or visibility still requires recalibration.
    """
    signature = policy_signature(settings)
    base = select(EvidencePolicy).where(EvidencePolicy.scope == scope, EvidencePolicy.signature == signature)
    exact = db.scalar(base.where(EvidencePolicy.corpus_signature == corpus)
                      .order_by(EvidencePolicy.created_at.desc()).limit(1))
    if exact:
        return exact, False
    members = corpus_members(db)
    for policy in db.scalars(base.order_by(EvidencePolicy.created_at.desc()).limit(20)):
        calibrated = policy.report.get("corpus_members")
        if not policy.report.get("approved") or not isinstance(calibrated, dict):
            continue
        if all(members[doc] == value for doc, value in calibrated.items() if doc in members):
            return policy, True
        return None, False  # Newer calibrated content changed; older policies are staler still.
    return None, False


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
    rows = db.execute(stmt, {"signature": signature, "vector": json.dumps(vector), "query": lexical_query(query),
                            "pool": POOL, "document_id": document_id, "admin": admin}).mappings().all()
    return tuple([dict(row) for row in sorted(rows, key=lambda r: r["rank"]) if row["channel"] == name]
                 for name in ("vector", "text"))


def expand_context(db, candidates):
    """Read exact sibling chunks of retrieved, eligible revisions; never invent passages.

    Small guides can be read as a whole. Large guides use nearby chunks so a heading
    does not lose the instructions immediately following it. The budget is global.
    """
    result = list(candidates)
    seen = {c["chunk_id"] for c in result}
    size = sum(len(c["search_content"].encode()) for c in result)
    versions = set()
    for seed in candidates[:10]:
        if seed["version_id"] in versions:
            continue
        versions.add(seed["version_id"])
        siblings = db.scalars(select(Chunk).where(Chunk.version_id == seed["version_id"],
            Chunk.revision_id == seed["revision_id"]).order_by(Chunk.number)).all()
        if len(siblings) > CONTEXT_POOL:
            seed_ids = {c["chunk_id"] for c in candidates if c["version_id"] == seed["version_id"]}
            numbers = [c.number for c in siblings if c.id in seed_ids]
            siblings = sorted(siblings, key=lambda c: (min(abs(c.number - n) for n in numbers), c.number))
        for chunk in siblings:
            if chunk.id in seen:
                continue
            cost = len(chunk.search_content.encode())
            if len(result) >= CONTEXT_POOL or size + cost > CONTEXT_BYTES:
                continue
            result.append(seed | {"chunk_id": chunk.id, "content": chunk.content,
                "search_content": chunk.search_content, "provenance": chunk.provenance,
                "rrf_score": 0, "channels": {"context": {"seed_chunk_id": seed["chunk_id"]}}})
            seen.add(chunk.id)
            size += cost
    return result


def evidence_decision(db, settings, corpus, results, filtered=False, admin=True, assessment=None):
    if filtered:
        return {"action": "abstain", "reason": "filtered_scope_uncalibrated"}
    if not assessment or assessment.get("version") != VERSION:
        return {"action": "abstain", "reason": "assessment_missing"}
    if assessment["action"] != "answer":
        return {"action": assessment["action"], "reason": assessment["reason"]}
    policy, inherited = find_policy(db, settings, "admin" if admin else "usuario", corpus)
    if not policy or not policy.report.get("approved"):
        return {"action": "abstain", "reason": "uncalibrated", "policy_id": policy.id if policy else None}
    threshold = policy.report.get("threshold")
    sufficient = bool(results) and threshold is not None and results[0]["rerank_score"] >= threshold
    return {"action": "answer" if sufficient else "abstain", "reason": "calibrated_score",
            "policy_id": policy.id, "threshold": threshold, "policy_inherited": inherited}


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
    candidates = expand_context(db, candidates)
    db.rollback()  # Release snapshot before the slow reranker.
    timing["fusion_ms"] = (perf_counter() - started) * 1000
    started = perf_counter()
    if candidates:
        ranking = await clients.rerank(query, [c["search_content"] for c in candidates])
        candidates = [candidates[row["index"]] | {"rerank_score": row["relevance_score"]} for row in ranking]
    timing["reranking_ms"] = (perf_counter() - started) * 1000
    started = perf_counter()
    assessment = await assess(clients, query, candidates)
    timing["sufficiency_ms"] = (perf_counter() - started) * 1000
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
        db, settings, corpus, candidates, filtered=document_id is not None, admin=admin, assessment=assessment)
    supporting = {s["chunk_id"] for s in assessment.get("support", [])}
    # Generation receives only the exact passages whose coverage was assessed.
    results = ([c for c in candidates if c["chunk_id"] in supporting]
               if assessment["action"] == "answer" else candidates)[:limit]
    return {"query": query, "candidates": candidates, "results": results,
            "pools": {"vector": vector_rows, "text": text_rows}, "decision": decision,
            "scope": {"admin": admin, "document_id": document_id},
            "latency": {key: round(value, 2) for key, value in timing.items()},
            "corpus_signature": corpus, "model_signature": policy_signature(settings), "assessment": assessment}


@router.post("/search")
async def inspect(body: Search, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    calls = []
    LLM_TRACE.set(calls)
    try:
        query = body.query
        if body.previous_questions:
            if any(not q.strip() or len(q) > 1000 for q in body.previous_questions):
                raise ValueError("invalid_history")
        # Same query normalization and contextual reformulation as chat.
        from .chat import contextual_query
        query = await contextual_query(request.app.state.clients, query, "",
                                       [{"role": "user", "content": q, "references": []}
                                        for q in body.previous_questions])
        result = await retrieve(db, request.app.state.settings, request.app.state.clients,
                                query, body.limit, body.document_id, admin=body.scope == "admin")
        result["question"] = body.query
        result["previous_questions"] = body.previous_questions
        result["llm"] = summarize_calls(calls) | {"trace": calls}
        run = RetrievalRun(actor_id=identity.user.id, query=query, status="completed", result=result, created_at=int(time.time()))
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
    split: Literal["calibration", "validation"] | None = None
    language: str = Field(default="es", max_length=16)


class CalibrationBank(BaseModel):
    cases: list[LabeledRun] = Field(min_length=24, max_length=500)
    scope: Literal["admin", "usuario"] = "admin"


@router.get("/policy")
def current_policy(request: Request, scope: Literal["admin", "usuario"] = "admin", db=Depends(database)):
    corpus = corpus_signature(db)
    policy, inherited = find_policy(db, request.app.state.settings, scope, corpus)
    return {"id": policy.id if policy else None, "corpus_signature": corpus, "inherited": inherited,
            "report": policy.report if policy else {"approved": False, "reason": "uncalibrated"}}


@router.post("/calibrate")
def calibrate_recorded_runs(body: CalibrationBank, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    if len({c.id for c in body.cases}) != len(body.cases) or len({c.run_id for c in body.cases}) != len(body.cases):
        raise HTTPException(422, "Casos y trazas deben ser unicos")
    minimums = {"answerable": 10, "unanswerable": 5, "ambiguous": 3, "conversation": 6}
    if any(sum(c.kind == kind for c in body.cases) < count for kind, count in minimums.items()):
        raise HTTPException(422, "El banco no cubre las cuatro clases de H0")
    if any(c.split for c in body.cases) and any(
            sum(c.kind == kind and c.split == split for c in body.cases) < count
            for split in ("calibration", "validation") for kind, count in minimums.items()):
        raise HTTPException(422, "Cada banco independiente debe cubrir las cuatro clases de H0")
    corpus, signature = corpus_signature(db), policy_signature(request.app.state.settings)
    rows = []
    for case in body.cases:
        run = db.get(RetrievalRun, case.run_id)
        if (not run or run.status != "completed" or run.result.get("corpus_signature") != corpus
                or run.result.get("model_signature") != signature
                or run.result.get("assessment", {}).get("version") != VERSION
                or run.result.get("scope") != {"admin": body.scope == "admin", "document_id": None}):
            raise HTTPException(409, "Las trazas deben pertenecer al corpus y modelos vigentes, sin filtros")
        if case.kind in {"answerable", "conversation"} and not case.expected_documents:
            raise HTTPException(422, "Faltan fuentes esperadas")
        if case.kind == "conversation" and not case.conversation_id:
            raise HTTPException(422, "Falta grupo conversacional")
        expected = "answer" if case.kind in {"answerable", "conversation"} else "clarify" if case.kind == "ambiguous" else "abstain"
        row = case.model_dump() | {"expected_behavior": expected}
        results = run.result["candidates"]
        evidence = run.result.get("results", results)
        row.update(ranking_metrics(row, evidence, {c["document_id"]: c["document_id"] for c in results}))
        row["score"] = results[0]["rerank_score"] if results else None
        row["answer_eligible"] = run.result["assessment"]["action"] == "answer"
        row["assessment_action"] = run.result["assessment"]["action"]
        row["error"] = run.result["assessment"].get("error", "assessment_failed") if run.result["assessment"]["reason"] == "assessment_failed" else None
        row["latency"] = run.result["latency"]
        rows.append(row)
    try:
        report = calibrate(rows) | {"metrics": summarize(rows), "cases": rows}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report["corpus_members"] = corpus_members(db)
    policy = EvidencePolicy(scope=body.scope, signature=signature, corpus_signature=corpus, report=report, created_at=int(time.time()))
    db.add(policy)
    from .models import AuditEvent
    db.add(AuditEvent(actor_id=identity.user.id, action="retrieval_calibrated", correlation_id=request.state.correlation_id))
    db.commit()
    return {"id": policy.id, "report": report}
