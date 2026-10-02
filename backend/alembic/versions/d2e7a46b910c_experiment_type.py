"""Add explicit experiment workflow identity without changing existing codes.

Revision ID: d2e7a46b910c
Revises: c6d91f28a405
"""
from alembic import op
import sqlalchemy as sa

revision = "d2e7a46b910c"
down_revision = "c6d91f28a405"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite supports an inline CHECK in ADD COLUMN. No parent-table rebuild,
    # so all existing child foreign keys and EXP codes remain untouched.
    op.add_column("experiments", sa.Column("experiment_type", sa.String(8),
        sa.CheckConstraint("experiment_type IN ('GER')", name="ck_experiment_type"),
        server_default="GER", nullable=False))


def downgrade():
    op.drop_column("experiments", "experiment_type")
