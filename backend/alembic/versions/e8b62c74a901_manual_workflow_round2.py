"""Add material identity, confirmed numbering, and independent dish scheduling.

Revision ID: e8b62c74a901
Revises: a9c41e32b7d6
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8b62c74a901"
down_revision: Union[str, None] = "a9c41e32b7d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pause_sqlite_foreign_keys() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
            raise RuntimeError("SQLite foreign keys could not be paused for batch migration")


def _check_foreign_keys() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite" and connection.exec_driver_sql("PRAGMA foreign_key_check").first():
        raise RuntimeError("SQLite foreign key check failed after workflow migration")


def upgrade() -> None:
    _pause_sqlite_foreign_keys()
    op.add_column("taxa", sa.Column("genus", sa.String(255), nullable=True))
    op.add_column("taxa", sa.Column("life_form", sa.String(255), nullable=True))
    op.add_column("seed_lots", sa.Column("source_code", sa.String(120), nullable=True))
    op.add_column("experiments", sa.Column("numbering_locked_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("experiment_materials", recreate="always") as batch:
        batch.add_column(sa.Column("experiment_number", sa.Integer(), nullable=True))
        batch.create_check_constraint("ck_material_experiment_number", "experiment_number IS NULL OR experiment_number > 0")
        batch.create_unique_constraint("uq_material_experiment_number", ["experiment_id", "experiment_number"])
    with op.batch_alter_table("germination_dishes", recreate="always") as batch:
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cancel_reason", sa.Text(), nullable=True))
        batch.create_check_constraint("ck_dish_sown_or_cancelled", "sown_at IS NULL OR cancelled_at IS NULL")
    op.add_column("import_jobs", sa.Column("file_hash", sa.String(64), nullable=True))
    op.create_index("ix_import_jobs_file_hash", "import_jobs", ["file_hash"], unique=True)
    _check_foreign_keys()


def downgrade() -> None:
    _pause_sqlite_foreign_keys()
    op.drop_index("ix_import_jobs_file_hash", table_name="import_jobs")
    op.drop_column("import_jobs", "file_hash")
    with op.batch_alter_table("germination_dishes", recreate="always") as batch:
        batch.drop_constraint("ck_dish_sown_or_cancelled", type_="check")
        batch.drop_column("cancel_reason")
        batch.drop_column("cancelled_at")
    with op.batch_alter_table("experiment_materials", recreate="always") as batch:
        batch.drop_constraint("uq_material_experiment_number", type_="unique")
        batch.drop_constraint("ck_material_experiment_number", type_="check")
        batch.drop_column("experiment_number")
    op.drop_column("experiments", "numbering_locked_at")
    op.drop_column("seed_lots", "source_code")
    op.drop_column("taxa", "life_form")
    op.drop_column("taxa", "genus")
    _check_foreign_keys()
