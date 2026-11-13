"""Declarative figures column on messages."""
from alembic import op
import sqlalchemy as sa

revision = "0007_h6"
down_revision = "0006_h5"
branch_labels = depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("figures", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade():
    op.drop_column("messages", "figures")
