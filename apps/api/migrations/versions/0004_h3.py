"""Versioned vectors, PostgreSQL text search and retrieval traces."""
from alembic import op
import sqlalchemy as sa
from bibliotecario.models import Chunk, RetrievalRun

revision = "0004_h3"
down_revision = "0003_h2_events"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("job_kind", "ingestion_jobs", type_="check")
    op.create_check_constraint("job_kind", "ingestion_jobs", "kind IN ('convert','delete','index')")
    for table in (Chunk.__table__, RetrievalRun.__table__):
        table.create(op.get_bind())
    # Freeze the H3 shape: importing the current ORM would include H4's scope
    # and make 0005 fail with a duplicate column on a fresh installation.
    op.create_table("evidence_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("corpus_signature", sa.String(64), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False))
    op.create_index("ix_evidence_policies_signature", "evidence_policies", ["signature"])
    op.execute("ALTER TABLE chunks ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (to_tsvector('spanish', search_content)) STORED")
    op.execute("CREATE INDEX ix_chunks_text ON chunks USING gin(search_vector)")
    # Exact vector search for the small MVP corpus; avoids approximate recall loss.


def downgrade():
    for name in ("evidence_policies", "retrieval_runs", "chunks"):
        op.drop_table(name)
    op.execute("DELETE FROM job_events WHERE job_id IN (SELECT id FROM ingestion_jobs WHERE kind='index')")
    op.execute("DELETE FROM ingestion_jobs WHERE kind='index'")
    op.drop_constraint("job_kind", "ingestion_jobs", type_="check")
    op.create_check_constraint("job_kind", "ingestion_jobs", "kind IN ('convert','delete')")
