"""Align seedling measurement days with germination-based DAG.

Revision ID: 9456099da4fd
Revises: 3179cf93a5f4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9456099da4fd'
down_revision: Union[str, None] = '3179cf93a5f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _prepare_sqlite_batch() -> None:
    """Pause FK enforcement for SQLite batch copies on this migration connection."""
    connection = op.get_bind()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    actual = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    if actual != 0:
        raise RuntimeError("Could not configure SQLite foreign key enforcement for batch migration")


def _verify_foreign_keys() -> None:
    # Alembic closes and disposes this connection after the migration. A fresh
    # connection enables FK checks again via make_engine's connect listener.
    if op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("SQLite foreign key check failed after DAG migration")


def upgrade() -> None:
    _prepare_sqlite_batch()
    with op.batch_alter_table('measurement_timepoints', recreate='always') as batch_op:
        batch_op.drop_constraint('ck_timepoint_day', type_='check')
        batch_op.drop_constraint('uq_timepoint_day', type_='unique')
        batch_op.alter_column('day_after_sowing', new_column_name='day_after_germination',
                              existing_type=sa.Integer(), existing_nullable=False)
        batch_op.create_check_constraint('ck_timepoint_dag_nonnegative', 'day_after_germination >= 0')
    op.create_index('uq_timepoint_experiment_dag', 'measurement_timepoints',
                    ['experiment_id', 'day_after_germination'], unique=True)
    with op.batch_alter_table('seedling_samples') as batch_op:
        batch_op.add_column(sa.Column('germinated_at', sa.DateTime(timezone=True), nullable=True))
    _verify_foreign_keys()


def downgrade() -> None:
    _prepare_sqlite_batch()
    op.drop_index('uq_timepoint_experiment_dag', table_name='measurement_timepoints')
    with op.batch_alter_table('seedling_samples') as batch_op:
        batch_op.drop_column('germinated_at')
    with op.batch_alter_table('measurement_timepoints', recreate='always') as batch_op:
        batch_op.drop_constraint('ck_timepoint_dag_nonnegative', type_='check')
        batch_op.alter_column('day_after_germination', new_column_name='day_after_sowing',
                              existing_type=sa.Integer(), existing_nullable=False)
        batch_op.create_check_constraint('ck_timepoint_day', 'day_after_sowing >= 0')
    with op.batch_alter_table('measurement_timepoints', recreate='always') as batch_op:
        batch_op.create_unique_constraint('uq_timepoint_day', ['experiment_id', 'day_after_sowing'])
    _verify_foreign_keys()
