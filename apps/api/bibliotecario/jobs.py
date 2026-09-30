import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select

from .models import (AuditEvent, Document, DocumentFile, DocumentVersion, IngestionJob, JobEvent,
                     NormalizedRevision, Chunk)
from .storage import storage_path

ACTIVE = {"pendiente", "en_ejecucion", "reintentable", "cancelando"}
LOGGER = logging.getLogger("bibliotecario.jobs")


def event(db, job, name):
    number = (db.scalar(select(func.max(JobEvent.number)).where(JobEvent.job_id == job.id)) or 0) + 1
    db.add(JobEvent(job_id=job.id, number=number, event=name, attempt=job.attempts, generation=job.generation, created_at=int(time.time())))


def enqueue(db, document_id, version_id, actor_id, correlation_id, key, kind="convert", payload=None):
    now = int(time.time())
    job = IngestionJob(id=str(uuid.uuid4()), document_id=document_id, version_id=version_id, kind=kind,
                       actor_id=actor_id, correlation_id=correlation_id, idempotency_key=key,
                       status="pendiente", payload=payload or {}, progress=0, attempts=0, generation=0,
                       available_at=now, created_at=now, updated_at=now)
    db.add(job)
    db.flush()
    event(db, job, "queued")
    return job


def restore_version(db, job):
    if job.version_id:
        version = db.get(DocumentVersion, job.version_id)
        if job.kind == "index" and version and version.status not in {"retirado", "eliminado", "eliminando"}:
            document = db.get(Document, job.document_id)
            version.status = "publicado" if document.active_version_id == version.id else "requiere_revision"
            return
        if version and version.status not in {"publicado", "retirado", "eliminado"}:
            version.status = "requiere_revision" if version.current_revision_id else "subido"


@dataclass(frozen=True)
class Lease:
    id: str
    generation: int
    owner: str
    kind: str


def claim(sessions, settings, owner):
    now = int(time.time())
    with sessions() as db:
        expired = db.scalars(select(IngestionJob).where(
            IngestionJob.status.in_(["en_ejecucion", "cancelando"]), IngestionJob.lease_until <= now
        ).with_for_update(skip_locked=True)).all()
        for job in expired:
            job.lease_owner, job.lease_until = None, None
            job.updated_at = now
            if job.status == "cancelando":
                job.status = "cancelado"
                restore_version(db, job)
                event(db, job, "cancelled_after_lease_expired")
            elif job.attempts >= 3:
                job.status, job.error_code = "fallido", "lease_expired"
                if job.version_id:
                    if job.kind == "index":
                        restore_version(db, job)
                    else:
                        db.get(DocumentVersion, job.version_id).status = "error"
                event(db, job, "attempts_exhausted")
            else:
                job.status, job.available_at = "pendiente", now
                event(db, job, "lease_expired_requeued")
        scheduled = db.scalars(select(IngestionJob).where(
            IngestionJob.status == "reintentable", IngestionJob.available_at <= now
        ).with_for_update(skip_locked=True)).all()
        for job in scheduled:
            job.status = "pendiente"
        db.flush()
        job = db.scalar(select(IngestionJob).where(IngestionJob.status == "pendiente", IngestionJob.available_at <= now)
                        .order_by(IngestionJob.created_at, IngestionJob.id).with_for_update(skip_locked=True).limit(1))
        lease = None
        if job:
            job.status, job.lease_owner = "en_ejecucion", owner
            job.lease_until, job.updated_at = now + settings.job_lease_seconds, now
            job.attempts += 1
            job.generation += 1
            job.progress, job.error_code = 10, None
            if job.version_id and job.kind != "index":
                db.get(DocumentVersion, job.version_id).status = "procesando"
            elif job.version_id and job.kind == "index":
                version = db.get(DocumentVersion, job.version_id)
                if version.status in {"requiere_revision", "error", "indexando"}:
                    version.status = "indexando"
            event(db, job, "claimed")
            lease = Lease(job.id, job.generation, owner, job.kind)
        db.commit()
        return lease


def owned_job(db, lease):
    return db.scalar(select(IngestionJob).where(
        IngestionJob.id == lease.id, IngestionJob.generation == lease.generation,
        IngestionJob.lease_owner == lease.owner, IngestionJob.lease_until > int(time.time()),
        IngestionJob.status.in_(["en_ejecucion", "cancelando"])
    ).with_for_update())


def renew(sessions, settings, lease):
    with sessions() as db:
        job = owned_job(db, lease)
        if not job:
            return "lost"
        if job.status == "cancelando":
            return "cancel"
        job.lease_until = int(time.time()) + settings.job_lease_seconds
        job.updated_at = int(time.time())
        job.progress = min(85, job.progress + 5)
        db.commit()
        return "owned"


def finish_cancel(sessions, lease):
    with sessions() as db:
        job = owned_job(db, lease)
        if job and job.status == "cancelando":
            job.status, job.lease_owner, job.lease_until = "cancelado", None, None
            job.updated_at = int(time.time())
            restore_version(db, job)
            event(db, job, "cancelled")
            db.commit()


def fail(sessions, lease, code, permanent=False):
    with sessions() as db:
        job = owned_job(db, lease)
        if not job:
            return
        if job.status == "cancelando":
            job.status = "cancelado"
            restore_version(db, job)
        else:
            job.status = "fallido" if permanent or job.attempts >= 3 else "reintentable"
            job.error_code, job.available_at = code, int(time.time()) + 2 ** job.attempts
            if job.version_id:
                if job.status == "fallido" and job.kind != "index":
                    db.get(DocumentVersion, job.version_id).status = "error"
                else:
                    restore_version(db, job)
        job.lease_owner, job.lease_until = None, None
        job.updated_at = int(time.time())
        event(db, job, code)
        db.commit()


def finalize_conversion(sessions, settings, lease, result):
    target = None
    try:
        with sessions() as db:
            job = owned_job(db, lease)
            if not job or job.status != "en_ejecucion":
                return False
            version = db.scalar(select(DocumentVersion).where(DocumentVersion.id == job.version_id).with_for_update())
            document = db.get(Document, version.document_id)
            if document.deleted_at or document.deletion_requested:
                return False
            revision_id = str(uuid.uuid4())
            key = f"normalized/{version.id}/{revision_id}.md"
            target = storage_path(settings, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = result["markdown"].encode("utf-8")
            if len(content) > settings.normalized_max_bytes:
                raise ValueError("normalized_too_large")
            with target.open("xb") as handle:
                handle.write(content)
            revision = NormalizedRevision(id=revision_id, version_id=version.id, storage_key=key,
                number=(db.scalar(select(func.max(NormalizedRevision.number)).where(NormalizedRevision.version_id == version.id)) or 0) + 1,
                metadata_json=version.metadata_json,
                sha256=hashlib.sha256(content).hexdigest(), provenance=result["provenance"],
                diagnostics=result["diagnostics"], created_at=int(time.time()), actor_id=None)
            db.add(revision)
            db.flush()
            version.current_revision_id, version.status, version.reviewed_at = revision_id, "requiere_revision", None
            job.status, job.progress = "completado", 100
            job.lease_owner, job.lease_until = None, None
            job.updated_at = int(time.time())
            event(db, job, "converted")
            db.add(AuditEvent(actor_id=job.actor_id, action="document_converted", object_id=version.id,
                              correlation_id=job.correlation_id))
            db.commit()
            return True
    except BaseException:
        if target:
            target.unlink(missing_ok=True)
        raise


def process_delete(sessions, settings, lease):
    # Hold the job lock through file removal: cancellation/reclaim cannot overlap these effects.
    with sessions() as db:
        job = owned_job(db, lease)
        if not job or job.status != "en_ejecucion":
            return
        document = db.scalar(select(Document).where(Document.id == job.document_id).with_for_update())
        versions = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id)).all()
        ids = [version.id for version in versions]
        files = db.scalars(select(DocumentFile).where(DocumentFile.version_id.in_(ids))).all()
        revisions = db.scalars(select(NormalizedRevision).where(NormalizedRevision.version_id.in_(ids))).all()
        paths = [storage_path(settings, item.storage_key) for item in [*files, *revisions]]
        for path in paths:
            path.unlink(missing_ok=True)
        document.active_version_id, document.deleted_at, document.title = None, int(time.time()), "Documento eliminado"
        for version in versions:
            version.current_revision_id, version.metadata_json, version.status = None, {}, "eliminado"
        db.flush()
        db.execute(delete(Chunk).where(Chunk.version_id.in_(ids)))
        db.execute(delete(DocumentFile).where(DocumentFile.version_id.in_(ids)))
        db.execute(delete(NormalizedRevision).where(NormalizedRevision.version_id.in_(ids)))
        job.status, job.progress, job.updated_at = "completado", 100, int(time.time())
        job.lease_owner, job.lease_until = None, None
        event(db, job, "deleted")
        db.add(AuditEvent(actor_id=job.actor_id, action="document_deleted", object_id=document.id,
                          correlation_id=job.correlation_id))
        db.commit()


def process(sessions, settings, lease, stop):
    if lease.kind == "delete":
        try:
            process_delete(sessions, settings, lease)
        except Exception:
            fail(sessions, lease, "delete_failed")
        return
    with sessions() as db:
        job = owned_job(db, lease)
        if not job:
            return
        if lease.kind == "index":
            arguments = ["-m", "bibliotecario.index_task", "--revision", job.payload["revision_id"]]
        else:
            source = db.scalar(select(DocumentFile).where(DocumentFile.version_id == job.version_id))
            path, fmt = storage_path(settings, source.storage_key), source.format
            arguments = ["-m", "bibliotecario.convert_task", "--input", str(path), "--format", fmt]
    temporary = storage_path(settings, "normalized/.task-" + str(uuid.uuid4()) + ".json")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    from .admin_settings import public_settings
    child_env = os.environ.copy()
    child_env.update({"BIB_" + name.upper(): str(value) for name, value in public_settings(settings).items()})
    child = subprocess.Popen([sys.executable, *arguments, "--output", str(temporary)], env=child_env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started, renewed = time.monotonic(), 0
    try:
        while child.poll() is None:
            if stop.is_set():
                child.terminate()
                child.wait(timeout=10)
                fail(sessions, lease, "worker_stopped")
                return
            timeout = settings.index_timeout_seconds if lease.kind == "index" else settings.conversion_timeout_seconds
            if time.monotonic() - started > timeout:
                child.kill()
                child.wait(timeout=10)
                fail(sessions, lease, "conversion_timeout", permanent=True)
                return
            if time.monotonic() - renewed >= settings.job_lease_seconds / 3:
                state = renew(sessions, settings, lease)
                renewed = time.monotonic()
                if state != "owned":
                    child.terminate()
                    child.wait(timeout=10)
                    if state == "cancel":
                        finish_cancel(sessions, lease)
                    return
            stop.wait(0.2)
        state = renew(sessions, settings, lease)
        if state == "cancel":
            finish_cancel(sessions, lease)
        elif state == "owned":
            if child.returncode or not temporary.exists():
                fail(sessions, lease, "converter_process_failed")
            else:
                result = json.loads(temporary.read_text(encoding="utf-8"))
                if "error" in result:
                    fail(sessions, lease, result["error"], permanent=lease.kind != "index")
                else:
                    if lease.kind == "index":
                        from .indexing import finalize_index
                        finished = finalize_index(sessions, settings, lease, result)
                    else:
                        finished = finalize_conversion(sessions, settings, lease, result)
                    if not finished:
                        finish_cancel(sessions, lease)
    except Exception as exc:
        LOGGER.error("job_attempt_failed", extra={"correlation_id": lease.id, "error_type": type(exc).__name__})
        fail(sessions, lease, "conversion_failed")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        temporary.unlink(missing_ok=True)
