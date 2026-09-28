"""add germination execution provenance

Revision ID: f705a6bb943c
Revises: d50447b51d78
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f705a6bb943c'
down_revision: Union[str, None] = 'd50447b51d78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
        raise RuntimeError("SQLite foreign keys could not be paused for batch migration")

    with op.batch_alter_table("germination_dishes", recreate="always") as batch:
        batch.add_column(sa.Column("code", sa.String(80), nullable=True))
        batch.add_column(sa.Column("replicate_no", sa.Integer(), nullable=True))

    ranks = {}
    previous_experiment = None
    rank = 0
    for material_id, experiment_id in connection.execute(sa.text(
        "SELECT id, experiment_id FROM experiment_materials "
        "ORDER BY experiment_id, display_order, created_at, id"
    )):
        if experiment_id != previous_experiment:
            previous_experiment, rank = experiment_id, 0
        rank += 1
        ranks[material_id] = rank

    previous_material = None
    replicate = 0
    dishes = connection.execute(sa.text(
        "SELECT d.id, d.material_id, e.code FROM germination_dishes d "
        "JOIN experiment_materials m ON m.id=d.material_id "
        "JOIN experiments e ON e.id=m.experiment_id "
        "ORDER BY d.material_id, d.created_at, d.id"
    ))
    for dish_id, material_id, experiment_code in dishes:
        if material_id != previous_material:
            previous_material, replicate = material_id, 0
        replicate += 1
        code = f"{experiment_code}-M{ranks[material_id]:03d}-R{replicate:02d}"
        connection.execute(sa.text(
            "UPDATE germination_dishes SET code=:code, replicate_no=:replicate WHERE id=:id"
        ), {"code": code, "replicate": replicate, "id": dish_id})

    with op.batch_alter_table("germination_dishes", recreate="always") as batch:
        batch.alter_column("code", existing_type=sa.String(80), nullable=False)
        batch.alter_column("replicate_no", existing_type=sa.Integer(), nullable=False)
        batch.create_check_constraint("ck_dish_replicate_no", "replicate_no > 0")
        batch.create_unique_constraint("uq_dish_code", ["code"])
        batch.create_unique_constraint("uq_dish_material_replicate", ["material_id", "replicate_no"])

    with op.batch_alter_table("seedling_samples", recreate="always") as batch:
        batch.add_column(sa.Column("source_observation_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("position_label", sa.String(80), nullable=True))
        batch.create_foreign_key("fk_sample_source_observation", "germination_observations",
                                 ["source_observation_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_seedling_samples_source_observation_id", "seedling_samples", ["source_observation_id"])
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("SQLite foreign key check failed after Stage 2 upgrade")


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
        raise RuntimeError("SQLite foreign keys could not be paused for batch migration")

    op.drop_index("ix_seedling_samples_source_observation_id", table_name="seedling_samples")
    with op.batch_alter_table("seedling_samples", recreate="always") as batch:
        batch.drop_constraint("fk_sample_source_observation", type_="foreignkey")
        batch.drop_column("source_observation_id")
        batch.drop_column("position_label")

    with op.batch_alter_table("germination_dishes", recreate="always") as batch:
        batch.drop_constraint("ck_dish_replicate_no", type_="check")
        batch.drop_constraint("uq_dish_code", type_="unique")
        batch.drop_constraint("uq_dish_material_replicate", type_="unique")
        batch.drop_column("code")
        batch.drop_column("replicate_no")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("SQLite foreign key check failed after Stage 2 downgrade")
