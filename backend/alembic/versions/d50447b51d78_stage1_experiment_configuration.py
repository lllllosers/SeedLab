"""Add experiment defaults, material overrides, ordering, and ready status.

Revision ID: d50447b51d78
Revises: 9456099da4fd
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd50447b51d78'
down_revision: Union[str, None] = '9456099da4fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
        raise RuntimeError("SQLite foreign keys could not be paused for batch migration")

    with op.batch_alter_table('experiments', recreate='always') as batch:
        batch.drop_constraint('ck_experiment_status', type_='check')
        batch.add_column(sa.Column('planned_start_date', sa.Date(), nullable=True))
        batch.add_column(sa.Column('owner_id', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_experiment_owner', 'users', ['owner_id'], ['id'], ondelete='SET NULL')
        batch.create_check_constraint('ck_experiment_status', "status IN ('draft', 'ready', 'active', 'completed', 'cancelled')")
    op.create_index('ix_experiments_owner_id', 'experiments', ['owner_id'])

    with op.batch_alter_table('experiment_protocols', recreate='always') as batch:
        batch.drop_constraint('ck_protocol_seed_count', type_='check')
        batch.alter_column('seed_count_per_dish', new_column_name='seeds_per_dish',
                           existing_type=sa.Integer(), existing_nullable=True)
        batch.add_column(sa.Column('replicate_count', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('observation_period_days', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('sampling_rule', sa.String(40), nullable=True))
        batch.add_column(sa.Column('sample_count', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('sample_scope', sa.String(30), nullable=True))
        batch.add_column(sa.Column('germination_criterion', sa.Text(), nullable=True))
        batch.create_check_constraint('ck_protocol_seeds_per_dish', 'seeds_per_dish IS NULL OR seeds_per_dish > 0')
        batch.create_check_constraint('ck_protocol_replicate_count', 'replicate_count IS NULL OR replicate_count > 0')
        batch.create_check_constraint('ck_protocol_observation_period', 'observation_period_days IS NULL OR observation_period_days > 0')
        batch.create_check_constraint('ck_protocol_sample_count', 'sample_count IS NULL OR sample_count > 0')
        batch.create_check_constraint('ck_protocol_sample_scope', "sample_scope IS NULL OR sample_scope IN ('per_dish', 'per_material')")

    with op.batch_alter_table('experiment_materials', recreate='always') as batch:
        batch.add_column(sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('seeds_per_dish_override', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('replicate_count_override', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('sample_count_override', sa.Integer(), nullable=True))
        batch.create_check_constraint('ck_material_display_order', 'display_order >= 0')
        batch.create_check_constraint('ck_material_seeds_override', 'seeds_per_dish_override IS NULL OR seeds_per_dish_override > 0')
        batch.create_check_constraint('ck_material_replicates_override', 'replicate_count_override IS NULL OR replicate_count_override > 0')
        batch.create_check_constraint('ck_material_samples_override', 'sample_count_override IS NULL OR sample_count_override > 0')

    previous_experiment = None
    order = 0
    rows = connection.execute(sa.text('SELECT id, experiment_id FROM experiment_materials ORDER BY experiment_id, created_at, id'))
    for material_id, experiment_id in rows:
        if experiment_id != previous_experiment:
            previous_experiment, order = experiment_id, 0
        connection.execute(sa.text('UPDATE experiment_materials SET display_order=:order WHERE id=:id'),
                           {'order': order, 'id': material_id})
        order += 1
    if connection.exec_driver_sql('PRAGMA foreign_key_check').first() is not None:
        raise RuntimeError('SQLite foreign key check failed after Stage 1 upgrade')


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
        raise RuntimeError("SQLite foreign keys could not be paused for batch migration")

    with op.batch_alter_table('experiment_materials', recreate='always') as batch:
        for name in ('ck_material_display_order', 'ck_material_seeds_override',
                     'ck_material_replicates_override', 'ck_material_samples_override'):
            batch.drop_constraint(name, type_='check')
        for name in ('display_order', 'seeds_per_dish_override', 'replicate_count_override', 'sample_count_override'):
            batch.drop_column(name)

    with op.batch_alter_table('experiment_protocols', recreate='always') as batch:
        for name in ('ck_protocol_seeds_per_dish', 'ck_protocol_replicate_count',
                     'ck_protocol_observation_period', 'ck_protocol_sample_count', 'ck_protocol_sample_scope'):
            batch.drop_constraint(name, type_='check')
        for name in ('replicate_count', 'observation_period_days', 'sampling_rule',
                     'sample_count', 'sample_scope', 'germination_criterion'):
            batch.drop_column(name)
        batch.alter_column('seeds_per_dish', new_column_name='seed_count_per_dish',
                           existing_type=sa.Integer(), existing_nullable=True)
        batch.create_check_constraint('ck_protocol_seed_count',
                                      'seed_count_per_dish IS NULL OR seed_count_per_dish > 0')

    connection.execute(sa.text("UPDATE experiments SET status='draft' WHERE status='ready'"))
    op.drop_index('ix_experiments_owner_id', table_name='experiments')
    with op.batch_alter_table('experiments', recreate='always') as batch:
        batch.drop_constraint('ck_experiment_status', type_='check')
        batch.drop_constraint('fk_experiment_owner', type_='foreignkey')
        batch.drop_column('planned_start_date')
        batch.drop_column('owner_id')
        batch.create_check_constraint('ck_experiment_status', "status IN ('draft', 'active', 'completed', 'cancelled')")
    if connection.exec_driver_sql('PRAGMA foreign_key_check').first() is not None:
        raise RuntimeError('SQLite foreign key check failed after Stage 1 downgrade')
