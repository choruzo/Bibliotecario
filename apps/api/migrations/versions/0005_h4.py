"""Persistent grounded conversations and scope-specific evidence policies."""
from alembic import op
import sqlalchemy as sa
from bibliotecario.models import Conversation, Message

revision = "0005_h4"
down_revision = "0004_h3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evidence_policies", sa.Column("scope", sa.String(16), nullable=False, server_default="admin"))
    Conversation.__table__.create(op.get_bind())
    Message.__table__.create(op.get_bind())


def downgrade():
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_column("evidence_policies", "scope")
