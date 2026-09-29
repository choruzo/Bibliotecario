import asyncio
import hashlib
import json
import math
import time
from sqlalchemy import delete, select

from .chunking import split_blocks
from .jobs import owned_job, event
from .models import AuditEvent, Chunk, Document, DocumentVersion, NormalizedRevision
from .providers import ModelClients, ProviderError
from .storage import storage_path


def model_signature(settings):
    contract = ["h3-v2", settings.embedding_base_url, settings.embedding_model,
                settings.embedding_dimensions, settings.reranker_base_url, settings.reranker_model]
    return hashlib.sha256(json.dumps(contract).encode()).hexdigest()


async def build_index(settings, revision, clients):
    if settings.embedding_dimensions != 768:
        raise ProviderError("h3_requires_768_dimensions")
    path = storage_path(settings, revision.storage_key)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != revision.sha256:
        raise ValueError("revision_hash_mismatch")
    markdown = data.decode("utf-8")
    chunks = split_blocks(markdown, revision.provenance)
    if not chunks:
        raise ValueError("empty_document")
    if ''.join(''.join(c['content'] for c in chunks).split()) != ''.join(markdown.split()):
        raise ValueError("chunk_coverage_loss")
    for chunk in chunks:
        # Verify the real llama.cpp tokenizer including Nomic prefix. Never truncate silently.
        count = await clients.embedding_tokens("search_document: " + chunk["search_content"])
        if count > 1000:
            raise ProviderError("embedding_context_exceeded")
        chunk["embedding"] = (await clients.embed([chunk["search_content"]]))[0]
    return {"revision_id": revision.id, "sha256": revision.sha256,
            "model_signature": model_signature(settings), "chunks": chunks, "coverage_verified": True}


def finalize_index(sessions, settings, lease, result):
    with sessions() as db:
        job = owned_job(db, lease)
        if not job or job.status != "en_ejecucion":
            return False
        # Same document -> version order as draft edits and withdrawals.
        document = db.scalar(select(Document).where(Document.id == job.document_id).with_for_update())
        version = db.scalar(select(DocumentVersion).where(DocumentVersion.id == job.version_id).with_for_update())
        revision = db.get(NormalizedRevision, version.current_revision_id)
        if (document.deleted_at or document.deletion_requested or not version.reviewed_at
                or version.status not in {"indexando", "publicado"} or version.current_revision_id != job.payload["revision_id"]
                or document.active_version_id != job.payload.get("active_version_id")
                or result["revision_id"] != revision.id or result["sha256"] != revision.sha256
                or result["model_signature"] != model_signature(settings)):
            raise ValueError("index_snapshot_changed")
        chunks = result["chunks"]
        if not chunks or any(len(c["embedding"]) != 768 or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in c["embedding"])
                or not any(c["embedding"]) for c in chunks):
            raise ProviderError("invalid_embedding")
        db.execute(delete(Chunk).where(Chunk.version_id == version.id))
        for number, chunk in enumerate(chunks):
            db.add(Chunk(version_id=version.id, revision_id=revision.id, number=number,
                         content=chunk["content"], search_content=chunk["search_content"],
                         provenance=chunk["provenance"], embedding=chunk["embedding"],
                         model_signature=result["model_signature"]))
        if document.active_version_id and document.active_version_id != version.id:
            previous = db.get(DocumentVersion, document.active_version_id)
            previous.status, previous.retired_at = "retirado", int(time.time())
        version.status, version.published_at, version.retired_at = "publicado", int(time.time()), None
        document.active_version_id = version.id
        job.status, job.progress, job.updated_at = "completado", 100, int(time.time())
        job.lease_owner, job.lease_until = None, None
        event(db, job, "indexed_and_published")
        db.add(AuditEvent(actor_id=job.actor_id, action="document_published", object_id=version.id,
                          correlation_id=job.correlation_id))
        db.commit()
        return True
