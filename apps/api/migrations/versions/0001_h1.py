"""H1: autenticacion, auditoria y heartbeat; habilita pgvector."""
from alembic import op
import sqlalchemy as sa

revision = "0001_h1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("roles", sa.Column("name", sa.String(16), primary_key=True))
    op.bulk_insert(sa.table("roles", sa.column("name", sa.String)), [{"name": "admin"}, {"name": "usuario"}])
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.String(16), sa.ForeignKey("roles.name"), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.Integer, nullable=False))
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_table("audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("object_id", sa.String(36)),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("worker_status",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("heartbeat_at", sa.Integer, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.CheckConstraint("state IN ('idle', 'stopped')", name="worker_state"))


def downgrade():
    for name in ("worker_status", "audit_events", "sessions", "users", "roles"):
        op.drop_table(name)
    # The extension may be shared by other schemas; retain it.
