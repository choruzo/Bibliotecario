"""Administrative settings and persistent reindex batches."""
from alembic import op
import sqlalchemy as sa

revision = "0006_h5"
down_revision = "0005_h4"
branch_labels = depends_on = None


def upgrade():
    op.add_column("worker_status", sa.Column("settings_signature", sa.String(64)))
    op.create_table("app_settings", sa.Column("name", sa.String(64), primary_key=True),
                    sa.Column("value", sa.JSON(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False))
    op.create_table("reindex_batches", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
                    sa.Column("job_ids", sa.JSON(), nullable=False), sa.Column("created_at", sa.Integer(), nullable=False))


def downgrade():
    op.drop_table("reindex_batches")
    op.drop_table("app_settings")
    op.drop_column("worker_status", "settings_signature")
