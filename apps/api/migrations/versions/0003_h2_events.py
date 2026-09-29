"""Orden monotono de eventos, tambien si ocurren en el mismo segundo."""
from alembic import op
import sqlalchemy as sa

revision = "0003_h2_events"
down_revision = "0002_h2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("job_events", sa.Column("number", sa.Integer, nullable=True))
    op.execute(sa.text("""WITH ranked AS (
        SELECT id, row_number() OVER (PARTITION BY job_id ORDER BY created_at, id) AS n FROM job_events
        ) UPDATE job_events SET number = ranked.n FROM ranked WHERE job_events.id = ranked.id"""))
    op.alter_column("job_events", "number", nullable=False)
    op.create_unique_constraint("uq_job_events_job_number", "job_events", ["job_id", "number"])


def downgrade():
    op.drop_constraint("uq_job_events_job_number", "job_events", type_="unique")
    op.drop_column("job_events", "number")
