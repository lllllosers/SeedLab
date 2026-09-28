"""Add the initial password change flag to users.

Revision ID: a9c41e32b7d6
Revises: f705a6bb943c
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9c41e32b7d6"
down_revision: Union[str, None] = "f705a6bb943c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(),
                                     server_default=sa.false(), nullable=False))
    connection = op.get_bind()
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("SQLite foreign key check failed after account upgrade")


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
        raise RuntimeError("SQLite foreign keys could not be paused for batch migration")
    with op.batch_alter_table("users", recreate="always") as batch:
        batch.drop_column("must_change_password")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("SQLite foreign key check failed after account downgrade")
