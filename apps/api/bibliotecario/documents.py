import hashlib
import re
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .auth import administrator, database, require_csrf
from .converters import edited_provenance
from .jobs import ACTIVE, enqueue, event, restore_version
from .models import (AuditEvent, Document, DocumentFile, DocumentVersion, IngestionJob,
                     JobEvent, NormalizedRevision)
from .storage import InvalidFile, save_upload, storage_path

router = APIRouter(prefix="/admin", dependencies=[Depends(administrator)])


class Metadata(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(default="", max_length=200)
    date: str = Field(default="", max_length=32)
    category: str = Field(default="", max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=30)
    language: str = Field(default="es", min_length=2, max_length=16)
    version: str = Field(default="1", min_length=1, max_length=64)
    visibility: str = Field(default="usuarios", pattern="^(usuarios|admin)$")

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value):
        if not value.strip():
            raise ValueError("Titulo vacio")
        return value.strip()


class ReviewEdit(BaseModel):
    expected_revision_id: str
    markdown: str
    metadata: Metadata


class Confirmation(BaseModel):
    confirmation: str


class RevisionConfirmation(BaseModel):
    expected_revision_id: str


def audit(db, request, actor, action, object_id):
    db.add(AuditEvent(actor_id=actor.user.id, action=action, object_id=object_id,
                      correlation_id=request.state.correlation_id))


def get_document(db, id, lock=False):
    query = select(Document).where(Document.id == id, Document.deleted_at.is_(None))
    document = db.scalar(query.with_for_update() if lock else query)
    if not document:
        raise HTTPException(404, "Documento no encontrado")
    return document


def get_version(db, id, lock=False):
    query = select(DocumentVersion).where(DocumentVersion.id == id)
    version = db.scalar(query)
    if not version or version.status == "eliminado":
        raise HTTPException(404, "Version no encontrada")
    # Serialize draft mutations with replacement/deletion at the document boundary.
    document = get_document(db, version.document_id, lock=lock)
    if lock:
        version = db.scalar(query.with_for_update().execution_options(populate_existing=True))
    if document.deletion_requested:
        raise HTTPException(409, "Eliminacion en curso")
    return version


def no_active_job(db, version_id=None, document_id=None):
    query = select(IngestionJob.id).where(IngestionJob.status.in_(ACTIVE))
    if version_id:
        query = query.where(IngestionJob.version_id == version_id)
    if document_id:
        query = query.where(IngestionJob.document_id == document_id)
    if db.scalar(query.limit(1)):
        raise HTTPException(409, "Hay un trabajo activo")


def version_json(db, version):
    revision = db.get(NormalizedRevision, version.current_revision_id) if version.current_revision_id else None
    file = db.scalar(select(DocumentFile).where(DocumentFile.version_id == version.id))
    return {"id": version.id, "document_id": version.document_id, "number": version.number,
            "status": version.status, "metadata": version.metadata_json, "original_sha256": version.original_sha256,
            "original_name": file.original_name if file else None, "format": file.format if file else None,
            "revision_id": version.current_revision_id, "reviewed_at": version.reviewed_at,
            "diagnostics": revision.diagnostics if revision else [], "created_at": version.created_at}


def document_json(db, document):
    versions = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id)
                           .order_by(DocumentVersion.number.desc())).all()
    return {"id": document.id, "title": document.title, "active_version_id": document.active_version_id,
            "deletion_requested": document.deletion_requested,
            "versions": [version_json(db, version) for version in versions]}


def job_json(job):
    return {"id": job.id, "document_id": job.document_id, "version_id": job.version_id,
            "kind": job.kind, "status": job.status, "progress": job.progress,
            "attempts": job.attempts, "generation": job.generation, "error_code": job.error_code,
            "created_at": job.created_at, "updated_at": job.updated_at}


@router.get("/documents")
def list_documents(q: str = "", offset: int = 0, db=Depends(database)):
    if len(q) > 300 or offset < 0:
        raise HTTPException(422, "Filtro no valido")
    query = select(Document).where(Document.deleted_at.is_(None))
    if q:
        query = query.where(Document.title.icontains(q, autoescape=True))
    documents = db.scalars(query.order_by(Document.created_at.desc(), Document.id).offset(offset).limit(50)).all()
    return {"items": [document_json(db, document) for document in documents], "offset": offset, "has_more": len(documents) == 50}


@router.get("/documents/{document_id}")
def detail(document_id: str, db=Depends(database)):
    return document_json(db, get_document(db, document_id))


@router.post("/documents", status_code=201)
@router.post("/documents/{document_id}/versions", status_code=201)
def upload(request: Request, file: UploadFile = File(...), title: str = Form("", max_length=300), document_id: str | None = None,
           idempotency_key: str = Header(..., alias="Idempotency-Key"), identity=Depends(require_csrf), db=Depends(database)):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", idempotency_key):
        raise HTTPException(422, "Clave de idempotencia no valida")
    settings = request.app.state.settings
    key = None
    try:
        key, digest, size, fmt = save_upload(file.file, file.filename, file.content_type, settings)
        previous = db.scalar(select(IngestionJob).where(IngestionJob.actor_id == identity.user.id,
                                                         IngestionJob.idempotency_key == idempotency_key))
        if previous:
            if previous.kind != "convert" or previous.payload.get("upload_sha256") != digest or previous.payload.get("replacement_id") != document_id:
                raise HTTPException(409, "La clave ya identifica otra operacion")
            storage_path(settings, key).unlink(missing_ok=True)
            key = None
            return {"document": document_json(db, get_document(db, previous.document_id)), "job": job_json(previous)}
        now = int(time.time())
        if document_id:
            document = get_document(db, document_id, lock=True)
            if document.deletion_requested:
                raise HTTPException(409, "Eliminacion en curso")
            no_active_job(db, document_id=document_id)
            latest = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(DocumentVersion.number.desc()).limit(1))
            number = latest.number + 1
            metadata = Metadata.model_validate(latest.metadata_json).model_copy(update={"version": str(number)})
        else:
            metadata = Metadata(title=title.strip() or file.filename)
            number = 1
            document = Document(id=str(uuid.uuid4()), title=metadata.title, created_at=now)
            db.add(document)
            db.flush()
        version = DocumentVersion(id=str(uuid.uuid4()), document_id=document.id, number=number, status="subido",
                                  original_sha256=digest, metadata_json=metadata.model_dump(), created_at=now)
        db.add(version)
        db.flush()
        db.add(DocumentFile(version_id=version.id, storage_key=key, original_name=file.filename, format=fmt, size_bytes=size, sha256=digest))
        db.flush()
        job = enqueue(db, document.id, version.id, identity.user.id, request.state.correlation_id, idempotency_key,
                      payload={"upload_sha256": digest, "replacement_id": document_id})
        audit(db, request, identity, "document_uploaded" if number == 1 else "document_replaced", version.id)
        db.commit()
        key = None
        return {"document": document_json(db, document), "job": job_json(job)}
    except InvalidFile as exc:
        db.rollback()
        raise HTTPException(413 if str(exc) == "upload_too_large" else 422, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Operacion concurrente; reintente con la misma clave") from exc
    finally:
        if key:
            storage_path(settings, key).unlink(missing_ok=True)
        file.file.close()


@router.get("/versions/{version_id}/original")
def original(version_id: str, request: Request, db=Depends(database)):
    get_version(db, version_id)
    file = db.scalar(select(DocumentFile).where(DocumentFile.version_id == version_id))
    target = storage_path(request.app.state.settings, file.storage_key)
    if not target.is_file():
        raise HTTPException(404, "Original no disponible")
    return FileResponse(target, media_type="application/octet-stream", filename=file.original_name)


@router.get("/versions/{version_id}/normalized")
def normalized(version_id: str, request: Request, revision_id: str | None = None, db=Depends(database)):
    version = get_version(db, version_id)
    revision = db.get(NormalizedRevision, revision_id or version.current_revision_id) if (revision_id or version.current_revision_id) else None
    if not revision or revision.version_id != version.id:
        raise HTTPException(404, "Revision no disponible")
    target = storage_path(request.app.state.settings, revision.storage_key)
    if not target.is_file():
        raise HTTPException(404, "Markdown no disponible")
    return {"revision_id": revision.id, "markdown": target.read_text(encoding="utf-8"),
            "number": revision.number, "metadata": revision.metadata_json,
            "sha256": revision.sha256, "provenance": revision.provenance, "diagnostics": revision.diagnostics}


@router.get("/versions/{version_id}/revisions")
def revisions(version_id: str, db=Depends(database)):
    get_version(db, version_id)
    rows = db.scalars(select(NormalizedRevision).where(NormalizedRevision.version_id == version_id).order_by(NormalizedRevision.number.desc())).all()
    return {"items": [{"id": row.id, "number": row.number, "sha256": row.sha256, "created_at": row.created_at, "edited": row.actor_id is not None} for row in rows]}


@router.patch("/versions/{version_id}")
def edit(version_id: str, body: ReviewEdit, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    version = get_version(db, version_id, lock=True)
    no_active_job(db, version_id=version_id)
    if version.status != "requiere_revision" or body.expected_revision_id != version.current_revision_id:
        raise HTTPException(409, "La version ha cambiado o no esta en revision")
    settings = request.app.state.settings
    content = body.markdown.encode("utf-8")
    if len(content) > settings.normalized_max_bytes or any(len(tag) > 100 for tag in body.metadata.tags):
        raise HTTPException(413, "Limite de contenido excedido")
    previous = db.get(NormalizedRevision, version.current_revision_id)
    old_content = storage_path(settings, previous.storage_key).read_text(encoding="utf-8")
    revision_id = str(uuid.uuid4())
    key = f"normalized/{version.id}/{revision_id}.md"
    target = storage_path(settings, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    locators = edited_provenance(old_content, previous.provenance, body.markdown)
    diagnostics = [code for code in previous.diagnostics if code not in {"empty_document", "edited_provenance"}]
    if any(locator["origin"] == "manual" for locator in locators):
        diagnostics.append("edited_provenance")
    if not body.markdown.strip():
        diagnostics.append("empty_document")
    try:
        with target.open("xb") as handle:
            handle.write(content)
        revision = NormalizedRevision(id=revision_id, version_id=version.id, storage_key=key,
            number=previous.number + 1, metadata_json=body.metadata.model_dump(),
            sha256=hashlib.sha256(content).hexdigest(), provenance=locators, diagnostics=diagnostics,
            created_at=int(time.time()), actor_id=identity.user.id)
        db.add(revision)
        db.flush()
        version.current_revision_id, version.metadata_json, version.reviewed_at = revision_id, body.metadata.model_dump(), None
        document = get_document(db, version.document_id)
        document.title = body.metadata.title
        audit(db, request, identity, "document_edited", version.id)
        db.commit()
        return version_json(db, version)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


@router.post("/versions/{version_id}/review")
def approve(version_id: str, body: RevisionConfirmation, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    version = get_version(db, version_id, lock=True)
    no_active_job(db, version_id=version_id)
    if version.status != "requiere_revision" or version.current_revision_id != body.expected_revision_id:
        raise HTTPException(409, "Revision no vigente")
    revision = db.get(NormalizedRevision, version.current_revision_id)
    if not storage_path(request.app.state.settings, revision.storage_key).read_text(encoding="utf-8").strip():
        raise HTTPException(422, "No se puede aprobar un documento vacio")
    version.reviewed_at = int(time.time())
    audit(db, request, identity, "document_reviewed", version.id)
    db.commit()
    return version_json(db, version)


@router.post("/versions/{version_id}/convert", status_code=202)
def reprocess(version_id: str, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    version = get_version(db, version_id, lock=True)
    no_active_job(db, version_id=version_id)
    if version.status not in {"subido", "requiere_revision", "error"}:
        raise HTTPException(409, "Estado no convertible")
    job = enqueue(db, version.document_id, version.id, identity.user.id, request.state.correlation_id, str(uuid.uuid4()))
    version.reviewed_at = None
    audit(db, request, identity, "conversion_requested", version.id)
    db.commit()
    return job_json(job)


@router.post("/documents/{document_id}/withdraw")
def withdraw(document_id: str, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    document = get_document(db, document_id, lock=True)
    if not document.active_version_id:
        raise HTTPException(409, "No hay una version publicada")
    version = db.get(DocumentVersion, document.active_version_id)
    version.status, version.retired_at = "retirado", int(time.time())
    document.active_version_id = None
    audit(db, request, identity, "document_withdrawn", version.id)
    db.commit()
    return document_json(db, document)


@router.post("/versions/{version_id}/publish", status_code=202)
def publish(version_id: str, body: RevisionConfirmation, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    version = get_version(db, version_id, lock=True)
    no_active_job(db, document_id=version.document_id)
    if (version.status not in {"requiere_revision", "publicado", "error"} or not version.reviewed_at
            or body.expected_revision_id != version.current_revision_id):
        raise HTTPException(409, "Se requiere una revision vigente aprobada")
    document = get_document(db, version.document_id)
    job = enqueue(db, document.id, version.id, identity.user.id, request.state.correlation_id,
                  str(uuid.uuid4()), kind="index", payload={"revision_id": version.current_revision_id,
                  "active_version_id": document.active_version_id})
    # Keep an existing published version searchable while its replacement index is built.
    if document.active_version_id != version.id:
        version.status = "indexando"
    audit(db, request, identity, "index_requested", version.id)
    db.commit()
    return job_json(job)


@router.delete("/documents/{document_id}", status_code=202)
def remove(document_id: str, body: Confirmation, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    document = get_document(db, document_id, lock=True)
    if body.confirmation != document.title or document.active_version_id or document.deletion_requested:
        raise HTTPException(409, "Confirmacion incorrecta o documento no eliminable")
    no_active_job(db, document_id=document_id)
    versions = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document_id)).all()
    cutoff = int(time.time()) - request.app.state.settings.retired_retention_days * 86400
    if any(version.published_at is not None and (version.retired_at is None or version.retired_at > cutoff) for version in versions):
        raise HTTPException(409, "No se cumple el plazo de retencion")
    document.deletion_requested = True
    for version in versions:
        version.status = "eliminando"
    job = enqueue(db, document_id, None, identity.user.id, request.state.correlation_id, str(uuid.uuid4()), kind="delete")
    audit(db, request, identity, "deletion_requested", document_id)
    db.commit()
    return job_json(job)


@router.get("/jobs")
def jobs(document_id: str | None = None, offset: int = 0, db=Depends(database)):
    if offset < 0:
        raise HTTPException(422, "Offset no valido")
    query = select(IngestionJob, Document.title).join(Document, Document.id == IngestionJob.document_id)
    if document_id:
        query = query.where(IngestionJob.document_id == document_id)
    rows = db.execute(query.order_by(IngestionJob.created_at.desc(), IngestionJob.id).offset(offset).limit(50)).all()
    return {"items": [job_json(row) | {"document_title": title} for row, title in rows], "has_more": len(rows) == 50}


@router.get("/jobs/{job_id}/events")
def job_events(job_id: str, db=Depends(database)):
    if not db.get(IngestionJob, job_id):
        raise HTTPException(404, "Trabajo no encontrado")
    rows = db.scalars(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.number).limit(1000)).all()
    return {"items": [{"event": row.event, "attempt": row.attempt, "generation": row.generation, "created_at": row.created_at} for row in rows]}


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update())
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    if job.kind not in {"convert", "index"} or job.status not in ACTIVE - {"cancelando"}:
        raise HTTPException(409, "Trabajo no cancelable")
    if job.status == "en_ejecucion":
        job.status = "cancelando"
    else:
        job.status = "cancelado"
        restore_version(db, job)
    job.updated_at = int(time.time())
    event(db, job, "cancellation_requested")
    audit(db, request, identity, "job_cancelled", job.id)
    db.commit()
    return job_json(job)


@router.post("/jobs/{job_id}/retry")
def retry(job_id: str, request: Request, identity=Depends(require_csrf), db=Depends(database)):
    job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update())
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    if job.status not in {"fallido", "cancelado"}:
        raise HTTPException(409, "Trabajo no reintentable")
    document = get_document(db, job.document_id, lock=True)
    if document.deletion_requested and job.kind != "delete":
        raise HTTPException(409, "Eliminacion en curso")
    if job.kind == "convert":
        version = get_version(db, job.version_id, lock=True)
        if version.status not in {"subido", "requiere_revision", "error"}:
            raise HTTPException(409, "Estado no convertible")
        version.reviewed_at = None
    if job.kind == "index":
        version = get_version(db, job.version_id, lock=True)
        if not version.reviewed_at or version.current_revision_id != job.payload.get("revision_id") or version.status == "retirado":
            raise HTTPException(409, "Revision no indexable")
        job.payload = job.payload | {"active_version_id": document.active_version_id}
    no_active_job(db, document_id=job.document_id)
    new_job = enqueue(db, job.document_id, job.version_id, identity.user.id, request.state.correlation_id,
                      str(uuid.uuid4()), kind=job.kind, payload=job.payload | {"retry_of": job.id})
    restore_version(db, new_job)
    event(db, new_job, "manual_retry")
    audit(db, request, identity, "job_retried", new_job.id)
    db.commit()
    return job_json(new_job)
