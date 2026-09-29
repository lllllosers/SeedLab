"""Repair historical ImportJob file-hash index drift.

Revision ID: 0b6111724c00
Revises: e8b62c74a901
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0b6111724c00"
down_revision: Union[str, None] = "e8b62c74a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    index = next(
        (item for item in sa.inspect(connection).get_indexes("import_jobs")
         if item["name"] == "ix_import_jobs_file_hash"),
        None,
    )
    if index and index["unique"] and index["column_names"] == ["file_hash"]:
        return

    # Check before any DDL: SQLite index changes may not roll back on failure.
    duplicate = connection.execute(sa.text("""
        SELECT file_hash FROM import_jobs
        WHERE file_hash IS NOT NULL
        GROUP BY file_hash HAVING COUNT(*) > 1
        LIMIT 1
    """)).first()
    if duplicate:
        raise RuntimeError(
            "import_jobs 中存在重复的文件哈希，无法安全建立唯一索引。请先人工核对导入历史。"
        )

    if index:
        op.drop_index("ix_import_jobs_file_hash", table_name="import_jobs")
    op.create_index("ix_import_jobs_file_hash", "import_jobs", ["file_hash"], unique=True)


def downgrade() -> None:
    # This revision repairs drift in historical databases. The canonical
    # e8b62c74a901 schema already requires this unique index, so downgrading
    # must not recreate the incorrect non-unique index.
    pass
