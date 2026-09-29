"""Documentos, revisiones inmutables y cola persistente de ingesta."""
from alembic import op
import sqlalchemy as sa

revision = "0002_h2"
down_revision = "0001_h1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("documents",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("title", sa.String(300), nullable=False),
        sa.Column("active_version_id", sa.String(36)), sa.Column("deletion_requested", sa.Boolean, nullable=False),
        sa.Column("deleted_at", sa.Integer), sa.Column("created_at", sa.Integer, nullable=False))
    op.create_table("document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("number", sa.Integer, nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("original_sha256", sa.String(64), nullable=False), sa.Column("metadata_json", sa.JSON, nullable=False),
        sa.Column("current_revision_id", sa.String(36)), sa.Column("reviewed_at", sa.Integer),
        sa.Column("published_at", sa.Integer), sa.Column("retired_at", sa.Integer), sa.Column("created_at", sa.Integer, nullable=False),
        sa.UniqueConstraint("document_id", "number"),
        sa.CheckConstraint("status IN ('subido','procesando','requiere_revision','indexando','publicado','retirado','eliminando','eliminado','error')", name="version_state"))
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_table("document_files", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("document_versions.id"), nullable=False, unique=True),
        sa.Column("storage_key", sa.String(200), nullable=False, unique=True), sa.Column("original_name", sa.String(200), nullable=False),
        sa.Column("format", sa.String(8), nullable=False), sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False))
    op.create_table("normalized_revisions", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("number", sa.Integer, nullable=False), sa.Column("metadata_json", sa.JSON, nullable=False),
        sa.Column("storage_key", sa.String(200), nullable=False, unique=True), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("provenance", sa.JSON, nullable=False), sa.Column("diagnostics", sa.JSON, nullable=False),
        sa.Column("created_at", sa.Integer, nullable=False), sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("version_id", "number"))
    op.create_index("ix_normalized_revisions_version_id", "normalized_revisions", ["version_id"])
    op.create_foreign_key("fk_document_active_version", "documents", "document_versions", ["active_version_id"], ["id"])
    op.create_foreign_key("fk_version_current_revision", "document_versions", "normalized_revisions", ["current_revision_id"], ["id"])
    op.create_table("ingestion_jobs", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("document_versions.id")),
        sa.Column("kind", sa.String(16), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("correlation_id", sa.String(36), nullable=False), sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False), sa.Column("progress", sa.Integer, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False), sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("lease_owner", sa.String(36)), sa.Column("lease_until", sa.Integer),
        sa.Column("available_at", sa.Integer, nullable=False), sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.Integer, nullable=False), sa.Column("updated_at", sa.Integer, nullable=False),
        sa.UniqueConstraint("actor_id", "idempotency_key"),
        sa.CheckConstraint("status IN ('pendiente','en_ejecucion','completado','reintentable','fallido','cancelando','cancelado')", name="job_state"),
        sa.CheckConstraint("kind IN ('convert','delete')", name="job_kind"))
    for column in ("document_id", "version_id", "status"):
        op.create_index(f"ix_ingestion_jobs_{column}", "ingestion_jobs", [column])
    op.create_table("job_events", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("ingestion_jobs.id"), nullable=False),
        sa.Column("event", sa.String(64), nullable=False), sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("generation", sa.Integer, nullable=False), sa.Column("created_at", sa.Integer, nullable=False))
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])


def downgrade():
    op.drop_constraint("fk_document_active_version", "documents", type_="foreignkey")
    op.drop_constraint("fk_version_current_revision", "document_versions", type_="foreignkey")
    for name in ("job_events", "ingestion_jobs", "normalized_revisions", "document_files", "document_versions", "documents"):
        op.drop_table(name)
