"""Preserve the reason an experiment was terminated.

Revision ID: c6d91f28a405
Revises: b742b49a162e
"""
from alembic import op
import sqlalchemy as sa

revision = "c6d91f28a405"
down_revision = "b742b49a162e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("experiments", sa.Column("termination_reason", sa.Text(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT id FROM experiments WHERE termination_reason IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("已有实验终止原因，旧版本不能保存；请先备份并人工核对后再回退")
    op.drop_column("experiments", "termination_reason")
