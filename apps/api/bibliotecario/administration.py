"""Administrative operations; exports contain explicit projections, never env or credentials."""
import hashlib
import json
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from .admin_settings import PublicSettings, public_settings, settings_signature
from .auth import administrator, database, require_csrf
from .documents import audit, job_json, no_active_job
from .jobs import ACTIVE, enqueue
from .models import (AppSetting, AuditEvent, Document, DocumentVersion, EvidencePolicy,
                     IngestionJob, Message, ReindexBatch, WorkerStatus)

router = APIRouter(prefix="/admin/operations", dependencies=[Depends(administrator)])


class SettingsEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    values: PublicSettings


@router.get("/settings")
def settings_view(request: Request, db=Depends(database)):
    row = db.get(AppSetting, "providers")
    active = public_settings(request.app.state.settings)
    workers = db.scalars(select(WorkerStatus)).all()
    expected = settings_signature(row.value if row else active)
    worker_pending = any(w.settings_signature != expected for w in workers)
    return {"revision": row.revision if row else 0, "active": active,
            "saved": row.value if row else active, "restart_required": bool((row and row.value != active) or worker_pending),
            "embedding_dimensions": 768}


@router.put("/settings")
def settings_edit(body: SettingsEdit, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    # Lock a stable row even on the first edit, when app_settings has no row yet.
    from .models import Role
    db.scalar(select(Role).where(Role.name == "admin").with_for_update())
    row = db.get(AppSetting, "providers")
    if body.expected_revision != (row.revision if row else 0):
        raise HTTPException(409, "Configuracion modificada; recargue antes de guardar")
    values = body.values.model_dump()
    if row:
        row.value, row.revision = values, row.revision + 1
    else:
        db.add(AppSetting(name="providers", value=values, revision=1))
    audit(db, request, identity, "settings_updated", None)
    db.commit()
    return settings_view(request, db)


@router.get("/status")
def operation_status(request: Request, db=Depends(database)):
    counts = dict(db.execute(select(IngestionJob.status, func.count()).group_by(IngestionJob.status)).all())
    workers = db.scalars(select(WorkerStatus)).all()
    now = int(time.time())
    row = db.get(AppSetting, "providers")
    expected = settings_signature(row.value if row else public_settings(request.app.state.settings))
    return {"jobs": counts, "workers": [{"name": w.name, "heartbeat_at": w.heartbeat_at,
        "settings_current": w.settings_signature == expected,
        "state": w.state, "available": w.state != "stopped" and now - w.heartbeat_at <
        request.app.state.settings.worker_interval_seconds * 3} for w in workers]}


class ReindexSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[str] | None = Field(default=None, min_length=1, max_length=1000)


class ReindexConfirmation(ReindexSelection):
    snapshot: str = Field(min_length=64, max_length=64)
    confirmation: Literal["REINDEXAR"]


def reindex_plan(db, ids, lock=False):
    if ids and len(ids) != len(set(ids)):
        raise HTTPException(422, "Documentos duplicados")
    query = select(Document).where(Document.deleted_at.is_(None), Document.deletion_requested.is_(False))
    if ids:
        query = query.where(Document.id.in_(ids))
    else:
        query = query.where(Document.active_version_id.is_not(None))
    query = query.order_by(Document.id).limit(1001)
    documents = db.scalars(query.with_for_update() if lock else query).all()
    if len(documents) > 1000:
        raise HTTPException(422, "Seleccione lotes de hasta 1000 documentos")
    if ids and {d.id for d in documents} != set(ids):
        raise HTTPException(409, "Documento inexistente o eliminacion en curso")
    items = []
    for document in documents:
        version = db.get(DocumentVersion, document.active_version_id) if document.active_version_id else None
        if not version or version.status != "publicado" or not version.reviewed_at or not version.current_revision_id:
            raise HTTPException(409, "Solo se reindexan versiones publicadas y revisadas")
        no_active_job(db, document_id=document.id)
        items.append({"document_id": document.id, "title": document.title, "version_id": version.id,
                      "version": version.number, "revision_id": version.current_revision_id})
    snapshot = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    return {"items": items, "snapshot": snapshot, "count": len(items)}


@router.post("/reindex/preview")
def reindex_preview(body: ReindexSelection, db=Depends(database)):
    return reindex_plan(db, body.document_ids)


@router.post("/reindex", status_code=202)
def reindex(body: ReindexConfirmation, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    plan = reindex_plan(db, body.document_ids, lock=True)
    if plan["snapshot"] != body.snapshot or not plan["items"]:
        raise HTTPException(409, "La seleccion cambio o esta vacia; vuelva a previsualizar")
    batch_id = str(uuid.uuid4())
    jobs = [enqueue(db, item["document_id"], item["version_id"], identity.user.id,
        request.state.correlation_id, str(uuid.uuid4()), kind="index",
        payload={"revision_id": item["revision_id"], "active_version_id": item["version_id"], "batch_id": batch_id})
        for item in plan["items"]]
    batch = ReindexBatch(id=batch_id, actor_id=identity.user.id, job_ids=[j.id for j in jobs], created_at=int(time.time()))
    db.add(batch)
    audit(db, request, identity, "reindex_requested", batch_id)
    db.commit()
    return batch_view(batch.id, db)


@router.get("/batches")
def batches(db=Depends(database)):
    rows = db.scalars(select(ReindexBatch).order_by(ReindexBatch.created_at.desc(), ReindexBatch.id).limit(50)).all()
    return {"items": [batch_view(row.id, db) for row in rows]}


@router.get("/batches/{batch_id}")
def batch_view(batch_id: str, db=Depends(database)):
    batch = db.get(ReindexBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Lote no encontrado")
    jobs = db.scalars(select(IngestionJob).where(IngestionJob.id.in_(batch.job_ids)).order_by(IngestionJob.id)).all()
    return {"id": batch.id, "created_at": batch.created_at, "total": len(jobs),
            "finished": sum(j.status not in ACTIVE for j in jobs),
            "failed": sum(j.status == "fallido" for j in jobs),
            "progress": round(sum(j.progress for j in jobs) / len(jobs)) if jobs else 0,
            "items": [job_json(j) for j in jobs]}


@router.get("/audit")
def audit_view(action: str = Query(default="", max_length=64), object_id: str = Query(default="", max_length=36),
               actor_id: str = Query(default="", max_length=36), result: str = Query(default="", max_length=16),
               offset: int = Query(default=0, ge=0), db=Depends(database)):
    query = select(AuditEvent)
    for name, value in [("action", action), ("object_id", object_id), ("actor_id", actor_id), ("result", result)]:
        if value:
            query = query.where(getattr(AuditEvent, name) == value)
    rows = db.scalars(query.order_by(AuditEvent.created_at.desc(), AuditEvent.id).offset(offset).limit(51)).all()
    return {"items": [{"id": r.id, "actor_id": r.actor_id, "action": r.action, "object_id": r.object_id,
            "result": r.result, "correlation_id": r.correlation_id, "created_at": r.created_at.isoformat()} for r in rows[:50]],
            "has_more": len(rows) > 50}


@router.get("/evaluations")
def evaluations(offset: int = Query(default=0, ge=0), db=Depends(database)):
    rows = db.scalars(select(EvidencePolicy).order_by(EvidencePolicy.created_at.desc(), EvidencePolicy.id)
                      .offset(offset).limit(51)).all()
    return {"items": [{"id": p.id, "scope": p.scope, "created_at": p.created_at,
        "approved": p.report.get("approved", False), "metrics": p.report.get("metrics", {})} for p in rows[:50]],
        "has_more": len(rows) > 50}


def download(payload, name):
    return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{name}.json"'})


@router.get("/export/diagnostics")
def diagnostics(request: Request, identity=Depends(administrator), db=Depends(database)):
    jobs = db.scalars(select(IngestionJob).order_by(IngestionJob.created_at.desc(), IngestionJob.id).limit(1000)).all()
    payload = {"schema": "bibliotecario-diagnostics-v1", "created_at": int(time.time()),
               "settings": settings_view(request, db), "status": operation_status(request, db),
               "jobs": [job_json(j) for j in jobs], "job_limit": 1000}
    audit(db, request, identity, "diagnostics_exported", None)
    db.commit()
    return download(payload, "bibliotecario-diagnosticos")


@router.get("/export/evaluations/{policy_id}")
def evaluation_export(policy_id: str, request: Request, identity=Depends(administrator), db=Depends(database)):
    policy = db.get(EvidencePolicy, policy_id)
    if not policy:
        raise HTTPException(404, "Evaluacion no encontrada")
    payload = {"schema": "bibliotecario-evaluation-v1", "id": policy.id, "scope": policy.scope,
               "signature": policy.signature, "corpus_signature": policy.corpus_signature, "report": policy.report}
    audit(db, request, identity, "evaluation_exported", policy.id)
    db.commit()
    return download(payload, "bibliotecario-evaluacion")


@router.get("/responses")
def responses(offset: int = Query(default=0, ge=0), db=Depends(database)):
    rows = db.scalars(select(Message).where(Message.role == "assistant").order_by(Message.created_at.desc(), Message.id)
                      .offset(offset).limit(51)).all()
    return {"items": [{"id": m.id, "conversation_id": m.conversation_id, "status": m.status,
        "created_at": m.created_at, "retrieval_run_id": m.retrieval_run_id, "sources": m.sources} for m in rows[:50]],
        "has_more": len(rows) > 50}
