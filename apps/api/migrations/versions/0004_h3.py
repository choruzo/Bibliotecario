"""Versioned vectors, PostgreSQL text search and retrieval traces."""
from alembic import op
import sqlalchemy as sa
from bibliotecario.models import Chunk, RetrievalRun, EvidencePolicy

revision = "0004_h3"
down_revision = "0003_h2_events"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("job_kind", "ingestion_jobs", type_="check")
    op.create_check_constraint("job_kind", "ingestion_jobs", "kind IN ('convert','delete','index')")
    for table in (Chunk.__table__, RetrievalRun.__table__, EvidencePolicy.__table__):
        table.create(op.get_bind())
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
